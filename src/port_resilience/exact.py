"""Small-instance CP-SAT oracle for convoy release and berth assignment."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .model import (
    Assignment,
    Berth,
    BerthOutage,
    SafetyWindow,
    ScheduleResult,
    Vessel,
    berth_has_outage,
    berth_is_compatible,
)


MINUTES_PER_HOUR = 60


@dataclass(frozen=True)
class ExactSolveReport:
    result: ScheduleResult
    status: str
    objective_value: float | None
    best_objective_bound: float | None
    wall_time_seconds: float
    metrics: dict[str, float | int]


@dataclass(frozen=True)
class _Candidate:
    vessel: Vessel
    berth: Berth
    window: SafetyWindow
    slot_index: int
    start_minute: int
    end_minute: int
    wait_minutes: int
    military_deviation_minutes: int
    changed_berth: bool
    selected: cp_model.IntVar


def _minute(hour: float) -> int:
    return round(hour * MINUTES_PER_HOUR)


def _empty_report(
    vessels: tuple[Vessel, ...], status: str, wall_time_seconds: float = 0.0
) -> ExactSolveReport:
    return ExactSolveReport(
        result=ScheduleResult((), tuple(sorted(v.ship_id for v in vessels))),
        status=status,
        objective_value=None,
        best_objective_bound=None,
        wall_time_seconds=wall_time_seconds,
        metrics={
            "scheduled_vessels": 0,
            "unscheduled_commercial": sum(v.identity == "commercial" for v in vessels),
            "military_schedule_deviation_minutes": 0,
            "commercial_wait_minutes": 0,
            "makespan_minutes": 0,
            "changed_berths": 0,
        },
    )


def solve_cp_sat(
    vessels: tuple[Vessel, ...],
    berths: tuple[Berth, ...],
    windows: tuple[SafetyWindow, ...],
    outages: tuple[BerthOutage, ...] = (),
    *,
    time_limit_seconds: float = 30.0,
    random_seed: int = 0,
) -> ExactSolveReport:
    """Solve a small case with deterministic, lexicographically scaled objectives.

    Objective priority is: commercial vessels served, military plan deviation,
    commercial waiting, makespan, then changed berths. Military tasks are mandatory
    and deadlines are hard constraints.
    """
    if len({v.ship_id for v in vessels}) != len(vessels):
        raise ValueError("ship_id values must be unique")
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")

    model = cp_model.CpModel()
    by_vessel: dict[str, list[_Candidate]] = {v.ship_id: [] for v in vessels}
    by_berth: dict[str, list[cp_model.IntervalVar]] = {b.code: [] for b in berths}
    by_slot: dict[tuple[str, int], list[cp_model.IntVar]] = {}

    for vessel in vessels:
        ready_hour = max(vessel.eta_hour, vessel.ready_hour)
        duration_minutes = max(1, math.ceil(vessel.service_hours * MINUTES_PER_HOUR))
        for window in sorted(windows, key=lambda item: item.start_hour):
            for slot_index, start_hour in enumerate(window.release_slots()):
                if start_hour + 1e-9 < ready_hour:
                    continue
                if vessel.deadline_hour is not None and start_hour > vessel.deadline_hour + 1e-9:
                    continue
                start_minute = _minute(start_hour)
                end_minute = start_minute + duration_minutes
                for berth in berths:
                    if not berth_is_compatible(vessel, berth):
                        continue
                    if berth_has_outage(berth.code, start_hour, end_minute / 60, outages):
                        continue
                    selected = model.new_bool_var(
                        f"x_{vessel.ship_id}_{berth.code}_{window.window_id}_{slot_index}"
                    )
                    interval = model.new_optional_interval_var(
                        start_minute,
                        duration_minutes,
                        end_minute,
                        selected,
                        f"i_{vessel.ship_id}_{berth.code}_{window.window_id}_{slot_index}",
                    )
                    planned = vessel.planned_start_hour
                    if planned is None:
                        planned = vessel.deadline_hour if vessel.identity == "military" else start_hour
                    candidate = _Candidate(
                        vessel=vessel,
                        berth=berth,
                        window=window,
                        slot_index=slot_index,
                        start_minute=start_minute,
                        end_minute=end_minute,
                        wait_minutes=max(0, start_minute - _minute(vessel.eta_hour)),
                        military_deviation_minutes=(
                            abs(start_minute - _minute(planned))
                            if vessel.identity == "military" else 0
                        ),
                        changed_berth=(
                            vessel.original_berth is not None
                            and berth.code != vessel.original_berth
                        ),
                        selected=selected,
                    )
                    by_vessel[vessel.ship_id].append(candidate)
                    by_berth[berth.code].append(interval)
                    by_slot.setdefault((window.window_id, slot_index), []).append(selected)

    unscheduled_commercial: list[cp_model.IntVar] = []
    for vessel in vessels:
        selections = [candidate.selected for candidate in by_vessel[vessel.ship_id]]
        if vessel.identity == "military":
            if not selections:
                return _empty_report(vessels, "INFEASIBLE")
            model.add(sum(selections) == 1)
        else:
            missed = model.new_bool_var(f"unscheduled_{vessel.ship_id}")
            model.add(sum(selections) + missed == 1)
            unscheduled_commercial.append(missed)

    for selections in by_slot.values():
        model.add(sum(selections) <= 1)
    for intervals in by_berth.values():
        model.add_no_overlap(intervals)

    candidates = [candidate for values in by_vessel.values() for candidate in values]
    max_end = max((candidate.end_minute for candidate in candidates), default=0)
    makespan = model.new_int_var(0, max_end, "makespan")
    for candidate in candidates:
        model.add(makespan >= candidate.end_minute * candidate.selected)

    changed_bound = len(vessels)
    makespan_weight = changed_bound + 1
    lower_bound = makespan_weight * max_end + changed_bound
    wait_weight = lower_bound + 1
    commercial_wait_bound = len(vessels) * max_end
    lower_bound += wait_weight * commercial_wait_bound
    military_deviation_weight = lower_bound + 1
    military_deviation_bound = len(vessels) * max_end
    lower_bound += military_deviation_weight * military_deviation_bound
    unscheduled_weight = lower_bound + 1

    model.minimize(
        unscheduled_weight * sum(unscheduled_commercial)
        + military_deviation_weight
        * sum(c.military_deviation_minutes * c.selected for c in candidates)
        + wait_weight
        * sum(
            c.wait_minutes * c.selected
            for c in candidates
            if c.vessel.identity == "commercial"
        )
        + makespan_weight * makespan
        + sum(int(c.changed_berth) * c.selected for c in candidates)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = random_seed
    status_code = solver.solve(model)
    status = solver.status_name(status_code)
    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _empty_report(vessels, status, solver.wall_time)

    chosen = [candidate for candidate in candidates if solver.value(candidate.selected)]
    chosen.sort(key=lambda c: (c.start_minute, c.window.window_id, c.vessel.ship_id))
    window_counts: dict[str, int] = {}
    assignments = []
    for candidate in chosen:
        window_id = candidate.window.window_id
        window_counts[window_id] = window_counts.get(window_id, 0) + 1
        explanation = [
            "CP_SAT_EXACT_OR_BOUNDED",
            "MILITARY_DEADLINE_HARD" if candidate.vessel.identity == "military"
            else "COMMERCIAL_WAIT_OPTIMIZED",
        ]
        if candidate.changed_berth:
            explanation.extend(("ORIGINAL_BERTH_UNAVAILABLE_OR_SUBOPTIMAL", "ALTERNATIVE_BERTH_COMPATIBLE"))
        assignments.append(
            Assignment(
                ship_id=candidate.vessel.ship_id,
                identity=candidate.vessel.identity,
                window_id=window_id,
                release_order=window_counts[window_id],
                channel_entry_hour=candidate.start_minute / 60,
                berth_code=candidate.berth.code,
                berth_start_hour=candidate.start_minute / 60,
                berth_end_hour=candidate.end_minute / 60,
                wait_hours=candidate.wait_minutes / 60,
                changed_berth=candidate.changed_berth,
                explanation_codes=tuple(explanation),
            )
        )

    scheduled_ids = {assignment.ship_id for assignment in assignments}
    result = ScheduleResult(
        assignments=tuple(assignments),
        unscheduled_ship_ids=tuple(sorted(v.ship_id for v in vessels if v.ship_id not in scheduled_ids)),
    )
    metrics: dict[str, float | int] = {
        "scheduled_vessels": len(assignments),
        "unscheduled_commercial": sum(
            v.identity == "commercial" and v.ship_id not in scheduled_ids for v in vessels
        ),
        "military_schedule_deviation_minutes": sum(
            c.military_deviation_minutes for c in chosen if c.vessel.identity == "military"
        ),
        "commercial_wait_minutes": sum(
            c.wait_minutes for c in chosen if c.vessel.identity == "commercial"
        ),
        "makespan_minutes": max((c.end_minute for c in chosen), default=0),
        "changed_berths": sum(c.changed_berth for c in chosen),
    }
    return ExactSolveReport(
        result=result,
        status=status,
        objective_value=solver.objective_value,
        best_objective_bound=solver.best_objective_bound,
        wall_time_seconds=solver.wall_time,
        metrics=metrics,
    )
