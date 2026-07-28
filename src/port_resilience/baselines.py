"""Deterministic FCFS/public-priority baseline for convoy safety windows."""

from __future__ import annotations

from math import inf

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


def _priority(vessel: Vessel) -> tuple[int | float | str, ...]:
    if vessel.identity == "military":
        return (0, vessel.deadline_hour if vessel.deadline_hour is not None else inf, vessel.eta_hour, vessel.ship_id)
    return (1, vessel.eta_hour, vessel.ready_hour, vessel.ship_id)


def _candidate_berths(vessel: Vessel, berths: tuple[Berth, ...]) -> tuple[Berth, ...]:
    compatible = [berth for berth in berths if berth_is_compatible(vessel, berth)]
    compatible.sort(key=lambda berth: (berth.code != vessel.original_berth, berth.code))
    return tuple(compatible)


def schedule_public_priority(
    vessels: tuple[Vessel, ...],
    berths: tuple[Berth, ...],
    windows: tuple[SafetyWindow, ...],
    outages: tuple[BerthOutage, ...] = (),
) -> ScheduleResult:
    """Schedule military deadlines first, then commercial FCFS, without look-ahead data."""
    remaining = {vessel.ship_id: vessel for vessel in vessels}
    berth_available = {berth.code: 0.0 for berth in berths}
    assignments: list[Assignment] = []

    for window in sorted(windows, key=lambda item: item.start_hour):
        released_in_window = 0
        for channel_hour in window.release_slots():
            ready = sorted(
                (
                    vessel
                    for vessel in remaining.values()
                    if max(vessel.eta_hour, vessel.ready_hour) <= channel_hour
                ),
                key=_priority,
            )
            selected: tuple[Vessel, Berth] | None = None
            for vessel in ready:
                for berth in _candidate_berths(vessel, berths):
                    berth_start = channel_hour
                    berth_end = berth_start + vessel.service_hours
                    if berth_available[berth.code] > berth_start:
                        continue
                    if berth_has_outage(berth.code, berth_start, berth_end, outages):
                        continue
                    if vessel.deadline_hour is not None and berth_start > vessel.deadline_hour:
                        continue
                    selected = vessel, berth
                    break
                if selected:
                    break
            if selected is None:
                continue

            vessel, berth = selected
            released_in_window += 1
            berth_start = channel_hour
            berth_end = berth_start + vessel.service_hours
            changed = vessel.original_berth is not None and berth.code != vessel.original_berth
            explanation = ["MILITARY_DEADLINE_PRIORITY" if vessel.identity == "military" else "COMMERCIAL_FCFS"]
            if changed:
                explanation.extend(("ORIGINAL_BERTH_UNAVAILABLE", "ALTERNATIVE_BERTH_COMPATIBLE"))
            assignments.append(
                Assignment(
                    ship_id=vessel.ship_id,
                    identity=vessel.identity,
                    window_id=window.window_id,
                    release_order=released_in_window,
                    channel_entry_hour=channel_hour,
                    berth_code=berth.code,
                    berth_start_hour=berth_start,
                    berth_end_hour=berth_end,
                    wait_hours=max(0.0, berth_start - vessel.eta_hour),
                    changed_berth=changed,
                    explanation_codes=tuple(explanation),
                )
            )
            berth_available[berth.code] = berth_end
            del remaining[vessel.ship_id]

    return ScheduleResult(
        assignments=tuple(assignments),
        unscheduled_ship_ids=tuple(sorted(remaining)),
    )
