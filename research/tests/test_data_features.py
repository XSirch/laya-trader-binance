import io
import hashlib
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from binance_multistrategy.config import ResearchConfig
from binance_multistrategy.data import (parse_times, parse_klines, validate_candles,
                                        verified_archive, load_dataset, recover_missing_mark_prices)
from binance_multistrategy.features import build_features, rsi, MODEL_FEATURES
from binance_multistrategy.strategies import generate_candidates, INPUT_FEATURES, STRATEGIES


def test_timestamp_millisecond_microsecond_transition():
    values = pd.Series([1735689540000, 1735689600000000])
    result = parse_times(values)
    assert result.iloc[1] - result.iloc[0] == pd.Timedelta(minutes=1)


def test_parse_timestamp_iso():
    assert str(parse_times(pd.Series(["2020-01-01T00:00:00Z"])).iloc[0]).startswith("2020-01-01")


def test_raw_archive_with_or_without_header():
    row = "1577836800000,100,102,99,101,5,1577836859999,505,10,2,202,0\n"
    plain = parse_klines(row.encode())
    names = "open_time,open,high,low,close,volume,close_time,quote_volume,num_trades,taker_buy_base,taker_buy_quote,ignore\n"
    header = parse_klines((names + row).encode())
    pd.testing.assert_frame_equal(plain, header)


