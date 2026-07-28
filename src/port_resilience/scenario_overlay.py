"""Apply explicit human-supplied scenario inputs to an immutable historical case."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .data_adapter import CaseVessel, EvaluationTruth, HistoricalCase
from .model import Vessel, berth_is_compatible


def apply_military_input(
    case: HistoricalCase,
    payload: dict[str, Any],
) -> HistoricalCase:
    """Add mandatory military missions; never infer, relax, or reprioritize them."""
    if payload.get("schema_version") != "resilience.military-input.v1":
        raise ValueError("unsupported military input schema_version")
    missions = payload.get("missions")
    if not isinstance(missions, list):
        raise ValueError("missions must be a list")
    existing_ids = {item.vessel.ship_id for item in case.vessels}
    additions = []
    for index, mission in enumerate(missions):
        if not isinstance(mission, dict):
            raise ValueError(f"missions[{index}] must be an object")
        required = (
            "ship_id", "eta_hour", "ready_hour", "service_hours", "loa_m",
            "draft_m", "ship_type", "original_berth", "deadline_hour",
            "planned_start_hour", "allowed_terminals",
        )
        missing = [field for field in required if field not in mission]
        if missing:
            raise ValueError(f"missions[{index}] missing fields: {', '.join(missing)}")
        ship_id = mission["ship_id"]
        if not isinstance(ship_id, str) or not ship_id.startswith("M"):
            raise ValueError(f"missions[{index}].ship_id must start with M")
        if ship_id in existing_ids:
            raise ValueError(f"duplicate ship_id: {ship_id}")
        numeric_fields = (
            "eta_hour", "ready_hour", "service_hours", "loa_m", "draft_m",
            "deadline_hour", "planned_start_hour",
        )
        if not all(isinstance(mission[field], (int, float)) for field in numeric_fields):
            raise ValueError(f"missions[{index}] has non-numeric scheduling fields")
        if any(float(mission[field]) < 0 for field in numeric_fields):
            raise ValueError(f"missions[{index}] scheduling fields must be non-negative")
        if mission["service_hours"] <= 0 or mission["loa_m"] <= 0 or mission["draft_m"] <= 0:
            raise ValueError(f"missions[{index}] dimensions and service_hours must be positive")
        terminals = mission["allowed_terminals"]
        if not isinstance(terminals, list) or not terminals or not all(
            isinstance(value, str) for value in terminals
        ):
            raise ValueError(f"missions[{index}].allowed_terminals must be a non-empty string list")
        vessel = Vessel(
            ship_id=ship_id,
            identity="military",
            eta_hour=float(mission["eta_hour"]),
            ready_hour=float(mission["ready_hour"]),
            service_hours=float(mission["service_hours"]),
            loa_m=float(mission["loa_m"]),
            draft_m=float(mission["draft_m"]),
            ship_type=str(mission["ship_type"]),
            original_berth=str(mission["original_berth"]),
            deadline_hour=float(mission["deadline_hour"]),
            allowed_terminals=frozenset(terminals),
            planned_start_hour=float(mission["planned_start_hour"]),
        )
        if not any(berth_is_compatible(vessel, berth) for berth in case.berths):
            raise ValueError(f"missions[{index}] has no compatible berth in this case")
        provenance = {
            field: "scenario_input"
            for field in required
            if field != "ship_id"
        }
        additions.append(
            CaseVessel(
                vessel=vessel,
                provenance=provenance,
                truth=EvaluationTruth(None, None, None),
                service_calibration_count=0,
            )
        )
        existing_ids.add(ship_id)
    metadata = dict(case.metadata)
    metadata["military_overlay"] = {
        "schema_version": payload["schema_version"],
        "missions": len(additions),
        "authority": "human_scenario_input",
    }
    return replace(case, vessels=case.vessels + tuple(additions), metadata=metadata)


def load_military_input(case: HistoricalCase, path: Path) -> HistoricalCase:
    return apply_military_input(case, json.loads(path.read_text(encoding="utf-8")))
