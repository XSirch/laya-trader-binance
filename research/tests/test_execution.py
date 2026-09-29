import numpy as np
import pandas as pd
import pytest
from binance_multistrategy.config import ResearchConfig
from binance_multistrategy.simulation import MarketArrays, simulate_trade, ratchet_stop, exit_trigger, promotion_gate, evaluate
from binance_multistrategy.paper import PaperBroker, PaperSignal


def array_bars(rows, funding=None):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["open_time"] = pd.date_range("2020-01-01", periods=len(df), freq="min", tz="UTC")
    for col in ["open", "high", "low", "close"]:
        df[f"mark_{col}"] = df[col]
    df["funding_rate"] = funding if funding is not None else 0
    return MarketArrays(df)


def candidate(**kw):
    return {"signal_index": 0, "side": 1, "atr": 1., "stop_atr": 1., "target_r": 2.,
            "trail_activation_r": 1., "trail_distance_r": 1., "max_hold_minutes": 3, **kw}


def free_config(**kw):
    return ResearchConfig(fee_bps=0, slippage_bps=0, **kw)


def test_signal_fills_next_open_not_signal_close():
    data = array_bars([[80, 81, 79, 80], [100, 100.2, 99.8, 100], [100, 100.2, 99.8, 100], [100, 100.2, 99.8, 100]])
    trade = simulate_trade(data, candidate(), free_config())
    assert trade.entry_price == 100
    assert trade.net_return == 0


@pytest.mark.parametrize("side,high,low", [(1, 103, 98), (-1, 102, 97)])
def test_ambiguous_bar_stop_before_target(side, high, low):
    data = array_bars([[100, 100, 100, 100], [100, high, low, 100], [100, 100, 100, 100], [100, 100, 100, 100]])
    trade = simulate_trade(data, candidate(side=side), free_config(market="usd_m"))
    assert trade.net_r == -1
    assert trade.exit_reason == "stop"


def test_opening_gap_is_filled_adversely():
    data = array_bars([[100, 100, 100, 100], [100, 100.2, 99.8, 100], [95, 96, 94, 95], [95, 95, 95, 95]])
    trade = simulate_trade(data, candidate(), free_config())
    assert trade.exit_price == 95
    assert trade.net_r == -5
    assert trade.exit_reason == "stop_gap"


def test_target_gap_before_later_stop():
    assert exit_trigger(1, 105, 106, 98, 99, 102) == (102, "target_gap")


def test_trailing_not_applied_retroactively_same_bar():
    data = array_bars([[100, 100, 100, 100], [100, 102, 99.5, 101.5], [101.5, 101.6, 100.8, 101], [101, 101, 101, 101]])
    trade = simulate_trade(data, candidate(target_r=10), free_config())
    assert trade.exit_index == 2
    assert trade.exit_price == 101
    assert trade.net_r == 1


def test_trailing_never_loosens():
    assert ratchet_stop(1, 100, 102, 102, 1, 1, 1) == 102
    assert ratchet_stop(-1, 100, 98, 98, 1, 1, 1) == 98


def test_fees_and_slippage_both_sides():
    data = array_bars([[100, 100, 100, 100]] * 4)
    trade = simulate_trade(data, candidate(), ResearchConfig())
    entry, exit_price = 100.05, 99.95
    expected = (exit_price - entry - (entry + exit_price) * .001) / entry
    assert trade.net_return == pytest.approx(expected)
    assert trade.net_return < 0


def test_spot_short_rejected():
    data = array_bars([[100, 100, 100, 100]] * 4)
    with pytest.raises(ValueError, match="Spot"):
        simulate_trade(data, candidate(side=-1), free_config())


def test_censored_trade_not_labelled():
    data = array_bars([[100, 100, 100, 100]] * 3)
    assert simulate_trade(data, candidate(), free_config()) is None


