import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from port_resilience.data_adapter import build_historical_case


class HistoricalCaseAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "movements.sqlite"
        self.specs = root / "berths.json"
        self.specs.write_text(
            json.dumps(
                {
                    "1068": {"length_m": 300, "depth_m": 14},
                    "1069": {"length_m": 320, "depth_m": 14.5},
                }
            ),
            encoding="utf-8",
        )
        connection = sqlite3.connect(self.db)
        connection.execute(
            """
            CREATE TABLE movements (
                direction TEXT, pilot_apply_time TEXT, pass_port_time TEXT,
                berth_time TEXT, depart_time TEXT, berth_code TEXT,
                gross_tonnage INTEGER, visa_no TEXT
            )
            """
        )
        rows = [
            ("進港", "2026-06-30T00:00:00", "2026-06-30T01:00:00", "2026-06-30T02:00:00", "2026-06-30T10:00:00", "1068", 20000, "OLD1"),
            ("進港", "2026-06-30T10:00:00", "2026-06-30T11:00:00", "2026-06-30T12:00:00", "2026-06-30T20:00:00", "1068", 22000, "OLD2"),
            ("進港", "2026-07-01T00:00:00", "2026-07-01T01:00:00", "2026-07-01T02:00:00", "2026-07-01T10:00:00", "1068", 24000, "OLD3"),
            ("進港", "2026-07-05T04:00:00", "2026-07-05T05:00:00", "2026-07-05T06:00:00", "2026-07-06T02:00:00", "1068", 30000, "SECRET"),
        ]
        connection.executemany("INSERT INTO movements VALUES (?,?,?,?,?,?,?,?)", rows)
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_service_estimate_uses_only_pre_cutoff_history(self) -> None:
        case = build_historical_case(
            self.db,
            self.specs,
            datetime.fromisoformat("2026-07-05T00:00:00"),
            limit=10,
            outage_berth=None,
        )
        self.assertEqual(len(case.vessels), 1)
        item = case.vessels[0]
        self.assertEqual(item.vessel.service_hours, 8)
        self.assertEqual(item.truth.actual_service_hours, 20)
        self.assertEqual(item.service_calibration_count, 3)
        self.assertLess(
            case.metadata["service_calibration_latest_departure"],
            case.metadata["service_calibration_cutoff"],
        )

    def test_identifiers_are_pseudonymized(self) -> None:
        case = build_historical_case(
            self.db,
            self.specs,
            datetime.fromisoformat("2026-07-05T00:00:00"),
            outage_berth=None,
        )
        self.assertEqual(case.vessels[0].vessel.ship_id, "V001")
        self.assertNotIn("SECRET", repr(case))


if __name__ == "__main__":
    unittest.main()
