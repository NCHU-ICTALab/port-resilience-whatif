"""Shared deterministic scheduling model used by every solver and baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Identity = Literal["military", "commercial"]


@dataclass(frozen=True)
class Berth:
    code: str
    length_m: float
    depth_m: float
    allowed_ship_types: frozenset[str] = frozenset()
    military_reserved: bool = False
    terminal: str | None = None


@dataclass(frozen=True)
class Vessel:
    ship_id: str
    identity: Identity
    eta_hour: float
    ready_hour: float
    service_hours: float
    loa_m: float
    draft_m: float
    ship_type: str
    original_berth: str | None = None
    deadline_hour: float | None = None
    allowed_terminals: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BerthOutage:
    berth_code: str
    start_hour: float
    end_hour: float


@dataclass(frozen=True)
class SafetyWindow:
    window_id: str
    start_hour: float
    end_hour: float
    max_releases: int
    channel_headway_minutes: float

    def release_slots(self) -> tuple[float, ...]:
        headway_hours = self.channel_headway_minutes / 60
        return tuple(
            self.start_hour + index * headway_hours
            for index in range(self.max_releases)
            if self.start_hour + index * headway_hours <= self.end_hour
        )


@dataclass(frozen=True)
class Assignment:
    ship_id: str
    identity: Identity
    window_id: str
    release_order: int
    channel_entry_hour: float
    berth_code: str
    berth_start_hour: float
    berth_end_hour: float
    wait_hours: float
    changed_berth: bool
    explanation_codes: tuple[str, ...]


@dataclass(frozen=True)
class ScheduleResult:
    assignments: tuple[Assignment, ...]
    unscheduled_ship_ids: tuple[str, ...]
    constraint_violations: int = 0


def intervals_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
    return start_a < end_b and start_b < end_a


def berth_is_compatible(vessel: Vessel, berth: Berth) -> bool:
    if vessel.loa_m > berth.length_m or vessel.draft_m > berth.depth_m:
        return False
    if berth.military_reserved and vessel.identity != "military":
        return False
    if vessel.allowed_terminals and berth.terminal not in vessel.allowed_terminals:
        return False
    return not berth.allowed_ship_types or vessel.ship_type in berth.allowed_ship_types


def berth_has_outage(
    berth_code: str,
    start_hour: float,
    end_hour: float,
    outages: tuple[BerthOutage, ...],
) -> bool:
    return any(
        outage.berth_code == berth_code
        and intervals_overlap(start_hour, end_hour, outage.start_hour, outage.end_hour)
        for outage in outages
    )
