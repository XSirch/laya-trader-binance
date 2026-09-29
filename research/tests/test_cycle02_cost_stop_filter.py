import unittest
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "scripts"))

from cycle02_cost_stop_filter_research import add_cost_to_stop_ratio


class CostToStopRatioTests(unittest.TestCase):
    def test_spot_round_trip_cost_at_quarter_stop_boundary_is_eligible(self):
        candidates = pd.DataFrame({"stop_fraction_signal": [0.012, 0.0119]})
        result = add_cost_to_stop_ratio(
            candidates, {"fee_bps": 10.0, "slippage_bps": 5.0}
        )
        self.assertAlmostEqual(result.loc[0, "round_trip_cost_rate_base"], 0.003)
        self.assertAlmostEqual(result.loc[0, "cost_to_stop_ratio"], 0.25)
        self.assertTrue(result.loc[0, "cost_filter_pass"])
        self.assertFalse(result.loc[1, "cost_filter_pass"])

    def test_usdm_uses_its_configured_base_round_trip_cost(self):
        candidates = pd.DataFrame({"stop_fraction_signal": [0.008]})
        result = add_cost_to_stop_ratio(
            candidates, {"fee_bps": 5.0, "slippage_bps": 5.0}
        )
        self.assertAlmostEqual(result.loc[0, "round_trip_cost_rate_base"], 0.002)
        self.assertAlmostEqual(result.loc[0, "cost_to_stop_ratio"], 0.25)
        self.assertTrue(result.loc[0, "cost_filter_pass"])

    def test_invalid_or_nonpositive_stop_fraction_is_rejected(self):
        for stop_fraction in (0.0, -0.01, float("nan")):
            with self.subTest(stop_fraction=stop_fraction):
                with self.assertRaises(ValueError):
                    add_cost_to_stop_ratio(
                        pd.DataFrame({"stop_fraction_signal": [stop_fraction]}),
                        {"fee_bps": 10.0, "slippage_bps": 5.0},
                    )


if __name__ == "__main__":
    unittest.main()
