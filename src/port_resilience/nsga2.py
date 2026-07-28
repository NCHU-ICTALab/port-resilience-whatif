"""NSGA-II Pareto search for convoy order, safety window, and berth choices."""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import ElementwiseProblem
from pymoo.optimize import minimize

from .baselines import schedule_public_priority
from .feasibility import validate_schedule
from .model import (
    Assignment,
    Berth,
    BerthOutage,
    SafetyWindow,
    ScheduleResult,
    Vessel,
    berth_has_outage,
    berth_is_compatible,
    intervals_overlap,
)


PROFILE_WEIGHTS = {
    "military_priority": (0.70, 0.20, 0.10),
    "port_resilience": (0.30, 0.50, 0.20),
    "ship_friendly": (0.30, 0.20, 0.50),
    "balanced": (0.34, 0.33, 0.33),
}


@dataclass(frozen=True)
class ParetoCandidate:
    candidate_id: str
    source: str
    result: ScheduleResult
    objectives: dict[str, float]
    kpis: dict[str, Any]
    profile_scores: dict[str, float]
    constraint_violations: tuple[str, ...]


@dataclass(frozen=True)
class Nsga2Report:
    candidates: tuple[ParetoCandidate, ...]
    profile_recommendations: dict[str, str]
    population_size: int
    generations: int
    evaluations: int
    seed: int
    wall_time_seconds: float
    baseline_scheduled_vessels: int


def _rotated(items: list[Any], gene: float) -> list[Any]:
    if not items:
        return []
    start = min(len(items) - 1, int(float(gene) * len(items)))
    return items[start:] + items[:start]


