import unittest

from port_resilience.baselines import schedule_public_priority
from port_resilience.model import Berth, BerthOutage, SafetyWindow, Vessel


class PublicPriorityBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.berths = (
            Berth("1068", 300, 14, frozenset({"container"})),
            Berth("1069", 300, 14, frozenset({"container"})),
        )
        self.window = (SafetyWindow("w1", 6, 7, 3, 15),)

    def test_military_deadline_precedes_earlier_commercial_arrival(self) -> None:
        vessels = (
            Vessel("V1", "commercial", 1, 1, 2, 200, 10, "container", "1068"),
            Vessel("M1", "military", 5, 5, 2, 200, 10, "container", "1069", 7),
        )
        result = schedule_public_priority(vessels, self.berths, self.window)
        self.assertEqual(result.assignments[0].ship_id, "M1")
        self.assertEqual(result.assignments[0].channel_entry_hour, 6)

    def test_outage_forces_compatible_reassignment(self) -> None:
        vessel = Vessel("V1", "commercial", 1, 1, 2, 200, 10, "container", "1068")
        outage = (BerthOutage("1068", 0, 24),)
        result = schedule_public_priority((vessel,), self.berths, self.window, outage)
        assignment = result.assignments[0]
        self.assertEqual(assignment.berth_code, "1069")
        self.assertTrue(assignment.changed_berth)

    def test_headway_is_applied_inside_window(self) -> None:
        vessels = tuple(
            Vessel(f"V{i}", "commercial", 1, 1, 0.1, 100, 5, "container")
            for i in range(3)
        )
        result = schedule_public_priority(vessels, self.berths, self.window)
        entries = [assignment.channel_entry_hour for assignment in result.assignments]
        self.assertEqual(entries, [6, 6.25, 6.5])

    def test_cross_terminal_reassignment_is_not_implicit(self) -> None:
        berths = (
            Berth("1068", 300, 14, frozenset({"container"}), terminal="CT3"),
            Berth("1075", 320, 14, frozenset({"container"}), terminal="CT5"),
        )
        vessel = Vessel(
            "V1", "commercial", 1, 1, 2, 200, 10, "container", "1068",
            allowed_terminals=frozenset({"CT3"}),
        )
        outage = (BerthOutage("1068", 0, 24),)
        result = schedule_public_priority((vessel,), berths, self.window, outage)
        self.assertEqual(result.assignments, ())
        self.assertEqual(result.unscheduled_ship_ids, ("V1",))


if __name__ == "__main__":
    unittest.main()
