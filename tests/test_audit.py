import unittest

from port_resilience.audit import duration_summary


class DurationSummaryTest(unittest.TestCase):
    def test_duration_summary(self) -> None:
        summary = duration_summary([1, 2, 3, 4, 5])
        self.assertEqual(summary["n"], 5)
        self.assertEqual(summary["mean"], 3)
        self.assertEqual(summary["median"], 3)
        self.assertEqual(summary["p10"], 1)
        self.assertEqual(summary["p90"], 5)

    def test_empty_duration_summary(self) -> None:
        self.assertEqual(
            duration_summary([]),
            {
                "n": 0,
                "mean": None,
                "median": None,
                "p10": None,
                "p90": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
