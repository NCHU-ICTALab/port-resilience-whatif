import importlib.util
import unittest

import numpy as np

from port_resilience.feasibility import validate_schedule
from port_resilience.model import Berth, BerthOutage, SafetyWindow, Vessel


OPTIMIZER_AVAILABLE = all(
    importlib.util.find_spec(name) for name in ("numpy", "pymoo")
)


@unittest.skipUnless(OPTIMIZER_AVAILABLE, "optimizer extra is not installed")
class Nsga2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.berths = (
            Berth("A", 300, 14, frozenset({"container"})),
            Berth("B", 220, 14, frozenset({"container"})),
        )
        self.windows = (
            SafetyWindow("w1", 6, 7, 3, 15),
            SafetyWindow("w2", 12, 13, 3, 15),
        )
        self.vessels = (
            Vessel("M1", "military", 1, 1, 2, 200, 9, "container", "A", 7, planned_start_hour=6),
            Vessel("V1", "commercial", 1, 1, 4, 200, 9, "container", "A"),
            Vessel("V2", "commercial", 1, 1, 3, 180, 8, "container", "B"),
        )

    def test_decoder_repairs_to_hard_constraints(self) -> None:
        from port_resilience.nsga2 import decode_genome

        genome = np.asarray([0.2, 0.1, 0.3, 0.0, 0.0, 0.0, 0.1, 0.2, 0.3])
        result = decode_genome(
            genome,
            self.vessels,
            self.berths,
            self.windows,
            (BerthOutage("B", 0, 8),),
        )
        report = validate_schedule(
            result,
            self.vessels,
            self.berths,
            self.windows,
            (BerthOutage("B", 0, 8),),
        )
        self.assertTrue(report.feasible, report.violation_codes)

    def test_search_returns_verified_candidates_and_profile_recommendations(self) -> None:
        from port_resilience.nsga2 import solve_nsga2

        report = solve_nsga2(
            self.vessels,
            self.berths,
            self.windows,
            population_size=20,
            generations=10,
            seed=7,
        )
        self.assertTrue(report.candidates)
        self.assertEqual(set(report.profile_recommendations), {
            "military_priority", "port_resilience", "ship_friendly", "balanced"
        })
        for candidate in report.candidates:
            self.assertEqual(candidate.constraint_violations, ())
            self.assertEqual(candidate.kpis["scheduled_vessels"], 3)
        objective_vectors = [tuple(candidate.objectives.values()) for candidate in report.candidates]
        self.assertEqual(len(objective_vectors), len(set(objective_vectors)))


if __name__ == "__main__":
    unittest.main()
