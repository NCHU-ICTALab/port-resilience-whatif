"""Run public-priority and CP-SAT on the same historical scheduling case."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .baselines import schedule_public_priority
from .data_adapter import build_historical_case
from .exact import solve_cp_sat
from .model import ScheduleResult


def _metrics(result: ScheduleResult) -> dict[str, Any]:
    commercial = [item for item in result.assignments if item.identity == "commercial"]
    return {
        "scheduled_vessels": len(result.assignments),
        "unscheduled_vessels": len(result.unscheduled_ship_ids),
        "commercial_wait_minutes": round(sum(item.wait_hours for item in commercial) * 60),
        "mean_commercial_wait_hours": (
            round(sum(item.wait_hours for item in commercial) / len(commercial), 3)
            if commercial else None
        ),
        "makespan_hour": round(
            max((item.berth_end_hour for item in result.assignments), default=0), 3
        ),
        "changed_berths": sum(item.changed_berth for item in result.assignments),
        "constraint_violations": result.constraint_violations,
    }


def compare_case(
    movements_db: Path,
    berth_specs: Path,
    observed_at: datetime,
    *,
    horizon_hours: float = 72,
    limit: int = 20,
    outage_berth: str | None = "1068",
    time_limit_seconds: float = 30,
) -> dict[str, Any]:
    case = build_historical_case(
        movements_db,
        berth_specs,
        observed_at,
        horizon_hours=horizon_hours,
        limit=limit,
        outage_berth=outage_berth,
    )
    baseline = schedule_public_priority(
        case.scheduling_vessels, case.berths, case.windows, case.outages
    )
    exact = solve_cp_sat(
        case.scheduling_vessels,
        case.berths,
        case.windows,
        case.outages,
        time_limit_seconds=time_limit_seconds,
    )
    optimality_gap = None
    if exact.objective_value is not None and exact.best_objective_bound is not None:
        denominator = max(1.0, abs(exact.objective_value))
        optimality_gap = max(
            0.0, (exact.objective_value - exact.best_objective_bound) / denominator
        )
    return {
        "case_id": case.case_id,
        "vessels": len(case.vessels),
        "berths": len(case.berths),
        "windows": len(case.windows),
        "outages": [outage.berth_code for outage in case.outages],
        "public_priority": _metrics(baseline),
        "cp_sat": {
            **_metrics(exact.result),
            "status": exact.status,
            "objective_value": exact.objective_value,
            "best_objective_bound": exact.best_objective_bound,
            "relative_optimality_gap": round(optimality_gap, 6)
            if optimality_gap is not None else None,
            "wall_time_seconds": round(exact.wall_time_seconds, 3),
            "objective_components": exact.metrics,
        },
        "interpretation": (
            "Algorithm-to-rule-emulation comparison under shared modeled inputs; "
            "this is not a claim against actual port operations."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movements-db", type=Path, required=True)
    parser.add_argument("--berth-specs", type=Path, required=True)
    parser.add_argument("--start", required=True, help="Asia/Taipei local ISO time")
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--outage-berth", default="1068")
    parser.add_argument("--time-limit", type=float, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = compare_case(
        args.movements_db,
        args.berth_specs,
        datetime.fromisoformat(args.start),
        horizon_hours=args.hours,
        limit=args.limit,
        outage_berth=args.outage_berth,
        time_limit_seconds=args.time_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
