from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "research" / "scripts"))

import cycle02_multiframe_research as engine  # noqa: E402
from binance_multistrategy.simulation import MarketArrays  # noqa: E402


class Cycle02ExitModeTests(unittest.TestCase):
    def setUp(self) -> None:
        times = pd.date_range("2026-01-01T00:00:00Z", periods=4, freq="min")
        bars = pd.DataFrame({
            "open_time": times,
            "open": [100.0, 100.0, 105.0, 100.0],
            "high": [100.0, 110.0, 116.0, 101.0],
            "low": [100.0, 98.0, 99.0, 99.0],
            "close": [100.0, 108.0, 100.0, 100.0],
            "mark_open": [100.0, 100.0, 105.0, 100.0],
            "mark_high": [100.0, 110.0, 116.0, 101.0],
            "mark_low": [100.0, 98.0, 99.0, 99.0],
            "mark_close": [100.0, 108.0, 100.0, 100.0],
            "funding_rate": [0.0, 0.0, 0.0, 0.0],
        })
        self.arrays = MarketArrays(bars)
        close_time = pd.Timestamp(times[2]) + pd.Timedelta(minutes=1)
        self.ema_by_symbol = {"BTCUSDT": {close_time: 105.0}}
        self.config = {"market": "spot", "fee_bps": 0.0, "slippage_bps": 0.0}
        self.candidates = pd.DataFrame([{
            "candidate_id": "test-candidate",
            "symbol": "BTCUSDT",
            "market": "spot",
            "family": "trend_resumption",
            "signal_index": 0,
            "side": 1,
            "atr": 10.0,
            "stop_atr": 1.0,
        }])

    def test_smoke_routes_all_registered_exit_modes(self) -> None:
        expected_reasons = {
            "fixed": "target",
            "trailing": "stop",
            "trend_loss": "trend_ema21_loss",
        }
        descriptions = dict(engine.EXITS)
        for mode, expected_reason in expected_reasons.items():
            with self.subTest(exit_mode=mode):
                result, _ = engine.run_variant(
                    market="spot",
                    family="trend_resumption",
                    horizon_name="6h",
                    max_hold=3,
                    exit_name=mode,
                    exit_plan=descriptions[mode],
                    candidates=self.candidates,
                    arrays={"BTCUSDT": self.arrays},
                    config=self.config,
                    ema_by_symbol=self.ema_by_symbol,
                    smoke=True,
                )
                self.assertEqual(result["smoke_labeled"], 1)
                self.assertEqual(result["stress_smoke_exit_reason"], expected_reason)

    def test_gate_uses_positive_stress_net_result_only(self) -> None:
        base = {"trades": 200, "active_weeks": 8, "mean_net_return": .013,
                "payoff_ratio": 1.0, "profit_factor": 1.25, "net_profit": 100.0}
        stress = {"trades": 20, "mean_net_return": -.01, "payoff_ratio": .5,
                  "profit_factor": .5, "net_profit": 1.0}

        passed, failures = engine.passes(base, stress)

        self.assertTrue(passed, failures)

    def test_simulator_rejects_descriptive_plan_instead_of_silently_falling_back(self) -> None:
        row = self.candidates.iloc[0].to_dict()
        with self.assertRaisesRegex(ValueError, "Unknown canonical exit mode"):
            engine.simulate(
                self.arrays,
                row,
                self.config,
                "fixed_1ATR_stop_1.5R_target",
                3,
                self.ema_by_symbol["BTCUSDT"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
