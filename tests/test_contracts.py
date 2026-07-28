import json
import unittest
from pathlib import Path

from port_resilience.contracts import validate_scenario


ROOT = Path(__file__).resolve().parents[1]


class ScenarioContractTest(unittest.TestCase):
    def test_example_scenario_is_valid(self) -> None:
        payload = json.loads(
            (ROOT / "examples" / "scenario_request.json").read_text(encoding="utf-8")
        )
        validate_scenario(payload)

    def test_window_rejects_impossible_headway(self) -> None:
        payload = {
            "schema_version": "resilience.scenario.v1",
            "horizon_hours": 1,
            "safety_windows": [
                {
                    "start_hour": 0,
                    "end_hour": 0.5,
                    "max_releases": 5,
                    "channel_headway_minutes": 20,
                }
            ],
            "resources": {"anchorage_capacity": 1},
            "vessels": [],
        }
        with self.assertRaisesRegex(ValueError, "cannot fit"):
            validate_scenario(payload)

    def test_military_task_requires_deadline(self) -> None:
        payload = {
            "schema_version": "resilience.scenario.v1",
            "horizon_hours": 2,
            "safety_windows": [
                {
                    "start_hour": 0,
                    "end_hour": 1,
                    "max_releases": 1,
                    "channel_headway_minutes": 15,
                }
            ],
            "resources": {"anchorage_capacity": 1},
            "vessels": [
                {
                    "ship_id": "M001",
                    "identity": "military",
                    "state": "convoy_ready",
                    "deadline": None,
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "requires a deadline"):
            validate_scenario(payload)


if __name__ == "__main__":
    unittest.main()
