"""Build reproducible 72-hour scheduling cases from the local movement archive."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .baselines import schedule_public_priority
from .model import Berth, BerthOutage, SafetyWindow, ScheduleResult, Vessel


CONTAINER_TERMINALS = {
    "CT1": frozenset({40, 41, 42, 43}),
    "CT2": frozenset({63, 64, 65, 66}),
    "CT3": frozenset({68, 69, 70}),
    "CT5": frozenset(range(74, 82)),
    "CT6": frozenset(range(108, 112)),
    "CT4": frozenset(range(115, 122)),
}
CONTAINER_BERTHS = frozenset().union(*CONTAINER_TERMINALS.values())
LOA_INTERCEPT_M = 52.944
LOA_SQRT_GT_COEFFICIENT = 0.815


@dataclass(frozen=True)
class EvaluationTruth:
    actual_channel_entry_hour: float | None
    actual_berth_start_hour: float | None
    actual_service_hours: float | None


@dataclass(frozen=True)
class CaseVessel:
    vessel: Vessel
    provenance: dict[str, str]
    truth: EvaluationTruth
    service_calibration_count: int


@dataclass(frozen=True)
class HistoricalCase:
    case_id: str
    observed_at: str
    horizon_hours: float
    vessels: tuple[CaseVessel, ...]
    berths: tuple[Berth, ...]
    windows: tuple[SafetyWindow, ...]
    outages: tuple[BerthOutage, ...]
    metadata: dict[str, Any]

    @property
    def scheduling_vessels(self) -> tuple[Vessel, ...]:
        return tuple(item.vessel for item in self.vessels)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.expanduser().resolve()}?mode=ro", uri=True)


def _relative_hour(value: str | None, start: datetime) -> float | None:
    if not value:
        return None
    return (datetime.fromisoformat(value) - start).total_seconds() / 3600


def _berth_number(code: str) -> int | None:
    if len(code) == 4 and code.startswith("1") and code[1:].isdigit():
        return int(code[1:])
    return None


def _terminal_for_berth(number: int | None) -> str | None:
    return next(
        (terminal for terminal, numbers in CONTAINER_TERMINALS.items() if number in numbers),
        None,
    )


def _estimate_loa_m(gt: float, berth_length_m: float) -> float:
    empirical = LOA_INTERCEPT_M + LOA_SQRT_GT_COEFFICIENT * math.sqrt(max(gt, 1))
    return round(min(max(empirical, 40.0), berth_length_m * 0.95, 400.0), 2)


def _estimate_draft_m(gt: float, berth_depth_m: float) -> float:
    heuristic = 2.5 + 0.035 * math.sqrt(max(gt, 1))
    return round(min(max(heuristic, 3.0), berth_depth_m * 0.95, 16.0), 2)


def load_container_berths(specs_path: Path) -> tuple[Berth, ...]:
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    result = []
    for code, value in specs.items():
        number = _berth_number(code)
        if number not in CONTAINER_BERTHS or not isinstance(value, dict):
            continue
        length = value.get("length_m")
        depth = value.get("depth_m")
        if not isinstance(length, (int, float)) or not isinstance(depth, (int, float)):
            continue
        result.append(
            Berth(
                code,
                float(length),
                float(depth),
                frozenset({"container"}),
                terminal=_terminal_for_berth(number),
            )
        )
    return tuple(sorted(result, key=lambda berth: berth.code))


def build_daily_windows(horizon_hours: float) -> tuple[SafetyWindow, ...]:
    templates = ((6.0, 7.5, 5), (12.0, 13.5, 5), (18.0, 19.0, 3))
    windows = []
    for day in range(math.ceil(horizon_hours / 24)):
        for index, (start, end, maximum) in enumerate(templates, start=1):
            absolute_start = day * 24 + start
            absolute_end = day * 24 + end
            if absolute_start >= horizon_hours:
                continue
            windows.append(
                SafetyWindow(
                    window_id=f"day-{day + 1}-window-{index}",
                    start_hour=absolute_start,
                    end_hour=min(absolute_end, horizon_hours),
                    max_releases=maximum,
                    channel_headway_minutes=15,
                )
            )
    return tuple(windows)


def _calibration_service_times(
    connection: sqlite3.Connection,
    cutoff: datetime,
    known_berths: set[str],
) -> tuple[dict[str, list[float]], list[float], str | None]:
    by_berth: dict[str, list[float]] = defaultdict(list)
    pooled: list[float] = []
    latest_departure: str | None = None
    rows = connection.execute(
        """
        SELECT berth_code, berth_time, depart_time
        FROM movements
        WHERE direction = '進港'
          AND berth_time IS NOT NULL
          AND depart_time IS NOT NULL
          AND depart_time < ?
        """,
        (cutoff.isoformat(),),
    )
    for berth_code, berth_time, depart_time in rows:
        if berth_code not in known_berths:
            continue
        duration = (
            datetime.fromisoformat(depart_time) - datetime.fromisoformat(berth_time)
        ).total_seconds() / 3600
        if 0 < duration <= 24 * 7:
            by_berth[berth_code].append(duration)
            pooled.append(duration)
            latest_departure = max(latest_departure or depart_time, depart_time)
    return dict(by_berth), pooled, latest_departure


def _estimated_service_hours(
    berth_code: str,
    by_berth: dict[str, list[float]],
    pooled: list[float],
) -> tuple[float, int, str]:
    local = by_berth.get(berth_code, [])
    if len(local) >= 3:
        return round(statistics.median(local), 3), len(local), "historical_berth_median"
    if pooled:
        return round(statistics.median(pooled), 3), len(pooled), "historical_container_median"
    return 12.0, 0, "scenario_default"


def build_historical_case(
    movements_db: Path,
    berth_specs: Path,
    observed_at: datetime,
    horizon_hours: float = 72,
    limit: int = 30,
    outage_berth: str | None = "1068",
    outage_start_hour: float = 10,
    outage_duration_hours: float = 48,
) -> HistoricalCase:
    if observed_at.tzinfo is not None:
        raise ValueError("observed_at must be a naive Asia/Taipei local datetime")
    if horizon_hours <= 0 or limit <= 0:
        raise ValueError("horizon_hours and limit must be positive")

    berths = load_container_berths(berth_specs)
    berth_by_code = {berth.code: berth for berth in berths}
    end_at = observed_at + timedelta(hours=horizon_hours)
    connection = _connect_read_only(movements_db)
    try:
        by_berth, pooled, latest_calibration_departure = _calibration_service_times(
            connection, observed_at, set(berth_by_code)
        )
        rows = list(
            connection.execute(
                """
                SELECT pilot_apply_time, pass_port_time, berth_time, depart_time,
                       berth_code, gross_tonnage, visa_no
                FROM movements
                WHERE direction = '進港'
                  AND pilot_apply_time >= ?
                  AND pilot_apply_time < ?
                ORDER BY pilot_apply_time, visa_no
                """,
                (observed_at.isoformat(), end_at.isoformat()),
            )
        )
    finally:
        connection.close()

    excluded = Counter()
    case_vessels = []
    for row in rows:
        pilot_apply, pass_port, berth_time, depart_time, berth_code, gt, _visa = row
        if berth_code not in berth_by_code:
            excluded["non_container_or_missing_berth_spec"] += 1
            continue
        if not isinstance(gt, (int, float)) or gt <= 0:
            excluded["missing_gt"] += 1
            continue
        berth = berth_by_code[berth_code]
        service_hours, calibration_count, service_source = _estimated_service_hours(
            berth_code, by_berth, pooled
        )
        eta_hour = _relative_hour(pilot_apply, observed_at)
        if eta_hour is None:
            excluded["missing_pilot_apply_time"] += 1
            continue
        actual_berth_start = _relative_hour(berth_time, observed_at)
        actual_departure = _relative_hour(depart_time, observed_at)
        actual_service = None
        if actual_berth_start is not None and actual_departure is not None:
            duration = actual_departure - actual_berth_start
            actual_service = round(duration, 3) if duration > 0 else None
        index = len(case_vessels) + 1
        vessel = Vessel(
            ship_id=f"V{index:03d}",
            identity="commercial",
            eta_hour=round(eta_hour, 3),
            ready_hour=round(eta_hour, 3),
            service_hours=service_hours,
            loa_m=_estimate_loa_m(float(gt), berth.length_m),
            draft_m=_estimate_draft_m(float(gt), berth.depth_m),
            ship_type="container",
            original_berth=berth_code,
            allowed_terminals=frozenset({berth.terminal}) if berth.terminal else frozenset(),
        )
        case_vessels.append(
            CaseVessel(
                vessel=vessel,
                provenance={
                    "eta_hour": "observed_pilot_apply_time_proxy",
                    "ready_hour": "observed_pilot_apply_time_proxy",
                    "original_berth": "observed",
                    "gross_tonnage": "observed",
                    "loa_m": "estimated_from_gt_capped_by_observed_berth",
                    "draft_m": "estimated_from_gt_capped_by_observed_berth",
                    "service_hours": service_source,
                    "identity": "scenario_input",
                },
                truth=EvaluationTruth(
                    actual_channel_entry_hour=_relative_hour(pass_port, observed_at),
                    actual_berth_start_hour=actual_berth_start,
                    actual_service_hours=actual_service,
                ),
                service_calibration_count=calibration_count,
            )
        )
    eligible_vessels = len(case_vessels)
    case_vessels = case_vessels[:limit]

    outages = ()
    if outage_berth and outage_berth in berth_by_code:
        outages = (
            BerthOutage(
                berth_code=outage_berth,
                start_hour=outage_start_hour,
                end_hour=outage_start_hour + outage_duration_hours,
            ),
        )
    return HistoricalCase(
        case_id=f"khh-{observed_at:%Y%m%dT%H%M}-{int(horizon_hours)}h",
        observed_at=observed_at.isoformat(),
        horizon_hours=horizon_hours,
        vessels=tuple(case_vessels),
        berths=berths,
        windows=build_daily_windows(horizon_hours),
        outages=outages,
        metadata={
            "source_rows_in_window": len(rows),
            "eligible_vessels": eligible_vessels,
            "selected_vessels": len(case_vessels),
            "truncated_eligible_vessels": max(0, eligible_vessels - len(case_vessels)),
            "excluded": dict(excluded),
            "service_calibration_rows": len(pooled),
            "service_calibration_latest_departure": latest_calibration_departure,
            "service_calibration_cutoff": observed_at.isoformat(),
            "identifiers": "pseudonymized_by_case_order",
            "arrival_proxy": (
                "pilot_apply_time is used as request readiness; pass_port_time is "
                "evaluation truth and is not exposed to the scheduler"
            ),
            "loa_model": {
                "formula": "52.944 + 0.815 * sqrt(gross_tonnage)",
                "fit_pairs": 470,
                "median_absolute_error_m": 10.57,
            },
        },
    )


def case_summary(case: HistoricalCase, result: ScheduleResult) -> dict[str, Any]:
    provenance = Counter(
        source for item in case.vessels for source in item.provenance.values()
    )
    truth_pairs = [
        (item.vessel.service_hours, item.truth.actual_service_hours)
        for item in case.vessels
        if item.truth.actual_service_hours is not None
    ]
    truth_errors = [abs(estimated - actual) for estimated, actual in truth_pairs]
    return {
        "case_id": case.case_id,
        "observed_at": case.observed_at,
        "horizon_hours": case.horizon_hours,
        "vessels": len(case.vessels),
        "berths": len(case.berths),
        "safety_windows": len(case.windows),
        "outages": [asdict(outage) for outage in case.outages],
        "metadata": case.metadata,
        "provenance_counts": dict(provenance),
        "service_estimate_quality": {
            "truth_pairs": len(truth_pairs),
            "mean_absolute_error_hours": round(statistics.mean(truth_errors), 3)
            if truth_errors else None,
            "median_absolute_error_hours": round(statistics.median(truth_errors), 3)
            if truth_errors else None,
            "warning": "evaluation-only; actual service is not exposed to the scheduler",
        },
        "baseline": {
            "assigned": len(result.assignments),
            "unscheduled": len(result.unscheduled_ship_ids),
            "constraint_violations": result.constraint_violations,
            "mean_wait_hours": round(
                statistics.mean(item.wait_hours for item in result.assignments), 3
            ) if result.assignments else None,
            "assignments": [asdict(item) for item in result.assignments],
            "unscheduled_ship_ids": result.unscheduled_ship_ids,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movements-db", type=Path, required=True)
    parser.add_argument("--berth-specs", type=Path, required=True)
    parser.add_argument("--start", required=True, help="Asia/Taipei local ISO time")
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--outage-berth", default="1068")
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
    result = schedule_public_priority(
        case.scheduling_vessels, case.berths, case.windows, case.outages
    )
    print(json.dumps(case_summary(case, result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
