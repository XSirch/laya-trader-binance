import copy
from dataclasses import replace
import unittest

from jev_trader.basis_features import build_states
from jev_trader.binance_data import Bar, HOUR_MS
from jev_trader.derivatives_data import Funding


def fixture(hours=760):
    rows = {}
    for i in range(hours):
        p = 100+i*.01
        rows[i*HOUR_MS] = Bar(i*HOUR_MS, p, p+1, p-1, p+.1, 100_000, 10_000_000, 100, 50_000)
    return {"spot": {"X": rows},
            "futures": {"X": {t: replace(b, close=b.close*1.002) for t, b in rows.items()}},
            "mark": {"X": dict(rows)},
            "funding": {"X": [Funding(i*HOUR_MS+1, 8, .0001) for i in range(0, hours, 8)]}}


class BasisFeaturesTests(unittest.TestCase):
    def test_delay_schema_and_funding_publication_lag(self):
        states, audit = build_states(fixture())
        row = states["X"][722*HOUR_MS]
        self.assertEqual(row["latest_observed_close_ms"], 721*HOUR_MS)
        self.assertEqual(row["funding_available_through_ms"], 720*HOUR_MS)
        self.assertEqual(row["funding_latest_ms"], 712*HOUR_MS+1)
        self.assertAlmostEqual(row["basis_previous720_median"], .002)
        self.assertEqual(row["quote_volume24"]["spot"], 240_000_000)
        for leg in ("spot", "futures"):
            self.assertEqual(set(row[leg+"_hourly"]), {"trend", "momentum", "volatility", "participation", "structure"})
            self.assertIn("180", row[leg+"_hourly"]["structure"]["fibonacci"])
        self.assertFalse(row["historical_point_in_time_verified"])
        self.assertEqual(audit["symbols"]["X"]["first_execution_ms"], 722*HOUR_MS)

    def test_future_and_unpublished_events_do_not_change_past(self):
        market = fixture()
        original, _ = build_states(market)
        changed = copy.deepcopy(market)
        for kind in ("spot", "futures", "mark"):
            for t in list(changed[kind]["X"]):
                if t > 730*HOUR_MS:
                    b = changed[kind]["X"][t]
                    changed[kind]["X"][t] = replace(b, open=b.open*2, high=b.high*2, low=b.low*2, close=b.close*2)
        changed["funding"]["X"] = [replace(e, rate=.3) if e.timestamp_ms > 730*HOUR_MS else e
                                    for e in changed["funding"]["X"]]
        new, _ = build_states(changed)
        self.assertEqual({t: r for t, r in original["X"].items() if t <= 732*HOUR_MS},
                         {t: r for t, r in new["X"].items() if t <= 732*HOUR_MS})

    def test_reference_excludes_current_basis(self):
        market = fixture()
        market["futures"]["X"][720*HOUR_MS] = replace(market["futures"]["X"][720*HOUR_MS], close=150)
        states, _ = build_states(market)
        row = states["X"][722*HOUR_MS]
        self.assertGreater(row["basis_fraction"], .3)
        self.assertAlmostEqual(row["basis_previous720_median"], .002)

    def test_gap_resets_technical_and_reference_history(self):
        market = fixture(1500)
        del market["spot"]["X"][740*HOUR_MS]
        states, _ = build_states(market)
        self.assertNotIn(1462*HOUR_MS, states["X"])
        self.assertIn(1463*HOUR_MS, states["X"])

    def test_missing_volume_is_not_zero_or_imputed(self):
        market = fixture()
        market["spot"]["X"][720*HOUR_MS] = replace(market["spot"]["X"][720*HOUR_MS], quote_volume=None)
        states, _ = build_states(market)
        self.assertIsNone(states["X"][722*HOUR_MS]["quote_volume24"]["spot"])


if __name__ == "__main__":
    unittest.main()
