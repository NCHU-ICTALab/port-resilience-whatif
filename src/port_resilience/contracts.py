"""Small dependency-free validators for the first convoy/batch scenario contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class VesselState(StrEnum):
    APPROACHING = "approaching"
    HOLDING_OFFSHORE = "holding_offshore"
    ANCHORED = "anchored"
    CONVOY_READY = "convoy_ready"
    RELEASED = "released"
    IN_CHANNEL = "in_channel"
    BERTHED = "berthed"
    DIVERTED = "diverted"
    COMPLETED = "completed"


class BerthState(StrEnum):
    NORMAL = "normal"
    COMMERCIAL_OCCUPIED = "commercial_occupied"
    MILITARY_OCCUPIED = "military_occupied"
    MILITARY_RESERVED = "military_reserved"
    FULLY_DAMAGED = "fully_damaged"
    PARTIALLY_DAMAGED = "partially_damaged"
    UNDER_REPAIR = "under_repair"


class Provenance(StrEnum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    SCENARIO_INPUT = "scenario_input"


def validate_scenario(payload: dict[str, Any]) -> None:
    """Reject structurally unsafe convoy scenarios before a solver sees them."""
    if payload.get("schema_version") != "resilience.scenario.v1":
        raise ValueError("unsupported schema_version")
    horizon = payload.get("horizon_hours")
    if not isinstance(horizon, (int, float)) or horizon <= 0:
        raise ValueError("horizon_hours must be positive")

    windows = payload.get("safety_windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("at least one safety window is required")
    previous_start = -1.0
    for index, window in enumerate(windows):
        start = window.get("start_hour")
        end = window.get("end_hour")
        maximum = window.get("max_releases")
        headway = window.get("channel_headway_minutes")
        if not all(isinstance(value, (int, float)) for value in (start, end, maximum, headway)):
            raise ValueError(f"safety_windows[{index}] has non-numeric limits")
        if start < 0 or end <= start or end > horizon:
            raise ValueError(f"safety_windows[{index}] is outside the horizon")
        if start < previous_start:
            raise ValueError("safety_windows must be sorted by start_hour")
        if maximum < 1 or int(maximum) != maximum:
            raise ValueError(f"safety_windows[{index}].max_releases must be a positive integer")
        if headway <= 0:
            raise ValueError(f"safety_windows[{index}].channel_headway_minutes must be positive")
        release_span_minutes = (end - start) * 60
        if (maximum - 1) * headway > release_span_minutes:
            raise ValueError(f"safety_windows[{index}] cannot fit its releases and headway")
        previous_start = float(start)

    anchorage = payload.get("resources", {}).get("anchorage_capacity")
    if not isinstance(anchorage, int) or anchorage < 0:
        raise ValueError("resources.anchorage_capacity must be a non-negative integer")

    for index, vessel in enumerate(payload.get("vessels", [])):
        try:
            VesselState(vessel["state"])
        except (KeyError, ValueError) as error:
            raise ValueError(f"vessels[{index}] has an invalid state") from error
        identity = vessel.get("identity")
        if identity not in {"military", "commercial"}:
            raise ValueError(f"vessels[{index}] has an invalid identity")
        if identity == "military" and not vessel.get("deadline"):
            raise ValueError(f"vessels[{index}] military task requires a deadline")
