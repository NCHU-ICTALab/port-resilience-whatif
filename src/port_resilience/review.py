"""Export verified Pareto schedules as a human decision-review packet."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .baselines import schedule_public_priority
from .data_adapter import HistoricalCase, build_historical_case
from .feasibility import validate_schedule
from .nsga2 import Nsga2Report, schedule_kpis, solve_nsga2
from .scenario_overlay import load_military_input


def _delta(value: float | int | None, baseline: float | int | None) -> float | None:
    if value is None or baseline is None:
        return None
    return round(float(value) - float(baseline), 3)


def _candidate_payload(
    candidate: Any,
    case: HistoricalCase,
    baseline_kpis: dict[str, Any],
    recommended_for: list[str],
) -> dict[str, Any]:
    vessel_by_id = {item.vessel.ship_id: item.vessel for item in case.vessels}
    berth_by_code = {berth.code: berth for berth in case.berths}
    assignments = []
    for assignment in candidate.result.assignments:
        vessel = vessel_by_id[assignment.ship_id]
        berth = berth_by_code[assignment.berth_code]
        assignments.append(
            {
                **asdict(assignment),
                "original_berth": vessel.original_berth,
                "assigned_terminal": berth.terminal,
                "eta_hour": vessel.eta_hour,
                "service_hours": vessel.service_hours,
                "deadline_hour": vessel.deadline_hour,
                "planned_start_hour": vessel.planned_start_hour,
            }
        )
    comparable = (
        "commercial_total_wait_hours",
        "commercial_mean_wait_hours",
        "commercial_p90_wait_hours",
        "schedule_completion_hour",
        "changed_berths",
        "modeled_max_waiting_queue",
    )
    return {
        "candidate_id": candidate.candidate_id,
        "source": candidate.source,
        "recommended_for_profiles": recommended_for,
        "objectives": candidate.objectives,
        "kpis": candidate.kpis,
        "delta_vs_public_priority": {
            key: _delta(candidate.kpis.get(key), baseline_kpis.get(key))
            for key in comparable
        },
        "profile_scores_lower_is_better": candidate.profile_scores,
        "feasibility": {
            "verified": not candidate.constraint_violations,
            "constraint_violations": list(candidate.constraint_violations),
        },
        "assignments": assignments,
    }


def build_review_packet(
    case: HistoricalCase,
    *,
    population_size: int = 80,
    generations: int = 80,
    seed: int = 42,
    max_candidates: int = 12,
) -> dict[str, Any]:
    baseline = schedule_public_priority(
        case.scheduling_vessels, case.berths, case.windows, case.outages
    )
    baseline_feasibility = validate_schedule(
        baseline, case.scheduling_vessels, case.berths, case.windows, case.outages
    )
    report: Nsga2Report = solve_nsga2(
        case.scheduling_vessels,
        case.berths,
        case.windows,
        case.outages,
        population_size=population_size,
        generations=generations,
        seed=seed,
        max_candidates=max_candidates,
    )
    baseline_kpis = schedule_kpis(baseline, case.scheduling_vessels)
    recommendations: dict[str, list[str]] = {}
    for profile, candidate_id in report.profile_recommendations.items():
        recommendations.setdefault(candidate_id, []).append(profile)
    provenance = Counter(
        source for item in case.vessels for source in item.provenance.values()
    )
    military_count = sum(
        item.vessel.identity == "military" for item in case.vessels
    )
    return {
        "schema_version": "resilience.human_review.v1",
        "review_status": "awaiting_human_evaluation",
        "case": {
            "case_id": case.case_id,
            "observed_at": case.observed_at,
            "horizon_hours": case.horizon_hours,
            "vessels": len(case.vessels),
            "military_vessels": military_count,
            "berths": len(case.berths),
            "safety_windows": len(case.windows),
            "outages": [asdict(outage) for outage in case.outages],
            "source_metadata": case.metadata,
            "provenance_counts": dict(provenance),
        },
        "algorithm_run": {
            "solver": "NSGA-II",
            "population_size": report.population_size,
            "generations": report.generations,
            "evaluations": report.evaluations,
            "seed": report.seed,
            "wall_time_seconds": round(report.wall_time_seconds, 3),
            "pareto_candidates": len(report.candidates),
            "throughput_acceptance_floor": report.baseline_scheduled_vessels,
            "profile_recommendations": report.profile_recommendations,
            "objective_degeneracy": (
                "military objective inactive because no military scenario input was supplied"
                if military_count == 0 else None
            ),
        },
        "public_priority_baseline": {
            "kpis": baseline_kpis,
            "feasibility": {
                "verified": baseline_feasibility.feasible,
                "constraint_violations": list(baseline_feasibility.violation_codes),
            },
        },
        "pareto_candidates": [
            _candidate_payload(
                candidate,
                case,
                baseline_kpis,
                recommendations.get(candidate.candidate_id, []),
            )
            for candidate in report.candidates
        ],
        "human_decision": {
            "selected_candidate_id": None,
            "reviewer": None,
            "reviewed_at": None,
            "disposition": None,
            "comments": [],
        },
        "review_readiness": (
            "requires_scenario_owner_inputs"
            if military_count == 0 else "candidate_selection_ready"
        ),
        "required_human_inputs": [
            {
                "id": "military_missions",
                "status": "missing" if military_count == 0 else "provided_as_scenario_input",
                "question": "請輸入或確認軍事船舶、預定時程、deadline、保留泊位與不可延誤任務。",
                "impact": "未提供時，軍方排程偏離目標固定為 0，不能作商軍戰時方案驗收。",
            },
            {
                "id": "arrival_semantics",
                "status": "requires_confirmation",
                "question": "pilot_apply_time 是否可作為排程當下已知的進港申請／ready time proxy？",
                "impact": "若不可，等待時間與佇列 KPI 必須改用港方當時可見 ETA。",
            },
            {
                "id": "vessel_dimensions",
                "status": "requires_replacement",
                "question": "請以真實 LOA、吃水、船貨種類覆蓋 GT 推估值。",
                "impact": "目前適泊集合仍可能高估或低估。",
            },
            {
                "id": "terminal_interchange",
                "status": "conservative_same_terminal_only",
                "question": "確認哪些 operator／貨種允許跨 terminal 改泊，以及堆場與裝卸設備限制。",
                "impact": "目前不會自動跨 terminal，候選較保守。",
            },
            {
                "id": "marine_resources",
                "status": "missing",
                "question": "請提供各時段引水、拖船、航道方向與可用量。",
                "impact": "目前只用安全窗口、max releases 與 headway 代理，不能視為完整 VTS 仿真。",
            },
            {
                "id": "preference_profile",
                "status": "requires_selection",
                "question": "請選擇軍方優先、港口韌性、商船友善、均衡，或提供核准權重。",
                "impact": "權重只排序已通過硬限制的 Pareto 候選，不會交換安全限制。",
            },
        ],
        "use_restrictions": [
            "這是決策支援候選，不是 VTS、港務或軍事命令。",
            "比較對象是本專案的公開優先規則仿真，不是實際港方戰時績效。",
            "未補齊軍事任務與海事資源前，不得宣稱已完成真實商軍排程驗證。",
            "歷史 pass_port_time 與實際服務時間只作事後評估，不提供給求解器。",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movements-db", type=Path, required=True)
    parser.add_argument("--berth-specs", type=Path, required=True)
    parser.add_argument("--start", required=True, help="Asia/Taipei local ISO time")
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--outage-berth", default="1068")
    parser.add_argument("--population", type=int, default=80)
    parser.add_argument("--generations", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument(
        "--military-input",
        type=Path,
        help="human-authorized resilience.military-input.v1 JSON",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    case = build_historical_case(
        args.movements_db,
        args.berth_specs,
        datetime.fromisoformat(args.start),
        horizon_hours=args.hours,
        limit=args.limit,
        outage_berth=args.outage_berth,
    )
    if args.military_input:
        case = load_military_input(case, args.military_input)
    packet = build_review_packet(
        case,
        population_size=args.population,
        generations=args.generations,
        seed=args.seed,
        max_candidates=args.max_candidates,
    )
    serialized = json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
