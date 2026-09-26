import copy
import unittest

from jev_trader.binance_data import HOUR_MS
from jev_trader.broad_research import DAY_MS
from jev_trader.derivatives_data import Funding
from jev_trader.funding_event_execution import evaluate
from jev_trader.scheduled_execution import evaluate as preserved
from jev_trader.trailing_stop import TrailingStop
from test_scheduled_execution import fixture


class FundingEventExecutionTests(unittest.TestCase):
    def test_execution_and_accounting_equal_preserved_engine(self):
        start, hourly = fixture(days=3)
        states = {"BTCUSDT": {start+d*DAY_MS: {
            "latest_observed_close_ms": start+d*DAY_MS+HOUR_MS,
            "event_timestamp_ms": start+d*DAY_MS+47} for d in range(3)}}
        funding = {"BTCUSDT": [Funding(start+8*HOUR_MS, 8, .001)]}
        policy = lambda state, rule: {"BTCUSDT": .5} if state else {}
        for distance in (None, .04):
            kwargs = dict(target_policy=policy,
                          trailing=TrailingStop("portfolio_pct", distance) if distance else None)
            result = evaluate(hourly, funding, states, "event", "2024-01-02", "2024-01-05",
                              .0015, **kwargs)
            reference = preserved(hourly, funding, states, "event", "2024-01-02", "2024-01-05",
                                  .0015, target_policy=policy, cadence="daily", delay_hours=2,
                                  trailing=TrailingStop("portfolio_pct", distance) if distance else None)
            for record in result["execution_audit"]:
                self.assertEqual(record["execution_ms"]-record["latest_input_close_ms"], HOUR_MS)
                self.assertEqual(record["execution_ms"]-record["signal_day_ms"], 2*HOUR_MS)
            result.pop("execution_audit")
            reference.pop("execution_audit")
            self.assertEqual(result, reference)
            self.assertLess(result["funding_pct_initial"], 0)
            self.assertGreater(result["fees_pct_initial"], 0)

    def test_causal_metadata_validation_precedes_replay(self):
        start, hourly = fixture(days=1)
        state = {"latest_observed_close_ms": start+HOUR_MS, "event_timestamp_ms": start+47}
        for field, value in (("latest_observed_close_ms", start+2*HOUR_MS),
                             ("event_timestamp_ms", start+60_000),
                             ("event_timestamp_ms", start-1),
                             ("decision_ms", start), ("execution_ms", start+HOUR_MS)):
            bad = copy.deepcopy(state)
            bad[field] = value
            with self.assertRaises(ValueError):
                evaluate(hourly, {}, {"BTCUSDT": {start: bad}}, "event", "2024-01-02",
                         "2024-01-03", 0)


if __name__ == "__main__":
    unittest.main()