def test_long_pays_observed_funding_short_receives():
    data = array_bars([[100, 100, 100, 100]] * 4, [0, 0, .001, 0])
    config = free_config(market="usd_m")
    assert simulate_trade(data, candidate(), config).net_return == pytest.approx(-.001)
    assert simulate_trade(data, candidate(side=-1), config).net_return == pytest.approx(.001)


def test_ambiguous_exit_funding_never_invents_credit():
    data = array_bars([[100, 100, 100, 100]] * 4, [0, 0, 0, .001])
    config = free_config(market="usd_m")
    assert simulate_trade(data, candidate(side=-1), config).net_return == 0
    assert simulate_trade(data, candidate(), config).net_return == pytest.approx(-.001)


def test_high_hit_rate_insufficient_sample_is_rejected():
    summary = {"trades": 10, "active_weeks": 1, "win_rate": .9, "weekly_bootstrap_lower_95": .8,
               "profit_factor": 2, "net_profit": 100, "mean_net_r": .2, "mean_net_return": .02,
               "payoff_ratio": 1.2, "max_drawdown": .55}
    passed, failures = promotion_gate(summary, summary, ResearchConfig())
    assert not passed
    assert "insufficient_executed_trades" in failures


def test_high_winrate_but_negative_expectancy_rejected():
    summary = {"trades": 1000, "active_weeks": 20, "win_rate": .8, "weekly_bootstrap_lower_95": .73,
               "profit_factor": .8, "net_profit": -100, "mean_net_r": -.2, "mean_net_return": -.003,
               "payoff_ratio": .8, "max_drawdown": .01}
    assert not promotion_gate(summary, summary, ResearchConfig())[0]


def test_soft_win_rate_and_unbounded_drawdown_use_current_user_objectives():
    summary = {"trades": 250, "active_weeks": 12, "win_rate": .65, "weekly_bootstrap_lower_95": .58,
               "profit_factor": 1.35, "net_profit": 300, "mean_net_r": .2, "mean_net_return": .015,
               "payoff_ratio": 1.2, "max_drawdown": .42}
    passed, failures = promotion_gate(summary, summary, ResearchConfig(
        max_drawdown=.05, confidence_lower_bound_required=True))
    assert passed
    assert not failures


def test_stress_uses_positive_net_result_without_extra_ev_or_payoff_gates():
    base = {"trades": 250, "active_weeks": 12, "win_rate": .65,
            "profit_factor": 1.35, "net_profit": 300, "mean_net_r": -.2,
            "mean_net_return": .015, "payoff_ratio": 1.2, "max_drawdown": .42}
    stress = {**base, "net_profit": 10, "mean_net_return": -.001,
              "payoff_ratio": .5, "max_drawdown": .8}

    passed, failures = promotion_gate(base, stress, ResearchConfig())

    assert passed
    assert not failures


def test_ev_and_payoff_are_hard_gates():
    summary = {"trades": 250, "active_weeks": 12, "win_rate": .69, "weekly_bootstrap_lower_95": .6,
               "profit_factor": 1.35, "net_profit": 300, "mean_net_r": .2, "mean_net_return": .012,
               "payoff_ratio": .99, "max_drawdown": .01}
    passed, failures = promotion_gate(summary, summary, ResearchConfig())
    assert not passed
    assert "net_ev_per_trade_below_target" in failures
    assert "payoff_ratio_below_target" in failures


def paper_signal(**kw):
    return PaperSignal(**{"signal_id": "test-1", "symbol": "SYNTHETIC", "side": 1,
                         "signal_time": "2020-01-01T00:01:00Z", "stop_distance": 1,
                         "target_r": 5, "trail_activation_r": 1, "trail_distance_r": 1,
                         "max_hold_minutes": 10, "strategy": "ema_pullback", **kw})


