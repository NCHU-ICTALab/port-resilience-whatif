import importlib.util
import unittest

from port_resilience.data_adapter import CaseVessel, EvaluationTruth, HistoricalCase
from port_resilience.model import Berth, BerthOutage, SafetyWindow, Vessel
from port_resilience.scenario_overlay import apply_military_input


OPTIMIZER_AVAILABLE = all(
    importlib.util.find_spec(name) for name in ("numpy", "pymoo")
)


@unittest.skipUnless(OPTIMIZER_AVAILABLE, "optimizer extra is not installed")
class ReviewPacketTest(unittest.TestCase):
    def _case(self) -> HistoricalCase:
        vessel = Vessel(
            "V001", "commercial", 1, 1, 0.1, 150, 8, "container", "A",
            allowed_terminals=frozenset({"CT"}),
        )
        return HistoricalCase(
            case_id="test-case",
            observed_at="2026-01-01T00:00:00",
            horizon_hours=24,
            vessels=(CaseVessel(
                vessel,
                {"eta_hour": "observed_proxy", "loa_m": "estimated"},
                EvaluationTruth(None, None, None),
                3,
            ),),
            berths=(Berth("A", 300, 14, frozenset({"container"}), terminal="CT"),),
            windows=(SafetyWindow("w1", 6, 7, 2, 15),),
            outages=(),
            metadata={"identifiers": "pseudonymized"},
        )

    def test_packet_exposes_human_gates_and_verified_candidates(self) -> None:
        from port_resilience.review import build_review_packet

        packet = build_review_packet(
            self._case(), population_size=8, generations=3, seed=1, max_candidates=4
        )
        self.assertEqual(packet["review_status"], "awaiting_human_evaluation")
        self.assertEqual(packet["review_readiness"], "requires_scenario_owner_inputs")
        self.assertIn("inactive", packet["algorithm_run"]["objective_degeneracy"])
        self.assertTrue(packet["pareto_candidates"])
        self.assertTrue(all(
            candidate["feasibility"]["verified"]
            for candidate in packet["pareto_candidates"]
        ))
        required = {item["id"]: item for item in packet["required_human_inputs"]}
        self.assertEqual(required["military_missions"]["status"], "missing")
        self.assertEqual(required["port_requisition_controls"]["status"], "not_supplied")
        self.assertIsNone(packet["human_decision"]["selected_candidate_id"])

    def test_human_military_overlay_activates_military_objective(self) -> None:
        from port_resilience.review import build_review_packet

        case = apply_military_input(self._case(), {
            "schema_version": "resilience.military-input.v1",
            "missions": [{
                "ship_id": "M001", "eta_hour": 5, "ready_hour": 5,
                "service_hours": 0.1, "loa_m": 180, "draft_m": 8,
                "ship_type": "container", "original_berth": "A",
                "deadline_hour": 7, "planned_start_hour": 6,
                "allowed_terminals": ["CT"],
            }],
        })
        packet = build_review_packet(
            case, population_size=12, generations=5, seed=2, max_candidates=4
        )
        self.assertEqual(packet["review_readiness"], "candidate_selection_ready")
        self.assertIsNone(packet["algorithm_run"]["objective_degeneracy"])
        required = {item["id"]: item for item in packet["required_human_inputs"]}
        self.assertEqual(
            required["military_missions"]["status"], "provided_as_scenario_input"
        )
        self.assertEqual(
            required["port_requisition_controls"]["status"],
            "human_approved_scenario",
        )
        self.assertTrue(all(
            candidate["feasibility"]["verified"]
            for candidate in packet["pareto_candidates"]
        ))


if __name__ == "__main__":
    unittest.main()
