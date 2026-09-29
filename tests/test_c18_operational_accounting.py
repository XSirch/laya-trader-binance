from datetime import UTC, datetime
import sqlite3
from xml.etree import ElementTree

import pytest

from jev_trader import lowvol_hgb_account as account
from jev_trader import lowvol_hgb_paper as paper


def _tick(timestamp_ms, midpoint=100.0, funding=()):
    return {
        "server_time_ms": timestamp_ms,
        "accepted_quotes": {
            "BTCUSDT": {"bidPrice": midpoint - 0.01, "askPrice": midpoint + 0.01},
        },
        "funding": list(funding),
    }


def test_observation_every_15_minutes_keeps_decisions_in_frozen_weekly_window():
    start = int(datetime(2026, 10, 5, 1, 0, tzinfo=UTC).timestamp() * 1000)
    end = start + 8 * 24 * 60 * 60 * 1000
    state = account.initialize(start - 15 * 60_000)
    now = start
    weekly_decisions = int(paper._scheduled(now))
    state = account.advance(
        state, _tick(now), {"BTCUSDT": 0.25},
        fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE,
    )
    observations = 1
    funding_events = []
    next_funding_ms = start + 8 * 60 * 60_000

    while state["last_ms"] + 15 * 60_000 <= end:
        now = state["last_ms"] + 15 * 60_000
        if paper._scheduled(now):
            weekly_decisions += 1
        due = []
        if next_funding_ms <= now:
            due.append({"symbol": "BTCUSDT", "timestamp_ms": next_funding_ms,
                        "rate": 0.0001, "mark_price": 100.0})
            funding_events.append(next_funding_ms)
            next_funding_ms += 8 * 60 * 60_000
        state = account.advance(
            state, _tick(now, midpoint=100.0 + observations * 0.001, funding=due),
            fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE,
        )
        observations += 1

    assert observations >= 8 * 24 * 4
    assert weekly_decisions == 2
    assert len(funding_events) == len(set(funding_events))
    assert len(funding_events) >= 23
    assert set(state["positions"]) == {"BTCUSDT"}
    assert state["last_ms"] > start + 7 * 24 * 60 * 60_000
    assert not state["live_orders_enabled"]


def test_open_position_still_blocks_observation_gap_over_65_minutes():
    start = int(datetime(2026, 10, 5, 1, 0, tzinfo=UTC).timestamp() * 1000)
    opened = account.advance(
        account.initialize(start), _tick(start + 15 * 60_000), {"BTCUSDT": 0.25},
        fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE,
    )

    on_limit = account.advance(
        opened, _tick(opened["last_ms"] + account.MAX_GAP_MS),
        fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE,
    )
    assert on_limit["last_ms"] - opened["last_ms"] == account.MAX_GAP_MS

    with pytest.raises(ValueError, match="exceeds 65 minutes"):
        account.advance(
            opened, _tick(opened["last_ms"] + account.MAX_GAP_MS + 1),
            fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE,
        )


def _metrics_input(closed_trades, *, equity=10_000.0):
    return {
        "closed_trades": closed_trades,
        "positions": {},
        "equity": equity,
        "initial_equity": 10_000.0,
        "max_drawdown": 0.0,
        "turnover_notional": 0.0,
        "fees": 0.0,
        "funding_pnl": 0.0,
    }


def _closed_trade(trade_id, net_pnl, notional, entry_ms):
    return {
        "trade_id": trade_id,
        "symbol": "BTCUSDT",
        "direction": 1 if net_pnl >= 0 else -1,
        "entry_ms": entry_ms,
        "net_pnl": net_pnl,
        "entry_notional": notional,
        "net_return_on_entry_notional": net_pnl / notional,
    }


def test_profit_factor_and_gate_use_monetary_pnls_while_ev_stays_normalized(monkeypatch):
    monkeypatch.setattr(paper, "_clustered_intervals", lambda trades: None)
    entry_ms = int(datetime(2026, 10, 5, tzinfo=UTC).timestamp() * 1000)
    base_trades = [
        _closed_trade("large-win", 20.0, 1_000.0, entry_ms),
        _closed_trade("small-loss", -10.0, 100.0, entry_ms + 7 * 24 * 60 * 60_000),
    ]
    stress_trades = [
        _closed_trade("large-win", 10.0, 1_000.0, entry_ms),
        _closed_trade("small-loss", -20.0, 100.0, entry_ms + 7 * 24 * 60 * 60_000),
    ]
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE equity_points(timestamp_ms,base_equity,stress_equity,sequence)")

    result = paper._metrics(
        connection,
        _metrics_input(base_trades, equity=10_010.0),
        _metrics_input(stress_trades, equity=9_990.0),
    )

    assert result["profit_factor"] == pytest.approx(2.0)
    assert result["stress_profit_factor"] == pytest.approx(0.5)
    assert result["mean_net_ev_pct_per_episode"] == pytest.approx(-4.0)
    assert result["profit_factor_gate_passed"] is True
    assert result["sample_gate_passed"] is False
    assert result["profit_factor_definition"] == "sum_positive_net_pnl_usd / abs(sum_negative_net_pnl_usd)"


