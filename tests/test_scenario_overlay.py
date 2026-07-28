import unittest

from port_resilience.data_adapter import HistoricalCase
from port_resilience.model import Berth, SafetyWindow, berth_has_outage
from port_resilience.scenario_overlay import apply_military_input


class MilitaryOverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.case = HistoricalCase(
            "case", "2026-01-01T00:00:00", 24, (),
            (Berth("A", 300, 14, frozenset({"container"}), terminal="CT"),),
            (SafetyWindow("w1", 6, 7, 2, 15),), (), {},
        )
        self.mission = {
            "ship_id": "M001", "eta_hour": 5, "ready_hour": 5,
            "service_hours": 2, "loa_m": 180, "draft_m": 8,
            "ship_type": "container", "original_berth": "A",
            "deadline_hour": 7, "planned_start_hour": 6,
            "allowed_terminals": ["CT"],
        }

    def test_adds_mandatory_scenario_input(self) -> None:
        updated = apply_military_input(self.case, {
            "schema_version": "resilience.military-input.v1",
            "missions": [self.mission],
        })
        item = updated.vessels[0]
        self.assertEqual(item.vessel.identity, "military")
        self.assertEqual(item.vessel.deadline_hour, 7)
        self.assertTrue(all(source == "scenario_input" for source in item.provenance.values()))
        self.assertEqual(updated.metadata["military_overlay"]["missions"], 1)

    def test_rejects_mission_without_compatible_berth(self) -> None:
        mission = {**self.mission, "draft_m": 20}
        with self.assertRaisesRegex(ValueError, "no compatible berth"):
            apply_military_input(self.case, {
                "schema_version": "resilience.military-input.v1",
                "missions": [mission],
            })

    def test_v2_military_exclusive_control_blocks_only_commercial(self) -> None:
        updated = apply_military_input(self.case, {
            "schema_version": "resilience.military-input.v2",
            "authority": {"status": "draft_preview", "reference": None},
            "missions": [self.mission],
            "port_controls": [{
                "control_id": "R001",
                "mode": "military_exclusive",
                "berth_codes": ["A"],
                "start_hour": 6,
                "end_hour": 12,
                "allow_current_vessel_to_finish": True,
                "clear_before_start": False,
            }],
        })
        self.assertTrue(berth_has_outage("A", 7, 8, updated.outages, "commercial"))
        self.assertFalse(berth_has_outage("A", 7, 8, updated.outages, "military"))
        overlay = updated.metadata["military_overlay"]
        self.assertEqual(overlay["authority"]["status"], "draft_preview")
        self.assertEqual(overlay["port_controls"][0]["mode"], "military_exclusive")

    def test_v2_rejects_conflicting_clearing_policy(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot both"):
            apply_military_input(self.case, {
                "schema_version": "resilience.military-input.v2",
                "authority": {"status": "exercise_input", "reference": "EX-1"},
                "missions": [],
                "port_controls": [{
                    "control_id": "R001",
                    "mode": "closed",
                    "berth_codes": ["A"],
                    "start_hour": 6,
                    "end_hour": 12,
                    "allow_current_vessel_to_finish": True,
                    "clear_before_start": True,
                }],
            })


if __name__ == "__main__":
    unittest.main()
