"""Apply explicit human-supplied scenario inputs to an immutable historical case."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .data_adapter import CaseVessel, EvaluationTruth, HistoricalCase
from .model import BerthOutage, Vessel, berth_is_compatible


SUPPORTED_SCHEMAS = {
    "resilience.military-input.v1",
    "resilience.military-input.v2",
}
AUTHORITY_STATUSES = {
    "draft_preview",
    "human_approved_scenario",
    "exercise_input",
}
CONTROL_MODES = {"military_priority", "military_exclusive", "closed"}


def apply_military_input(
    case: HistoricalCase,
    payload: dict[str, Any],
) -> HistoricalCase:
    """Add mandatory military missions; never infer, relax, or reprioritize them."""
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMAS:
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
    authority: dict[str, Any] = {
        "status": "human_approved_scenario",
        "reference": None,
    }
    controls: list[dict[str, Any]] = []
    added_outages: list[BerthOutage] = []
    if schema_version == "resilience.military-input.v2":
        supplied_authority = payload.get("authority")
        if not isinstance(supplied_authority, dict):
            raise ValueError("v2 authority must be an object")
        status = supplied_authority.get("status")
        if status not in AUTHORITY_STATUSES:
            raise ValueError("v2 authority.status is invalid")
        reference = supplied_authority.get("reference")
        if reference is not None and not isinstance(reference, str):
            raise ValueError("v2 authority.reference must be a string or null")
        authority = {"status": status, "reference": reference}
        raw_controls = payload.get("port_controls")
        if not isinstance(raw_controls, list):
            raise ValueError("v2 port_controls must be a list")
        known_berths = {berth.code for berth in case.berths}
        seen_controls: set[str] = set()
        for index, control in enumerate(raw_controls):
            if not isinstance(control, dict):
                raise ValueError(f"port_controls[{index}] must be an object")
            required_control = (
                "control_id", "mode", "berth_codes", "start_hour", "end_hour",
                "allow_current_vessel_to_finish", "clear_before_start",
            )
            missing = [field for field in required_control if field not in control]
            if missing:
                raise ValueError(
                    f"port_controls[{index}] missing fields: {', '.join(missing)}"
                )
            control_id = control["control_id"]
            if not isinstance(control_id, str) or not control_id:
                raise ValueError(f"port_controls[{index}].control_id must be a string")
            if control_id in seen_controls:
                raise ValueError(f"duplicate control_id: {control_id}")
            seen_controls.add(control_id)
            mode = control["mode"]
            if mode not in CONTROL_MODES:
                raise ValueError(f"port_controls[{index}].mode is unsupported")
            berth_codes = control["berth_codes"]
            if not isinstance(berth_codes, list) or not berth_codes or not all(
                isinstance(code, str) for code in berth_codes
            ):
                raise ValueError(
                    f"port_controls[{index}].berth_codes must be a non-empty string list"
                )
            unknown = sorted(set(berth_codes) - known_berths)
            if unknown:
                raise ValueError(
                    f"port_controls[{index}] references unknown berths: {', '.join(unknown)}"
                )
            start = control["start_hour"]
            end = control["end_hour"]
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                raise ValueError(f"port_controls[{index}] times must be numeric")
            if start < 0 or end <= start or end > case.horizon_hours:
                raise ValueError(f"port_controls[{index}] is outside the case horizon")
            allow_finish = control["allow_current_vessel_to_finish"]
            clear_before = control["clear_before_start"]
            if not isinstance(allow_finish, bool) or not isinstance(clear_before, bool):
                raise ValueError(f"port_controls[{index}] clearing flags must be boolean")
            if allow_finish and clear_before:
                raise ValueError(
                    f"port_controls[{index}] cannot both allow completion and require clearing"
                )
            blocked = ()
            if mode == "military_exclusive":
                blocked = ("commercial",)
            elif mode == "closed":
                blocked = ("military", "commercial")
            for berth_code in berth_codes:
                if blocked:
                    added_outages.append(
                        BerthOutage(
                            berth_code=berth_code,
                            start_hour=float(start),
                            end_hour=float(end),
                            blocked_identities=blocked,
                            reason=mode,
                            control_id=control_id,
                        )
                    )
            controls.append(
                {
                    "control_id": control_id,
                    "mode": mode,
                    "berth_codes": berth_codes,
                    "start_hour": float(start),
                    "end_hour": float(end),
                    "allow_current_vessel_to_finish": allow_finish,
                    "clear_before_start": clear_before,
                }
            )

    metadata = dict(case.metadata)
    metadata["military_overlay"] = {
        "schema_version": schema_version,
        "missions": len(additions),
        "authority": authority,
        "port_controls": controls,
        "model_scope": "berth-level priority, military-exclusive, and closed controls",
    }
    return replace(
        case,
        vessels=case.vessels + tuple(additions),
        outages=case.outages + tuple(added_outages),
        metadata=metadata,
    )


def load_military_input(case: HistoricalCase, path: Path) -> HistoricalCase:
    return apply_military_input(case, json.loads(path.read_text(encoding="utf-8")))