def decode_genome(
    genome: np.ndarray,
    vessels: tuple[Vessel, ...],
    berths: tuple[Berth, ...],
    windows: tuple[SafetyWindow, ...],
    outages: tuple[BerthOutage, ...] = (),
) -> ScheduleResult:
    """Decode three random keys per vessel into an always-repaired physical schedule."""
    count = len(vessels)
    if len(genome) != count * 3:
        raise ValueError("genome must contain order, window, and berth genes per vessel")
    if not windows:
        return ScheduleResult((), tuple(sorted(v.ship_id for v in vessels)))

    order_genes = genome[:count]
    window_genes = genome[count : count * 2]
    berth_genes = genome[count * 2 :]
    vessel_index = {vessel.ship_id: index for index, vessel in enumerate(vessels)}
    ordered = sorted(
        vessels,
        key=lambda vessel: (
            vessel.identity != "military",
            order_genes[vessel_index[vessel.ship_id]],
            vessel.ship_id,
        ),
    )
    sorted_windows = sorted(windows, key=lambda item: item.start_hour)
    occupied: dict[str, list[tuple[float, float]]] = {berth.code: [] for berth in berths}
    used_slots: set[tuple[str, int]] = set()
    selected: list[tuple[Vessel, Berth, SafetyWindow, int, float]] = []

    for vessel in ordered:
        index = vessel_index[vessel.ship_id]
        compatible = sorted(
            (berth for berth in berths if berth_is_compatible(vessel, berth)),
            key=lambda berth: (berth.code != vessel.original_berth, berth.code),
        )
        berth_order = _rotated(compatible, berth_genes[index])
        window_order = _rotated(sorted_windows, window_genes[index])
        choice = None
        for window in window_order:
            for slot_index, start_hour in enumerate(window.release_slots()):
                if (window.window_id, slot_index) in used_slots:
                    continue
                if start_hour + 1e-9 < max(vessel.eta_hour, vessel.ready_hour):
                    continue
                if vessel.deadline_hour is not None and start_hour > vessel.deadline_hour + 1e-9:
                    continue
                end_hour = start_hour + vessel.service_hours
                for berth in berth_order:
                    if berth_has_outage(berth.code, start_hour, end_hour, outages):
                        continue
                    if any(
                        intervals_overlap(start_hour, end_hour, occupied_start, occupied_end)
                        for occupied_start, occupied_end in occupied[berth.code]
                    ):
                        continue
                    choice = berth, window, slot_index, start_hour
                    break
                if choice is not None:
                    break
            if choice is not None:
                break
        if choice is None:
            continue
        berth, window, slot_index, start_hour = choice
        occupied[berth.code].append((start_hour, start_hour + vessel.service_hours))
        used_slots.add((window.window_id, slot_index))
        selected.append((vessel, berth, window, slot_index, start_hour))

    selected.sort(key=lambda item: (item[4], item[2].window_id, item[0].ship_id))
    window_counts: dict[str, int] = {}
    assignments = []
    for vessel, berth, window, _slot_index, start_hour in selected:
        window_counts[window.window_id] = window_counts.get(window.window_id, 0) + 1
        changed = vessel.original_berth is not None and berth.code != vessel.original_berth
        explanation = [
            "NSGA2_PARETO_CANDIDATE",
            "MILITARY_HARD_PRIORITY" if vessel.identity == "military" else "COMMERCIAL_MULTI_OBJECTIVE",
        ]
        if changed:
            explanation.extend(("ORIGINAL_BERTH_UNAVAILABLE_OR_SUBOPTIMAL", "ALTERNATIVE_BERTH_COMPATIBLE"))
        assignments.append(
            Assignment(
                ship_id=vessel.ship_id,
                identity=vessel.identity,
                window_id=window.window_id,
                release_order=window_counts[window.window_id],
                channel_entry_hour=start_hour,
                berth_code=berth.code,
                berth_start_hour=start_hour,
                berth_end_hour=start_hour + vessel.service_hours,
                wait_hours=max(0.0, start_hour - vessel.eta_hour),
                changed_berth=changed,
                explanation_codes=tuple(explanation),
            )
        )
    scheduled = {assignment.ship_id for assignment in assignments}
    return ScheduleResult(
        assignments=tuple(assignments),
        unscheduled_ship_ids=tuple(sorted(v.ship_id for v in vessels if v.ship_id not in scheduled)),
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def schedule_kpis(result: ScheduleResult, vessels: tuple[Vessel, ...]) -> dict[str, Any]:
    vessel_by_id = {vessel.ship_id: vessel for vessel in vessels}
    commercial_waits = [
        assignment.wait_hours
        for assignment in result.assignments
        if assignment.identity == "commercial"
    ]
    military = [vessel for vessel in vessels if vessel.identity == "military"]
    assignment_by_ship = {item.ship_id: item for item in result.assignments}
    on_time = sum(
        vessel.ship_id in assignment_by_ship
        and (
            vessel.deadline_hour is None
            or assignment_by_ship[vessel.ship_id].berth_start_hour <= vessel.deadline_hour + 1e-9
        )
        for vessel in military
    )
    release_times = sorted(
        {max(vessel.eta_hour, vessel.ready_hour) for vessel in vessels}
        | {assignment.channel_entry_hour for assignment in result.assignments}
    )
    max_waiting = 0
    for hour in release_times:
        waiting = sum(
            max(vessel.eta_hour, vessel.ready_hour) <= hour
            and (
                vessel.ship_id not in assignment_by_ship
                or assignment_by_ship[vessel.ship_id].channel_entry_hour > hour
            )
            for vessel in vessels
        )
        max_waiting = max(max_waiting, waiting)
    per_window: dict[str, int] = {}
    for assignment in result.assignments:
        per_window[assignment.window_id] = per_window.get(assignment.window_id, 0) + 1
    return {
        "scheduled_vessels": len(result.assignments),
        "unscheduled_vessels": len(result.unscheduled_ship_ids),
        "military_on_time_rate": round(on_time / len(military), 4) if military else None,
        "commercial_total_wait_hours": round(sum(commercial_waits), 3),
        "commercial_mean_wait_hours": round(statistics.mean(commercial_waits), 3)
        if commercial_waits else None,
        "commercial_p90_wait_hours": round(_percentile(commercial_waits, 0.9), 3)
        if commercial_waits else None,
        "schedule_completion_hour": round(
            max((item.berth_end_hour for item in result.assignments), default=0), 3
        ),
        "changed_berths": sum(item.changed_berth for item in result.assignments),
        "modeled_max_waiting_queue": max_waiting,
        "releases_per_window": per_window,
        "scheduled_ship_ids": sorted(assignment_by_ship),
        "unscheduled_ship_ids": list(result.unscheduled_ship_ids),
        "unknown_vessel_references": sorted(
            set(assignment_by_ship) - set(vessel_by_id)
        ),
    }


def _objectives(result: ScheduleResult, vessels: tuple[Vessel, ...]) -> tuple[float, float, float]:
    vessel_by_id = {vessel.ship_id: vessel for vessel in vessels}
    military_deviation = 0.0
    commercial_wait = 0.0
    for assignment in result.assignments:
        vessel = vessel_by_id[assignment.ship_id]
        if vessel.identity == "military":
            planned = vessel.planned_start_hour
            if planned is None:
                planned = vessel.deadline_hour if vessel.deadline_hour is not None else assignment.berth_start_hour
            military_deviation += abs(assignment.berth_start_hour - planned)
        else:
            commercial_wait += assignment.wait_hours
    makespan = max((item.berth_end_hour for item in result.assignments), default=0.0)
    return military_deviation, commercial_wait, makespan


class _SchedulingProblem(ElementwiseProblem):
    def __init__(
        self,
        vessels: tuple[Vessel, ...],
        berths: tuple[Berth, ...],
        windows: tuple[SafetyWindow, ...],
        outages: tuple[BerthOutage, ...],
        minimum_throughput: int,
    ) -> None:
        super().__init__(n_var=len(vessels) * 3, n_obj=3, n_ieq_constr=1, xl=0.0, xu=1.0)
        self.vessels = vessels
        self.berths = berths
        self.windows = windows
        self.outages = outages
        self.minimum_throughput = minimum_throughput

    def _evaluate(self, genome: np.ndarray, out: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        result = decode_genome(genome, self.vessels, self.berths, self.windows, self.outages)
        feasibility = validate_schedule(
            result, self.vessels, self.berths, self.windows, self.outages
        )
        throughput_shortfall = max(0, self.minimum_throughput - len(result.assignments))
        out["F"] = np.asarray(_objectives(result, self.vessels))
        out["G"] = np.asarray([feasibility.violation_count + throughput_shortfall])


def _baseline_genome(
    result: ScheduleResult,
    vessels: tuple[Vessel, ...],
    berths: tuple[Berth, ...],
    windows: tuple[SafetyWindow, ...],
) -> np.ndarray:
    count = len(vessels)
    genome = np.full(count * 3, 0.001, dtype=float)
    assignment_by_ship = {item.ship_id: item for item in result.assignments}
    ordered_assignments = sorted(result.assignments, key=lambda item: item.channel_entry_hour)
    order_rank = {item.ship_id: rank for rank, item in enumerate(ordered_assignments)}
    sorted_windows = sorted(windows, key=lambda item: item.start_hour)
    window_index = {window.window_id: index for index, window in enumerate(sorted_windows)}
    for index, vessel in enumerate(vessels):
        assignment = assignment_by_ship.get(vessel.ship_id)
        genome[index] = (order_rank.get(vessel.ship_id, count) + 0.01) / (count + 1)
        if assignment is None:
            continue
        genome[count + index] = (window_index[assignment.window_id] + 0.01) / len(sorted_windows)
        compatible = sorted(
            (berth for berth in berths if berth_is_compatible(vessel, berth)),
            key=lambda berth: (berth.code != vessel.original_berth, berth.code),
        )
        selected_index = next(
            i for i, berth in enumerate(compatible) if berth.code == assignment.berth_code
        )
        genome[count * 2 + index] = (selected_index + 0.01) / len(compatible)
    return genome


def _is_dominated(target: tuple[float, ...], others: list[tuple[float, ...]]) -> bool:
    return any(
        all(other[i] <= target[i] + 1e-9 for i in range(len(target)))
        and any(other[i] < target[i] - 1e-9 for i in range(len(target)))
        for other in others
    )


def solve_nsga2(
    vessels: tuple[Vessel, ...],
    berths: tuple[Berth, ...],
    windows: tuple[SafetyWindow, ...],
    outages: tuple[BerthOutage, ...] = (),
    *,
    population_size: int = 80,
    generations: int = 80,
    seed: int = 42,
    max_candidates: int = 12,
) -> Nsga2Report:
    """Return independently verified, non-dominated schedules for human review."""
    if population_size < 4 or generations < 1 or max_candidates < 1:
        raise ValueError("population_size>=4, generations>=1, and max_candidates>=1 required")
    baseline = schedule_public_priority(vessels, berths, windows, outages)
    baseline_feasibility = validate_schedule(baseline, vessels, berths, windows, outages)
    if not baseline_feasibility.feasible:
        raise ValueError(
            "public-priority seed is infeasible: " + ", ".join(baseline_feasibility.violation_codes)
        )
    rng = np.random.default_rng(seed)
    sampling = rng.random((population_size, len(vessels) * 3))
    if vessels:
        sampling[0] = _baseline_genome(baseline, vessels, berths, windows)
    problem = _SchedulingProblem(
        vessels, berths, windows, outages, minimum_throughput=len(baseline.assignments)
    )
    algorithm = NSGA2(pop_size=population_size, sampling=sampling, eliminate_duplicates=True)
    started = time.perf_counter()
    optimization = minimize(
        problem,
        algorithm,
        termination=("n_gen", generations),
        seed=seed,
        verbose=False,
    )
    elapsed = time.perf_counter() - started

    work: list[tuple[str, ScheduleResult, tuple[float, float, float]]] = [
        ("public_priority_seed", baseline, _objectives(baseline, vessels))
    ]
    if optimization.X is not None:
        genomes = np.atleast_2d(optimization.X)
        for genome in genomes:
            result = decode_genome(genome, vessels, berths, windows, outages)
            feasibility = validate_schedule(result, vessels, berths, windows, outages)
            if feasibility.feasible and len(result.assignments) >= len(baseline.assignments):
                work.append(("nsga2", result, _objectives(result, vessels)))

    unique: dict[tuple, tuple[str, ScheduleResult, tuple[float, float, float]]] = {}
    for source, result, objectives in work:
        signature = tuple(
            (item.ship_id, item.window_id, item.berth_code, item.channel_entry_hour)
            for item in result.assignments
        )
        previous = unique.get(signature)
        if previous is None or source == "public_priority_seed":
            unique[signature] = (source, result, objectives)
    objective_representatives: dict[
        tuple[float, float, float],
        tuple[str, ScheduleResult, tuple[float, float, float]],
    ] = {}
    for item in unique.values():
        objective_key = tuple(round(value, 9) for value in item[2])
        current = objective_representatives.get(objective_key)
        if current is None:
            objective_representatives[objective_key] = item
            continue
        item_kpis = schedule_kpis(item[1], vessels)
        current_kpis = schedule_kpis(current[1], vessels)
        item_secondary = (
            item[0] != "public_priority_seed",
            item_kpis["changed_berths"],
            item_kpis["commercial_p90_wait_hours"] or 0,
        )
        current_secondary = (
            current[0] != "public_priority_seed",
            current_kpis["changed_berths"],
            current_kpis["commercial_p90_wait_hours"] or 0,
        )
        if item_secondary < current_secondary:
            objective_representatives[objective_key] = item
    values = list(objective_representatives.values())
    nondominated = [
        item for item in values
        if not _is_dominated(item[2], [other[2] for other in values if other is not item])
    ]
    nondominated.sort(key=lambda item: (item[2], item[0] != "public_priority_seed"))
    nondominated = nondominated[:max_candidates]

    objective_matrix = np.asarray([item[2] for item in nondominated], dtype=float)
    minimum = objective_matrix.min(axis=0)
    span = objective_matrix.max(axis=0) - minimum
    span[span == 0] = 1.0
    normalized = (objective_matrix - minimum) / span
    candidates = []
    for index, ((source, result, objectives), normalized_row) in enumerate(
        zip(nondominated, normalized), start=1
    ):
        feasibility = validate_schedule(result, vessels, berths, windows, outages)
        scores = {
            profile: round(float(np.dot(normalized_row, weights)), 6)
            for profile, weights in PROFILE_WEIGHTS.items()
        }
        candidates.append(
            ParetoCandidate(
                candidate_id=f"P{index:03d}",
                source=source,
                result=result,
                objectives={
                    "military_schedule_deviation_hours": round(objectives[0], 3),
                    "commercial_total_wait_hours": round(objectives[1], 3),
                    "schedule_completion_hour": round(objectives[2], 3),
                },
                kpis=schedule_kpis(result, vessels),
                profile_scores=scores,
                constraint_violations=feasibility.violation_codes,
            )
        )
    recommendations = {
        profile: min(candidates, key=lambda candidate: candidate.profile_scores[profile]).candidate_id
        for profile in PROFILE_WEIGHTS
    } if candidates else {}
    evaluations = int(getattr(optimization.algorithm.evaluator, "n_eval", 0))
    return Nsga2Report(
        candidates=tuple(candidates),
        profile_recommendations=recommendations,
        population_size=population_size,
        generations=generations,
        evaluations=evaluations,
        seed=seed,
        wall_time_seconds=elapsed,
        baseline_scheduled_vessels=len(baseline.assignments),
    )
