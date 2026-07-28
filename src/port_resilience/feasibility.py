"""Independent hard-constraint checks shared by solvers and review exports."""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    Berth,
    BerthOutage,
    SafetyWindow,
    ScheduleResult,
    Vessel,
    berth_has_outage,
    berth_is_compatible,
    intervals_overlap,
)


TOLERANCE = 1e-6


@dataclass(frozen=True)
class FeasibilityReport:
    feasible: bool
    violation_codes: tuple[str, ...]

    @property
    def violation_count(self) -> int:
        return len(self.violation_codes)


def validate_schedule(
    result: ScheduleResult,
    vessels: tuple[Vessel, ...],
    berths: tuple[Berth, ...],
    windows: tuple[SafetyWindow, ...],
    outages: tuple[BerthOutage, ...] = (),
) -> FeasibilityReport:
    """Recompute modeled hard constraints without trusting solver metadata."""
    vessel_by_id = {vessel.ship_id: vessel for vessel in vessels}
    berth_by_code = {berth.code: berth for berth in berths}
    window_by_id = {window.window_id: window for window in windows}
    violations: list[str] = []
    seen_ships: set[str] = set()
    used_slots: set[tuple[str, int]] = set()

    for assignment in result.assignments:
        vessel = vessel_by_id.get(assignment.ship_id)
        berth = berth_by_code.get(assignment.berth_code)
        window = window_by_id.get(assignment.window_id)
        if assignment.ship_id in seen_ships:
            violations.append(f"DUPLICATE_ASSIGNMENT:{assignment.ship_id}")
        seen_ships.add(assignment.ship_id)
        if vessel is None:
            violations.append(f"UNKNOWN_VESSEL:{assignment.ship_id}")
            continue
        if berth is None:
            violations.append(f"UNKNOWN_BERTH:{assignment.ship_id}")
            continue
        if window is None:
            violations.append(f"UNKNOWN_WINDOW:{assignment.ship_id}")
            continue
        if assignment.identity != vessel.identity:
            violations.append(f"IDENTITY_MISMATCH:{assignment.ship_id}")
        if not berth_is_compatible(vessel, berth):
            violations.append(f"BERTH_INCOMPATIBLE:{assignment.ship_id}:{berth.code}")
        if assignment.berth_start_hour + TOLERANCE < max(vessel.eta_hour, vessel.ready_hour):
            violations.append(f"VESSEL_NOT_READY:{assignment.ship_id}")
        expected_end = assignment.berth_start_hour + vessel.service_hours
        if abs(expected_end - assignment.berth_end_hour) > 1 / 60 + TOLERANCE:
            violations.append(f"SERVICE_DURATION_MISMATCH:{assignment.ship_id}")
        if berth_has_outage(
            berth.code,
            assignment.berth_start_hour,
            assignment.berth_end_hour,
            outages,
        ):
            violations.append(f"BERTH_OUTAGE:{assignment.ship_id}:{berth.code}")
        if (
            vessel.deadline_hour is not None
            and assignment.berth_start_hour > vessel.deadline_hour + TOLERANCE
        ):
            violations.append(f"MILITARY_DEADLINE:{assignment.ship_id}")

        slots = window.release_slots()
        matching = [index for index, hour in enumerate(slots) if abs(hour - assignment.channel_entry_hour) <= TOLERANCE]
        if not matching:
            violations.append(f"INVALID_RELEASE_SLOT:{assignment.ship_id}:{window.window_id}")
        else:
            slot = (window.window_id, matching[0])
            if slot in used_slots:
                violations.append(f"CHANNEL_SLOT_COLLISION:{window.window_id}:{matching[0]}")
            used_slots.add(slot)
        if abs(assignment.channel_entry_hour - assignment.berth_start_hour) > TOLERANCE:
            violations.append(f"CHANNEL_BERTH_START_MISMATCH:{assignment.ship_id}")

    by_berth: dict[str, list] = {}
    for assignment in result.assignments:
        by_berth.setdefault(assignment.berth_code, []).append(assignment)
    for berth_code, assignments in by_berth.items():
        ordered = sorted(assignments, key=lambda item: item.berth_start_hour)
        for first, second in zip(ordered, ordered[1:]):
            if intervals_overlap(
                first.berth_start_hour,
                first.berth_end_hour,
                second.berth_start_hour,
                second.berth_end_hour,
            ):
                violations.append(
                    f"BERTH_OVERLAP:{berth_code}:{first.ship_id}:{second.ship_id}"
                )

    unscheduled = set(result.unscheduled_ship_ids)
    expected_unscheduled = set(vessel_by_id) - seen_ships
    if unscheduled != expected_unscheduled:
        violations.append("UNSCHEDULED_SET_MISMATCH")
    for vessel in vessels:
        if vessel.identity == "military" and vessel.ship_id not in seen_ships:
            violations.append(f"MILITARY_TASK_UNSCHEDULED:{vessel.ship_id}")

    return FeasibilityReport(not violations, tuple(violations))
