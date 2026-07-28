import unittest

from port_resilience.baselines import schedule_public_priority
from port_resilience.feasibility import validate_schedule
from port_resilience.model import (
    Assignment,
    Berth,
    SafetyWindow,
    ScheduleResult,
    Vessel,
)


class FeasibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.berths = (Berth("A", 300, 14, frozenset({"container"})),)
        self.windows = (SafetyWindow("w1", 6, 7, 2, 15),)
        self.vessels = (
            Vessel("V1", "commercial", 1, 1, 2, 200, 10, "container", "A"),
        )

    def test_accepts_baseline_schedule(self) -> None:
        result = schedule_public_priority(self.vessels, self.berths, self.windows)
        report = validate_schedule(result, self.vessels, self.berths, self.windows)
        self.assertTrue(report.feasible)
        self.assertEqual(report.violation_codes, ())

    def test_detects_invalid_release_and_service_duration(self) -> None:
        assignment = Assignment(
            "V1", "commercial", "w1", 1, 6.1, "A", 6.1, 7, 5.1, False, ()
        )
        result = ScheduleResult((assignment,), ())
        report = validate_schedule(result, self.vessels, self.berths, self.windows)
        self.assertFalse(report.feasible)
        self.assertIn("INVALID_RELEASE_SLOT:V1:w1", report.violation_codes)
        self.assertIn("SERVICE_DURATION_MISMATCH:V1", report.violation_codes)

    def test_unscheduled_military_is_a_violation(self) -> None:
        military = (
            Vessel("M1", "military", 1, 1, 2, 200, 10, "container", "A", 7),
        )
        report = validate_schedule(
            ScheduleResult((), ("M1",)), military, self.berths, self.windows
        )
        self.assertIn("MILITARY_TASK_UNSCHEDULED:M1", report.violation_codes)


if __name__ == "__main__":
    unittest.main()