def test_paper_spot_exit_is_sell_and_idempotent(tmp_path):
    broker = PaperBroker(free_config())
    assert broker.submit(paper_signal())
    assert not broker.submit(paper_signal())
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:01Z")
    broker.on_price("SYNTHETIC", 98, "2020-01-01T00:01:02Z")
    assert broker.position is None
    assert broker.events[-1]["side"] == "SELL"
    assert broker.balance < 10000
    broker.save(tmp_path / "state.json")
    restored = PaperBroker.load(tmp_path / "state.json")
    assert not restored.submit(paper_signal())
    assert restored.balance == broker.balance


def test_paper_stop_reacts_before_next_minute():
    broker = PaperBroker(free_config())
    broker.submit(paper_signal())
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:01Z")
    broker.on_price("SYNTHETIC", 98, "2020-01-01T00:01:02Z")
    assert broker.position is None
    assert broker.events[-1]["reason"] == "stop"


def test_paper_trailing_only_ratchets_on_closed_minute():
    broker = PaperBroker(free_config())
    broker.submit(paper_signal())
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:01Z")
    broker.on_price("SYNTHETIC", 102, "2020-01-01T00:01:30Z")
    assert broker.position["stop"] == 99
    broker.on_minute_closed("2020-01-01T00:02:00Z")
    assert broker.position["stop"] == 101
    broker.on_price("SYNTHETIC", 100.9, "2020-01-01T00:02:01Z")
    assert broker.position is None
    assert broker.events[-1]["net_pnl"] > 0


def test_stale_paper_signal_is_not_executed():
    broker = PaperBroker(free_config())
    broker.submit(paper_signal())
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:03:00Z")
    assert broker.position is None
    assert broker.pending is None
    assert broker.events[-1]["event"] == "signal_expired"


def test_paper_short_exit_is_buy_and_funding_deduplicates():
    broker = PaperBroker(free_config(market="usd_m"))
    broker.submit(paper_signal(side=-1))
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:01Z")
    broker.on_funding("settle-1", "SYNTHETIC", .001, 100, "2020-01-01T00:02:00Z")
    after = broker.balance
    broker.on_funding("settle-1", "SYNTHETIC", .001, 100, "2020-01-01T00:02:00Z")
    assert broker.balance == after and after > 10000
    broker.on_price("SYNTHETIC", 102, "2020-01-01T00:02:01Z")
    assert broker.events[-1]["side"] == "BUY"


def test_paper_time_stop():
    broker = PaperBroker(free_config())
    broker.submit(paper_signal(max_hold_minutes=1))
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:00Z")
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:02:00Z")
    assert broker.events[-1]["reason"] == "time_stop"


def test_portfolio_prevents_overlapping_global_positions():
    data = array_bars([[100, 100.2, 99.8, 100]] * 1440)
    start = pd.Timestamp("2020-01-01", tz="UTC")
    rows = []
    for index, symbol in [(0, "A"), (1, "B")]:
        rows.append({**candidate(signal_index=index), "symbol": symbol, "strategy": "ema_pullback",
                     "regime": 1, "probability": .9, "expected_r": .3,
                     "signal_time": start + pd.Timedelta(minutes=index + 1)})
    report, trades, curve = evaluate(pd.DataFrame(rows), {"A": data, "B": data}, free_config(),
                                    start, start + pd.Timedelta(days=1), .7)
    assert len(trades) == 1
    assert report["one_global_position"]
    assert trades.notional.max() <= 10000


def test_quote_before_signal_cannot_enter():
    broker = PaperBroker(free_config())
    broker.submit(paper_signal())
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:00:59Z")
    assert broker.position is None
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:01Z")
    assert broker.position is not None


def test_out_of_order_quote_cannot_stop_position_in_the_past():
    broker = PaperBroker(free_config())
    broker.submit(paper_signal())
    broker.on_price("SYNTHETIC", 100, "2020-01-01T00:01:01Z")
    broker.on_price("SYNTHETIC", 1, "2020-01-01T00:00:59Z")
    assert broker.position is not None