def test_zero_losses_are_explicit_and_cannot_pass_the_sample_gate(monkeypatch):
    monkeypatch.setattr(paper, "_clustered_intervals", lambda trades: None)
    start = int(datetime(2026, 10, 5, tzinfo=UTC).timestamp() * 1000)
    trades = [
        _closed_trade(f"win-{index}", 20.0, 1_000.0, start + index * 7 * 24 * 60 * 60_000)
        for index in range(200)
    ]
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE equity_points(timestamp_ms,base_equity,stress_equity,sequence)")

    result = paper._metrics(
        connection,
        _metrics_input(trades, equity=14_000.0),
        _metrics_input(trades, equity=14_000.0),
    )

    assert result["profit_factor"] == "unbounded"
    assert result["profit_factor_gate_passed"] is False
    assert result["sample_gate_passed"] is False


def test_weekly_decision_reservation_is_idempotent_and_runtime_lock_skips_overlap(tmp_path):
    database = tmp_path / "paper.sqlite3"
    original_database, original_paper = paper.DATABASE, paper.PAPER
    paper.DATABASE, paper.PAPER = database, tmp_path
    try:
        connection = paper._connect()
        start = int(datetime(2026, 10, 5, 1, 0, tzinfo=UTC).timestamp() * 1000)
        base, stress = account.initialize(start - 1), account.initialize(start - 1)
        first = paper._reserve_weekly_decision(
            connection, feature_cutoff_ms=start - 3_600_000, attempted_server_ms=start,
            base_state=base, stress_state=stress,
        )
        repeated = paper._reserve_weekly_decision(
            connection, feature_cutoff_ms=start - 3_600_000, attempted_server_ms=start + 1,
            base_state=base, stress_state=stress,
        )
        assert first[0] is True and first[1]
        assert repeated == (False, None)
        assert connection.execute("SELECT COUNT(*) FROM decision_attempts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
        connection.close()
    finally:
        paper.DATABASE, paper.PAPER = original_database, original_paper

    with paper._exclusive_paper_tick_lock(tmp_path / "lock") as first_lock:
        assert first_lock is True
        with paper._exclusive_paper_tick_lock(tmp_path / "lock") as overlapping_lock:
            assert overlapping_lock is False


def test_observability_reports_positions_block_reason_and_next_decision():
    start = int(datetime(2026, 10, 5, 1, 0, tzinfo=UTC).timestamp() * 1000)
    state = account.advance(
        account.initialize(start - 1), _tick(start), {"BTCUSDT": -0.25},
        fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE,
    )

    observed = paper._operational_status(state, start, status="blocked", blocking_reason="test_gap")

    assert observed["last_accounted_server_time_ms"] == start
    assert observed["heartbeat_age_ms_at_write"] == 0
    assert observed["next_weekly_decision_utc"] == "2026-10-12T01:00:00Z"
    assert observed["open_positions"][0]["direction"] == "short"
    assert observed["blocking_reason"] == "test_gap"
    assert observed["orders_enabled"] is False

    before_first = int(datetime(2026, 9, 29, 12, 0, tzinfo=UTC).timestamp() * 1000)
    assert paper._next_weekly_decision_utc(before_first) == "2026-10-05T01:00:00Z"


def test_prepared_task_repeats_observation_without_changing_weekly_decision_window():
    task_path = (
        paper.ROOT / "research/results/cycle18_lowvol_hgb_forward/paper/"
        "task_definition_observation_15m.xml"
    )
    tree = ElementTree.parse(task_path)
    namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = tree.getroot()
    assert root.find("t:RegistrationInfo/t:URI", namespace).text == "\\C18-LowVol-HGB-Paper"
    assert root.find("t:Triggers/t:CalendarTrigger/t:Repetition/t:Interval", namespace).text == "PT15M"
    assert root.find("t:Settings/t:MultipleInstancesPolicy", namespace).text == "IgnoreNew"

    monday = int(datetime(2026, 10, 5, 1, 0, tzinfo=UTC).timestamp() * 1000)
    assert paper._scheduled(monday) is True
    assert paper._scheduled(monday + 4 * 60_000 + 59_000) is True
    assert paper._scheduled(monday + 5 * 60_000) is False
    assert paper._scheduled(monday + 15 * 60_000) is False
