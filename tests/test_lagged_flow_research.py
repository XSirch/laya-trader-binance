from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jev_trader import lagged_flow_research as research
from jev_trader import lagged_flow_prediction as prediction
from jev_trader.lagged_flow_prediction import SYMBOLS


H = 3_600_000
T0 = 1_704_067_200_000


def bar(timestamp):
    return SimpleNamespace(open_ms=timestamp, open=100.0, high=101.0, low=99.0,
        close=100.0, volume=100.0, quote_volume=10_000.0,
        trades=10, taker_buy_base=50.0)


def test_protocol_runtime_and_twenty_scenario_grid_are_anchored():
    anchored = research.anchors()
    assert anchored["runtime"] == research.RUNTIME
    assert len(research.CONFIG["models"]) * len(research.CONFIG["side_costs"]) * 2 == 20
    assert research.CONFIG["symbols"] == list(SYMBOLS)
    assert research.CONFIG["decision_interval_hours"] == research.CONFIG["target_horizon_hours"] == 8


def test_build_panel_uses_same_base_fields_and_masks_self_as_leader():
    bars = {symbol: {timestamp: bar(timestamp)
            for timestamp in range(T0 - 10 * H, T0 + H, H)} for symbol in SYMBOLS}
    market = {"spot": bars}
    contexts = {symbol: {T0: {"symbol": symbol}} for symbol in SYMBOLS}
    flat = {T0: {"base.return": .001, "context_sha256": "a" * 64}}
    with patch.object(prediction, "build_contexts", return_value=(contexts, {"audit": True})), \
         patch("jev_trader.lagged_flow_prediction.flatten_contexts",
               return_value=(flat, ("base.return",), "b" * 64)):
        panel, fields, audit = research.build_panel(market)
    assert len(panel) == len(SYMBOLS)
    assert "leader.BTCUSDT.return_1h" in fields
    btc = panel[(T0, "BTCUSDT")]
    bnb = panel[(T0, "BNBUSDT")]
    btc_leader_index = fields.index("leader.BTCUSDT.return_1h")
    assert btc["features"][btc_leader_index] is None
    assert bnb["features"][btc_leader_index] == .0
    assert audit["event_count"] == 4
    assert audit["field_count"] == len(fields)


def test_calendar_year_compounds_monthly_returns():
    result = research.calendar_year_returns({"2025-01": 10.0, "2025-02": -10.0,
                                             "2026-01": 5.0})
    assert result["2025"] == pytest.approx(-1.0)
    assert result["2026"] == pytest.approx(5.0)


def test_invalid_expected_fill_is_not_recast_as_a_valid_scenario():
    forecasts = {"predictions": {"own_hgb": {}}}
    with patch.object(research, "evaluate", side_effect=research.ExecutionUnavailable("missing held bar")):
        result = research.scenario({}, {}, forecasts, "own_hgb", .0015, "later")
    assert result["status"] == "invalid_execution"
    assert result["metrics"] is None
