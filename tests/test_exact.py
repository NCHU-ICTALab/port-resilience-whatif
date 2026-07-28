import importlib.util
import unittest

from port_resilience.baselines import schedule_public_priority
from port_resilience.model import Berth, BerthOutage, SafetyWindow, Vessel


@unittest.skipUnless(importlib.util.find_spec("ortools"), "optimizer extra is not installed")
class CpSatOracleTest(unittest.TestCase):
    def setUp(self) -> None:
        from port_resilience.exact import solve_cp_sat

        self.solve = solve_cp_sat
        self.window = (SafetyWindow("w1", 6, 7, 2, 15),)

    def test_lookahead_serves_vessel_greedy_misses(self) -> None:
        berths = (
            Berth("A", 300, 14, frozenset({"container"})),
            Berth("B", 200, 14, frozenset({"container"})),
        )
        vessels = (
            Vessel("V1", "commercial", 1, 1, 4, 150, 8, "container", "A"),
            Vessel("V2", "commercial", 1, 1, 4, 250, 8, "container", "A"),
        )
        greedy = schedule_public_priority(vessels, berths, self.window)
        exact = self.solve(vessels, berths, self.window)
        self.assertEqual(len(greedy.assignments), 1)
        self.assertEqual(exact.status, "OPTIMAL")
        self.assertEqual(len(exact.result.assignments), 2)
        assigned = {item.ship_id: item.berth_code for item in exact.result.assignments}
        self.assertEqual(assigned, {"V1": "B", "V2": "A"})

    def test_outage_and_deadline_are_hard(self) -> None:
        berths = (
            Berth("A", 300, 14, frozenset({"container"})),
            Berth("B", 300, 14, frozenset({"container"})),
        )
        military = Vessel(
            "M1", "military", 1, 1, 2, 180, 8, "container", "A", 6.25,
            planned_start_hour=6,
        )
        report = self.solve(
            (military,), berths, self.window, (BerthOutage("A", 0, 12),)
        )
        self.assertEqual(report.status, "OPTIMAL")
        self.assertEqual(report.result.assignments[0].berth_code, "B")
        self.assertLessEqual(report.result.assignments[0].berth_start_hour, 6.25)

    def test_impossible_military_task_is_infeasible(self) -> None:
        berth = (Berth("A", 100, 5, frozenset({"container"})),)
        military = Vessel("M1", "military", 1, 1, 2, 200, 8, "container", "A", 7)
        report = self.solve((military,), berth, self.window)
        self.assertEqual(report.status, "INFEASIBLE")
        self.assertEqual(report.result.unscheduled_ship_ids, ("M1",))


if __name__ == "__main__":
    unittest.main()
