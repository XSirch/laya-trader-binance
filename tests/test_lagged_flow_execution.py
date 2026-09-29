from types import SimpleNamespace

import pytest

from jev_trader import lagged_flow_execution as execution
from jev_trader.lagged_flow_prediction import SYMBOLS


H = 3_600_000
T0 = 1_704_067_200_000
DIGEST = "b" * 64


def bar(timestamp, price=100.0):
    return SimpleNamespace(open_ms=timestamp, open=price, high=price * 1.01,
        low=price * 0.99, close=price, volume=1000.0, quote_volume=100_000.0, trades=100)


def spot_through(end):
    return {symbol: {timestamp: bar(timestamp)
                     for timestamp in range(T0, end + H, H)} for symbol in SYMBOLS}


def strong_signals(times):
    return {(timestamp, symbol): {"prediction": .01,
             "latest_observed_close_ms": timestamp - H,
             "context_sha256": DIGEST}
            for timestamp in times for symbol in SYMBOLS}


def test_fixed_horizon_replay_closes_then_reenters_and_reconciles_fees():
    end = T0 + 16 * H
    times = (T0, T0 + 8 * H)
    event_symbols = {timestamp: set(SYMBOLS) for timestamp in times}
    result = execution.evaluate(spot_through(end), event_symbols, strong_signals(times),
        start_ms=T0, end_ms=end, side_cost=.0015, mode="own_hgb")
    assert result["entries"] == 8
    assert result["exits"] == 8
    assert result["asset_exposure_hours"] == 4 * 16
    assert result["asset_cash_hours"] == 0
    assert len(result["hourly_equity"]) == 17
    assert result["return_pct"] < 0
    assert result["fees_pct_initial"] > 0
    assert abs(result["reconciliation_error"]) < 1e-12
    assert result["adverse_intrahour_drawdown_bound_pct"] > 0


def test_cost_hurdle_keeps_subthreshold_forecasts_in_cash():
    end = T0 + 8 * H
    signals = strong_signals((T0,))
    for row in signals.values():
        row["prediction"] = .002
    result = execution.evaluate(spot_through(end), {T0: set(SYMBOLS)}, signals,
        start_ms=T0, end_ms=end, side_cost=.0015, mode="own_hgb")
    assert result["entries"] == 0
    assert result["terminal_equity"] == 1
    assert result["decision_reason_counts"]["forecast_below_round_trip_cost"] == 4


def test_buy_and_hold_does_not_close_at_each_eight_hour_signal_boundary():
    end = T0 + 16 * H
    result = execution.evaluate(spot_through(end), {}, {}, start_ms=T0,
        end_ms=end, side_cost=.0015, mode="buy_hold")
    assert result["entries"] == 4
    assert result["exits"] == 4
    assert result["asset_exposure_hours"] == 4 * 16
    assert result["return_pct"] < 0
    assert abs(result["reconciliation_error"]) < 1e-12


def test_invalid_held_hour_aborts_the_scenario():
    end = T0 + 8 * H
    spot = spot_through(end)
    del spot["BTCUSDT"][T0 + 3 * H]
    with pytest.raises(execution.ExecutionUnavailable, match="held BTCUSDT"):
        execution.evaluate(spot, {T0: set(SYMBOLS)}, strong_signals((T0,)),
            start_ms=T0, end_ms=end, side_cost=.0015, mode="own_hgb")


def test_signal_with_wrong_information_cutoff_is_rejected():
    end = T0 + 8 * H
    signals = strong_signals((T0,))
    signals[(T0, "BTCUSDT")]["latest_observed_close_ms"] = T0
    with pytest.raises(ValueError, match="cutoff"):
        execution.evaluate(spot_through(end), {T0: set(SYMBOLS)}, signals,
            start_ms=T0, end_ms=end, side_cost=.0015, mode="own_hgb")
