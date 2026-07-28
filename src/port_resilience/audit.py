"""Read-only audit of the local Kaohsiung port research datasets."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


CONTAINER_BERTHS = {
    40, 41, 42, 43,
    63, 64, 65, 66,
    68, 69, 70,
    *range(74, 82),
    *range(108, 112),
    *range(115, 123),
}


def _connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    return sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)


def _percent(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 2) if denominator else None


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * probability)
    return ordered[index]


def duration_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values]
    if not clean:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p90": None}
    return {
        "n": len(clean),
        "mean": round(statistics.mean(clean), 3),
        "median": round(statistics.median(clean), 3),
        "p10": round(_quantile(clean, 0.10) or 0, 3),
        "p90": round(_quantile(clean, 0.90) or 0, 3),
    }


def _present_count(connection: sqlite3.Connection, table: str, column: str) -> int:
    query = (
        f'SELECT COUNT(*) FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL AND TRIM(CAST("{column}" AS TEXT)) <> \'\''
    )
    return int(connection.execute(query).fetchone()[0])


def audit_movements(path: Path) -> dict[str, Any]:
    connection = _connect_read_only(path)
    try:
        total = int(connection.execute("SELECT COUNT(*) FROM movements").fetchone()[0])
        date_min, date_max, date_count = connection.execute(
            "SELECT MIN(query_date), MAX(query_date), COUNT(DISTINCT query_date) FROM movements"
        ).fetchone()
        fields = {}
        for column in (
            "gross_tonnage", "berth_code", "pilot_apply_time", "pass_port_time",
            "berth_time", "depart_time", "visa_no", "prev_port", "next_port",
        ):
            present = _present_count(connection, "movements", column)
            fields[column] = {"present": present, "percent": _percent(present, total)}

        directions = {
            str(direction): int(count)
            for direction, count in connection.execute(
                "SELECT direction, COUNT(*) FROM movements GROUP BY direction"
            )
        }
        inbound = directions.get("進港", 0)
        complete_rows = list(
            connection.execute(
                """
                SELECT pass_port_time, berth_time, depart_time, berth_code
                FROM movements
                WHERE direction = '進港'
                  AND pass_port_time IS NOT NULL
                  AND berth_time IS NOT NULL
                  AND depart_time IS NOT NULL
                """
            )
        )
        waits: list[float] = []
        dwell: list[float] = []
        container_waits: list[float] = []
        container_dwell: list[float] = []
        for signal, berth, depart, berth_code in complete_rows:
            signal_at = datetime.fromisoformat(signal)
            berth_at = datetime.fromisoformat(berth)
            depart_at = datetime.fromisoformat(depart)
            wait_h = (berth_at - signal_at).total_seconds() / 3600
            dwell_h = (depart_at - berth_at).total_seconds() / 3600
            if 0 <= wait_h <= 24 * 30:
                waits.append(wait_h)
            if 0 < dwell_h <= 24 * 30:
                dwell.append(dwell_h)
            try:
                berth_number = int(str(berth_code)[1:])
            except (TypeError, ValueError):
                berth_number = -1
            if berth_number in CONTAINER_BERTHS:
                container_waits.append(wait_h)
                container_dwell.append(dwell_h)

        parse_errors = int(
            connection.execute(
                "SELECT COUNT(*) FROM movements "
                "WHERE parse_error IS NOT NULL AND TRIM(parse_error) <> ''"
            ).fetchone()[0]
        )
        return {
            "path": str(path),
            "rows": total,
            "query_date": {"min": date_min, "max": date_max, "distinct_days": date_count},
            "directions": directions,
            "field_completeness": fields,
            "inbound_complete_timestamps": {
                "rows": len(complete_rows),
                "inbound_rows": inbound,
                "percent": _percent(len(complete_rows), inbound),
            },
            "inbound_wait_hours": duration_summary(waits),
            "inbound_dwell_hours": duration_summary(dwell),
            "container_inbound_complete_rows": len(container_waits),
            "container_wait_hours": duration_summary(container_waits),
            "container_dwell_hours": duration_summary(container_dwell),
            "parse_errors": parse_errors,
        }
    finally:
        connection.close()


def audit_snapshots(path: Path) -> dict[str, Any]:
    connection = _connect_read_only(path)
    try:
        total = int(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        timestamp_min, timestamp_max, timestamp_count = connection.execute(
            "SELECT MIN(snapshot_ts), MAX(snapshot_ts), COUNT(DISTINCT snapshot_ts) FROM snapshots"
        ).fetchone()
        fields = {}
        for column in (
            "gross_tonnage", "berth", "pilot_apply_time", "scheduled_arrival",
            "captain_eta", "actual_arrival", "anchor_time", "imo", "visa_no",
        ):
            present = _present_count(connection, "snapshots", column)
            fields[column] = {"present": present, "percent": _percent(present, total)}
        menus = {
            str(menu): int(count)
            for menu, count in connection.execute(
                "SELECT menu_name, COUNT(*) FROM snapshots GROUP BY menu_name"
            )
        }
        unique_visas = int(
            connection.execute(
                "SELECT COUNT(DISTINCT visa_no) FROM snapshots "
                "WHERE visa_no IS NOT NULL AND visa_no <> ''"
            ).fetchone()[0]
        )
        return {
            "path": str(path),
            "rows": total,
            "snapshot_time": {
                "min": timestamp_min,
                "max": timestamp_max,
                "distinct_polls": timestamp_count,
            },
            "menus": menus,
            "field_completeness": fields,
            "unique_visas": unique_visas,
        }
    finally:
        connection.close()


def _numeric_berth_codes(codes: Iterable[str]) -> set[int]:
    result = set()
    for code in codes:
        if len(code) == 4 and code.startswith("1") and code[1:].isdigit():
            result.add(int(code[1:]))
    return result


def audit_berths(specs_path: Path, markers_path: Path) -> dict[str, Any]:
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    marker_doc = json.loads(markers_path.read_text(encoding="utf-8"))
    markers = marker_doc.get("berths", marker_doc)
    spec_codes = _numeric_berth_codes(specs)
    marker_codes = _numeric_berth_codes(str(marker["code"]) for marker in markers)
    return {
        "spec_records": len(specs),
        "specs_with_length": sum(
            isinstance(value, dict) and value.get("length_m") is not None
            for value in specs.values()
        ),
        "specs_with_depth": sum(
            isinstance(value, dict) and value.get("depth_m") is not None
            for value in specs.values()
        ),
        "coordinate_markers": len(markers),
        "container_berths_expected": len(CONTAINER_BERTHS),
        "container_specs_covered": len(CONTAINER_BERTHS & spec_codes),
        "container_markers_covered": len(CONTAINER_BERTHS & marker_codes),
        "container_specs_missing": sorted(CONTAINER_BERTHS - spec_codes),
        "container_markers_missing": sorted(CONTAINER_BERTHS - marker_codes),
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {"audit_version": "0.1.0"}
    if args.movements_db:
        report["movements"] = audit_movements(args.movements_db)
    if args.snapshots_db:
        report["snapshots"] = audit_snapshots(args.snapshots_db)
    if args.berth_specs and args.berth_markers:
        report["berths"] = audit_berths(args.berth_specs, args.berth_markers)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movements-db", type=Path)
    parser.add_argument("--snapshots-db", type=Path)
    parser.add_argument("--berth-specs", type=Path)
    parser.add_argument("--berth-markers", type=Path)
    return parser.parse_args()


def main() -> None:
    print(json.dumps(build_report(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