def test_checksum_enforced(monkeypatch, tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("data.csv", "a,b\n1,2\n")
    content = output.getvalue()
    correct = hashlib.sha256(content).hexdigest().encode() + b" data.zip"
    monkeypatch.setattr("binance_multistrategy.data.get_bytes", lambda url: correct if url.endswith("CHECKSUM") else content)
    raw, receipt = verified_archive("https://example.test/data.zip", tmp_path)
    assert raw == b"a,b\n1,2\n"
    assert receipt["sha256"] == hashlib.sha256(content).hexdigest()
    (tmp_path / receipt["cache_file"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="SHA256"):
        verified_archive("https://example.test/data.zip", tmp_path)


def test_missing_minute_is_not_invented(bars):
    with pytest.raises(ValueError, match="missing/non-1m"):
        validate_candles(bars.drop(index=30), "spot")


def test_duplicate_candle_rejected(bars):
    with pytest.raises(ValueError, match="Duplicate"):
        validate_candles(pd.concat([bars, bars.iloc[[30]]]), "spot")


def test_invalid_ohlc_rejected(bars):
    data = bars.copy()
    data.loc[2, "high"] = .01
    with pytest.raises(ValueError, match="OHLC"):
        validate_candles(data, "spot")


def test_unclosed_bar_rejected(bars):
    data = bars.tail(1).copy()
    data["open_time"] = pd.Timestamp.now(tz="UTC").ceil("min")
    with pytest.raises(ValueError, match="unclosed"):
        validate_candles(data, "spot")


def test_futures_does_not_assume_zero_funding(tmp_path, bars):
    filename = tmp_path / "provided.csv"
    bars.drop(columns=["market"]).to_csv(filename, index=False)
    with pytest.raises(ValueError, match="funding archives"):
        load_dataset(filename, "usd_m")


def test_daily_mark_archive_recovers_only_missing_verified_rows(monkeypatch, tmp_path):
    times = pd.date_range("2026-06-29T00:00:00Z", periods=3, freq="min")
    def millis(value):
        return int(value.timestamp() * 1000)
    rows = [f"{millis(t)},100,102,99,101,5,{millis(t)+59999},505,10,2,202,0" for t in times]
    content = ("open_time,open,high,low,close,volume,close_time,quote_volume,num_trades,taker_buy_base,taker_buy_quote,ignore\n"
               + "\n".join(rows) + "\n").encode()
    def fake_verified(url, cache):
        assert "2026-06-29.zip" in url
        return content, {"url": url, "sha256": "verified-in-test", "bytes": len(content)}
    monkeypatch.setattr("binance_multistrategy.data.verified_archive", fake_verified)
    candles = pd.DataFrame({"open_time": times})
    monthly = pd.DataFrame({"open_time": times[:1], "mark_open": [100.0], "mark_high": [102.0],
                            "mark_low": [99.0], "mark_close": [101.0]})
    receipts = []
    result = recover_missing_mark_prices("BTCUSDT", candles, monthly, tmp_path, receipts)
    assert result.open_time.is_unique
    assert len(result) == 3
    assert receipts[0]["archive_kind"] == "daily_mark_recovery"
    assert receipts[0]["recovered_rows"] == 2


def test_daily_mark_archive_does_not_fill_unavailable_rows(monkeypatch, tmp_path):
    def fake_verified(url, cache):
        return b"open_time,open,high,low,close,volume,close_time,quote_volume,num_trades,taker_buy_base,taker_buy_quote,ignore\n", {"url": url}
    monkeypatch.setattr("binance_multistrategy.data.verified_archive", fake_verified)
    candles = pd.DataFrame({"open_time": pd.date_range("2026-06-29T00:00:00Z", periods=1, freq="min")})
    monthly = pd.DataFrame({"open_time": pd.DatetimeIndex([], tz="UTC"), "mark_open": [], "mark_high": [],
                            "mark_low": [], "mark_close": []})
    with pytest.raises(ValueError, match="no gap-filling"):
        recover_missing_mark_prices("BTCUSDT", candles, monthly, tmp_path, [])


def test_rsi_edge_cases():
    assert rsi(pd.Series(np.arange(40, dtype=float))).iloc[-1] == 100
    assert rsi(pd.Series(-np.arange(40, dtype=float))).iloc[-1] == 0
    assert rsi(pd.Series(np.ones(40))).iloc[-1] == 50


def test_feature_prefix_invariance(bars):
    full = build_features(bars)
    for length in [12503, 15559]:
        prefix = build_features(bars.iloc[:length])
        pd.testing.assert_frame_equal(full.iloc[:length][MODEL_FEATURES], prefix[MODEL_FEATURES])


def test_higher_timeframes_not_visible_early(bars):
    f = build_features(bars)
    # At 03:01, 03:02,...03:59 the last available 60m candle remains 03:00.
    j = 60 * 210
    assert f.loc[j:j + 57, "60m_rsi"].nunique() == 1
    assert not f.loc[:11997, "ready"].any()
    assert f.ready.any()


def test_donchian_excludes_current_bar(bars):
    altered = bars.copy()
    altered.loc[15000, "high"] *= 10
    old = build_features(bars)
    new = build_features(altered)
    assert old.loc[15000, "don_high"] == new.loc[15000, "don_high"]
    assert new.loc[15001, "don_high"] > old.loc[15001, "don_high"]


def test_spot_candidates_are_long_only(bars):
    f = build_features(bars)
    candidates = generate_candidates(f, "SYNTHETIC", ResearchConfig())
    assert len(candidates) > 0
    assert set(candidates.side) == {1}
    assert set(INPUT_FEATURES).issubset(candidates.columns)
    assert len(STRATEGIES) == 8
    assert "label" not in INPUT_FEATURES and "net_return" not in INPUT_FEATURES


def test_future_candidate_prefix_not_rewritten(bars):
    config = ResearchConfig(market="usd_m", fee_bps=5)
    all_rows = generate_candidates(build_features(bars), "SYNTHETIC", config)
    length = 16003
    prefix = generate_candidates(build_features(bars.iloc[:length]), "SYNTHETIC", config)
    cut = bars.open_time.iloc[length - 1] + pd.Timedelta(minutes=1)
    expected = all_rows.loc[all_rows.signal_time <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(expected, prefix)


@pytest.mark.parametrize("kwargs", [dict(market="futures"), dict(fee_bps=-1), dict(risk_fraction=2),
                                    dict(max_notional_equity=10), dict(minimum_probability=1),
                                    dict(embargo_minutes=0), dict(min_stop_fraction=.1, max_stop_fraction=.01)])
def test_invalid_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        ResearchConfig(**kwargs)
