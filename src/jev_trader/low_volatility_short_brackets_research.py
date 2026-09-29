"""Replay de brackets sobre a política short-only congelada; nenhuma ordem real."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import broad_data, broad_research, broad_trade_reanalysis, low_volatility_ev_forecast_research
from . import low_volatility_short_only_research as source_research


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"
SOURCE_REPORT = RESULTS / "low_volatility_short_only_20260928.json"
SOURCE_LEDGER = RESULTS / "low_volatility_short_only_ledger_20260928.csv"
PROTOCOL = DOCS / "low_volatility_short_brackets_protocol_2026-09-28.md"
OUTPUT = RESULTS / "low_volatility_short_brackets_20260928.json"
OUTPUT_CSV = RESULTS / "low_volatility_short_brackets_ledger_20260928.csv"
OUTPUT_MD = DOCS / "low_volatility_short_brackets_research_2026-09-28.md"

DAY_MS = 86_400_000
GROSS_SHORT = 0.25
BASE_SIDE_COST = 0.001
STRESS_SIDE_COST = 0.002
SOURCE_STRESS_SIDE_COST = 0.0015
STOP_PCTS = (0.04, 0.06, 0.08, 0.10)
TARGET_RS = (1.2, 1.5)
EVALUATION_PERIODS = (
    "validation_2024",
    "calibration_2025h1",
    "validation_2025h2",
    "confirmation_2026",
    "combined",
)
PERIODS = source_research.PERIODS
FLOAT_FIELDS = (
    "entry_price",
    "exit_price",
    "hold_days",
    "entry_notional",
    "price_pnl",
    "funding_pnl",
    "fees",
    "net_pnl",
    "net_return_pct_on_entry_notional",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _decision_policy(states: dict, saved_rows: list[dict], period: str) -> tuple[dict, dict]:
    """Rebuild accepted short legs from saved forecasts, without fitting a model."""
    policy: dict[int, dict[str, float]] = {}
    held: dict[str, int] = {}
    checked = []
    previous_timestamp = None

    for saved in saved_rows:
        timestamp = int(saved["decision_ms"])
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError(f"weekly decisions are duplicated or unordered: {period} {timestamp}")
        previous_timestamp = timestamp
        current = {symbol: rows[timestamp] for symbol, rows in states.items() if timestamp in rows}
        base_targets = broad_research.target_weights(current, "low_volatility30_betahedged")
        short_candidates = sorted(symbol for symbol, weight in base_targets.items() if weight < 0)
        if len(short_candidates) != int(saved["base_short_candidates"]):
            raise ValueError(f"base short candidate count changed: {period} {timestamp}")

        accepted: dict[str, int] = {}
        predictions = saved.get("predicted_net_return_pct", {})
        if saved.get("model_available"):
            for symbol in short_candidates:
                if held.get(symbol) == -1:
                    accepted[symbol] = -1
                    continue
                forecast = predictions.get(symbol)
                if forecast is not None and float(forecast) >= low_volatility_ev_forecast_research.PREDICTED_EV_THRESHOLD_PCT:
                    accepted[symbol] = -1

        expected_count = int(saved["accepted_short_legs"])
        if len(accepted) != expected_count:
            raise ValueError(
                f"reconstructed accepted-leg count differs: {period} {timestamp}; "
                f"expected {expected_count}, found {len(accepted)}"
            )
        if set(predictions) - set(short_candidates):
            raise ValueError(f"saved prediction is not a current short candidate: {period} {timestamp}")

        policy[timestamp] = ({symbol: -GROSS_SHORT / len(accepted) for symbol in accepted}
                             if accepted else {})
        checked.append({
            "decision_ms": timestamp,
            "base_short_candidates": len(short_candidates),
            "accepted_short_legs": len(accepted),
            "accepted_symbols": sorted(accepted),
        })
        held = accepted

    serializable_policy = {
        str(timestamp): {symbol: float(weight) for symbol, weight in sorted(targets.items())}
        for timestamp, targets in sorted(policy.items())
    }
    return policy, {
        "decision_count": len(checked),
        "decision_checks": checked,
        "policy_sha256": _json_sha256(serializable_policy),
        "accepted_leg_total": sum(row["accepted_short_legs"] for row in checked),
    }


def _assert_float(actual: float, expected: float, description: str, tolerance: float = 1e-8) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance):
        raise ValueError(f"source reconciliation failed for {description}: {actual} != {expected}")


def _compare_control_ledger(actual: list[dict], expected: list[dict], period: str, cost: str) -> int:
    def ordering(row):
        return (int(row["entry_ms"]), str(row["symbol"]), int(row["exit_ms"]), str(row["exit_reason"]))

    ours = sorted(actual, key=ordering)
    theirs = sorted(expected, key=ordering)
    if len(ours) != len(theirs):
        raise ValueError(f"source ledger episode count changed: {period}/{cost}: {len(ours)} != {len(theirs)}")
    for index, (left, right) in enumerate(zip(ours, theirs)):
        for field in ("symbol", "exit_reason"):
            if str(left[field]) != str(right[field]):
                raise ValueError(f"source ledger {field} mismatch at {period}/{cost}/{index}")
        for field in ("direction", "entry_ms", "exit_ms"):
            if int(left[field]) != int(right[field]):
                raise ValueError(f"source ledger {field} mismatch at {period}/{cost}/{index}")
        if bool(left["unresolved_proxy_exit"]) != (str(right["unresolved_proxy_exit"]).lower() == "true"):
            raise ValueError(f"source ledger unresolved flag mismatch at {period}/{cost}/{index}")
        for field in FLOAT_FIELDS:
            _assert_float(left[field], float(right[field]), f"{period}/{cost}/{index}/{field}")
    return len(ours)


def _compare_source_metrics(actual_summary: dict, actual_portfolio: dict,
                            expected: dict, period: str, cost: str) -> None:
    for field in ("episodes", "wins", "losses", "flats", "unresolved_proxy_episodes"):
        if int(actual_summary[field]) != int(expected[field]):
            raise ValueError(f"source report {field} mismatch: {period}/{cost}")
    for field in (
        "win_rate_pct",
        "mean_win_pct",
        "mean_loss_pct",
        "net_payoff_ratio",
        "ev_net_pct_per_episode_on_entry_notional",
    ):
        left, right = actual_summary.get(field), expected.get(field)
        if left is None or right is None:
            if left is not right:
                raise ValueError(f"source report {field} mismatch: {period}/{cost}")
        else:
            _assert_float(left, right, f"{period}/{cost}/{field}")
    expected_portfolio = expected["portfolio_replay"]
    for field in ("return_pct", "max_drawdown_pct", "fees_pct_initial", "funding_pct_initial"):
        _assert_float(actual_portfolio[field], expected_portfolio[field], f"{period}/{cost}/{field}")
    if int(actual_portfolio["unresolved_exits"]) != int(expected_portfolio["unresolved_exits"]):
        raise ValueError(f"source report unresolved exits mismatch: {period}/{cost}")


def _barrier_fill(row: dict, bar) -> tuple[float, str] | None:
    if row["stop_price"] is None:
        return None
    if bar.open >= row["stop_price"]:
        return bar.open, "stop_gap"
    if bar.open <= row["target_price"]:
        return bar.open, "target_gap"
    stop_hit = bar.high >= row["stop_price"]
    target_hit = bar.low <= row["target_price"]
    if stop_hit and target_hit:
        return row["stop_price"], "stop_both_touched"
    if stop_hit:
        return row["stop_price"], "stop"
    if target_hit:
        return row["target_price"], "target"
    return None


def _simulate_brackets(data, policy: dict[int, dict[str, float]], start: str, end: str,
                       side_cost: float, stop_pct: float | None,
                       target_r: float | None) -> tuple[list[dict], dict]:
    start_ms, end_ms = low_volatility_ev_forecast_research.utc_ms(start), low_volatility_ev_forecast_research.utc_ms(end)
    bars = {symbol: {bar.open_ms: bar for bar in rows} for symbol, rows in data["klines"].items()}
    marks = {symbol: {bar.open_ms: bar for bar in rows} for symbol, rows in data["markPriceKlines"].items()}
    funding = {symbol: {} for symbol in bars}
    for symbol, rows in data["fundingRate"].items():
        for event in rows:
            funding[symbol].setdefault(event.timestamp_ms // DAY_MS * DAY_MS, []).append(event)

    quantity: dict[str, float] = {}
    previous_price: dict[str, float] = {}
    active: dict[str, dict] = {}
    episodes: list[dict] = []
    equity = 1.0
    fees = funding_pnl = 0.0
    unresolved_count = 0
    marked_path = [1.0]
    adverse_path = [1.0]

    def close_episode(symbol: str, timestamp: int, price: float, reason: str,
                      unresolved: bool = False) -> dict | None:
        row = active.pop(symbol, None)
        if row is None:
            return None
        row.update({
            "exit_ms": timestamp,
            "exit_price": price,
            "exit_reason": reason,
            "unresolved_proxy_exit": unresolved,
            "hold_days": (timestamp - row["entry_ms"]) / DAY_MS,
        })
        row["net_return_pct_on_entry_notional"] = 100 * row["net_pnl"] / row["entry_notional"]
        episodes.append(row)
        return row

    for timestamp in range(start_ms, end_ms + 1, DAY_MS):
        for symbol in list(quantity):
            current_quantity = quantity[symbol]
            bar = bars[symbol].get(timestamp)
            if bar is None:
                prior = bars[symbol].get(timestamp - DAY_MS)
                if prior is None:
                    raise ValueError(f"cannot value unresolved disappearance: {symbol} {timestamp}")
                price_pnl = current_quantity * (prior.close - previous_price[symbol])
                charge = abs(current_quantity) * prior.close * (side_cost + 0.02)
                equity += price_pnl - charge
                active[symbol]["net_pnl"] += price_pnl - charge
                active[symbol]["price_pnl"] += price_pnl
                active[symbol]["fees"] += charge
                close_episode(symbol, timestamp, prior.close, "unresolved_listing_exit_proxy", True)
                quantity.pop(symbol)
                previous_price.pop(symbol, None)
                fees += charge
                unresolved_count += 1
                continue
            price_pnl = current_quantity * (bar.open - previous_price[symbol])
            equity += price_pnl
            active[symbol]["net_pnl"] += price_pnl
            active[symbol]["price_pnl"] += price_pnl
            previous_price[symbol] = bar.open

        if equity <= 0:
            raise ValueError(f"insolvent bracket portfolio at daily open {timestamp}: equity={equity}")

        old_quantity = dict(quantity)
        old_active = dict(active)
        blocked_today: set[str] = set()
        terminal = timestamp == end_ms

        if not terminal:
            for symbol in list(quantity):
                bar = bars[symbol][timestamp]
                row = active[symbol]
                if row["stop_price"] is None:
                    continue
                if bar.open >= row["stop_price"]:
                    fill_price, reason = bar.open, "stop_gap"
                elif bar.open <= row["target_price"]:
                    fill_price, reason = bar.open, "target_gap"
                else:
                    continue
                current_quantity = quantity[symbol]
                close_fee = abs(current_quantity) * fill_price * side_cost
                equity -= close_fee
                row["net_pnl"] -= close_fee
                row["fees"] += close_fee
                fees += close_fee
                close_episode(symbol, timestamp, fill_price, reason)
                quantity.pop(symbol)
                previous_price.pop(symbol, None)
                blocked_today.add(symbol)

        rebalanced = (datetime.fromtimestamp(timestamp / 1000, timezone.utc).weekday() == 0) or terminal
        if rebalanced:
            targets = {} if terminal else dict(policy.get(timestamp, {}))
            targets = {symbol: value for symbol, value in targets.items()
                       if symbol in bars and timestamp in bars[symbol]}
            starting_equity = equity
            for symbol in sorted(set(quantity) | set(targets)):
                bar = bars[symbol].get(timestamp)
                if bar is None:
                    continue
                price = bar.open
                weight = 0.0 if symbol in blocked_today else targets.get(symbol, 0.0)
                desired = weight * starting_equity / price
                previous = quantity.get(symbol, 0.0)
                charge = abs(desired - previous) * price * side_cost
                equity -= charge

                if not previous and desired:
                    entry_notional = abs(desired) * price
                    active[symbol] = {
                        "symbol": symbol,
                        "direction": -1,
                        "entry_ms": timestamp,
                        "entry_price": price,
                        "entry_notional": entry_notional,
                        "net_pnl": -charge,
                        "price_pnl": 0.0,
                        "fees": charge,
                        "funding_pnl": 0.0,
                        "unresolved_proxy_exit": False,
                        "stop_price": price * (1 + stop_pct) if stop_pct is not None else None,
                        "target_price": price * (1 - target_r * stop_pct)
                        if stop_pct is not None and target_r is not None else None,
                    }
                elif previous and not desired:
                    active[symbol]["net_pnl"] -= charge
                    active[symbol]["fees"] += charge
                    close_episode(symbol, timestamp, price, "signal_flat_or_terminal")
                elif previous and desired:
                    active[symbol]["net_pnl"] -= charge
                    active[symbol]["fees"] += charge

                if desired:
                    quantity[symbol], previous_price[symbol] = desired, price
                else:
                    quantity.pop(symbol, None)
                    previous_price.pop(symbol, None)
                fees += charge

        if terminal:
            if quantity or active:
                raise ValueError(f"terminal portfolio did not close: {timestamp}")
            marked_path.append(equity)
            adverse_path.append(equity)
            break

        day_fills = {}
        for symbol in list(quantity):
            bar = bars[symbol][timestamp]
            fill = _barrier_fill(active[symbol], bar)
            if fill is not None:
                day_fills[symbol] = fill

        for symbol in set(old_quantity) | set(quantity):
            mark = marks.get(symbol, {}).get(timestamp)
            if mark is None:
                continue
            for event in funding[symbol].get(timestamp, []):
                new_scalar = -quantity.get(symbol, 0.0) * event.rate
                old_scalar = -old_quantity.get(symbol, 0.0) * event.rate
                scalar = new_scalar
                recipient = active.get(symbol)
                at_open = event.timestamp_ms - timestamp < 60_000
                if at_open and old_scalar < new_scalar:
                    scalar = old_scalar
                    recipient = old_active.get(symbol)
                payment = scalar * (mark.low if scalar >= 0 else mark.high)
                if not at_open and symbol in day_fills and payment > 0:
                    payment = 0.0
                equity += payment
                funding_pnl += payment
                if recipient is not None:
                    recipient["net_pnl"] += payment
                    recipient["funding_pnl"] += payment

        adverse_path.append(equity)
        worst_equity = equity
        for symbol, current_quantity in quantity.items():
            bar = bars[symbol][timestamp]
            adverse_price = bar.high if current_quantity < 0 else bar.low
            worst_equity += current_quantity * (adverse_price - bar.open)
        if equity <= 0:
            raise ValueError(f"insolvent bracket portfolio at {timestamp}: equity={equity}")

        for symbol, (fill_price, reason) in day_fills.items():
            if symbol not in quantity:
                continue
            current_quantity = quantity[symbol]
            row = active[symbol]
            price_pnl = current_quantity * (fill_price - bars[symbol][timestamp].open)
            close_fee = abs(current_quantity) * fill_price * side_cost
            equity += price_pnl - close_fee
            row["net_pnl"] += price_pnl - close_fee
            row["price_pnl"] += price_pnl
            row["fees"] += close_fee
            fees += close_fee
            close_episode(symbol, timestamp, fill_price, reason)
            quantity.pop(symbol)
            previous_price.pop(symbol, None)

        marked_equity = equity
        for symbol, current_quantity in quantity.items():
            bar = bars[symbol][timestamp]
            marked_equity += current_quantity * (bar.close - bar.open)
        marked_path.append(marked_equity)
        adverse_path.append(worst_equity)
        adverse_path.append(marked_equity)

    def maximum_drawdown(path: list[float]) -> float:
        peak, drawdown = 1.0, 0.0
        for value in path:
            peak = max(peak, value)
            drawdown = max(drawdown, 1 - value / peak)
        return 100 * drawdown

    portfolio = {
        "return_pct": 100 * (equity - 1),
        "max_drawdown_pct": maximum_drawdown(marked_path),
        "max_adverse_daily_drawdown_pct": maximum_drawdown(adverse_path),
        "fees_pct_initial": 100 * fees,
        "funding_pct_initial": 100 * funding_pnl,
        "unresolved_exits": unresolved_count,
    }
    return episodes, portfolio


def _active_weeks(episodes: list[dict]) -> int:
    weeks = set()
    for row in episodes:
        first = int(row["entry_ms"])
        last = int(row["exit_ms"])
        first_week = first - datetime.fromtimestamp(first / 1000, timezone.utc).weekday() * DAY_MS
        last_week = last - datetime.fromtimestamp(last / 1000, timezone.utc).weekday() * DAY_MS
        for week_start in range(first_week, last_week + 1, 7 * DAY_MS):
            weeks.add(week_start)
    return len(weeks)


def _summarize(episodes: list[dict], portfolio: dict) -> dict:
    summary = broad_trade_reanalysis._summarize(episodes)
    gross_profit = math.fsum(max(0.0, row["net_pnl"]) for row in episodes)
    gross_loss = math.fsum(min(0.0, row["net_pnl"]) for row in episodes)
    summary.update({
        "profit_factor": gross_profit / abs(gross_loss) if gross_loss else None,
        "active_weeks": _active_weeks(episodes),
        "unique_complete_episodes": len({
            (row["symbol"], row["direction"], row["entry_ms"], row["exit_ms"]) for row in episodes
        }),
        "portfolio_replay": portfolio,
    })
    return summary


def _episode_rows(episodes: list[dict], period: str, variant: str,
                  stop_pct: float | None, target_r: float | None, cost: str, side_cost: float) -> list[dict]:
    return [{
        "period": period,
        "variant": variant,
        "stop_pct": stop_pct,
        "target_r": target_r,
        "cost": cost,
        "side_cost": side_cost,
        **row,
    } for row in episodes]


def _gate_result(base: dict, stress: dict) -> dict:
    gates = {
        "base_ev_above_1_2_pct": base["ev_net_pct_per_episode_on_entry_notional"] is not None
        and base["ev_net_pct_per_episode_on_entry_notional"] > 1.2,
        "base_payoff_at_least_1_to_1": base["net_payoff_ratio"] is not None
        and base["net_payoff_ratio"] >= 1.0,
        "base_profit_factor_at_least_1_25": base["profit_factor"] is not None
        and base["profit_factor"] >= 1.25,
        "base_at_least_200_unique_complete_episodes": base["unique_complete_episodes"] >= 200
        and base["unique_complete_episodes"] == base["episodes"],
        "base_at_least_8_active_weeks": base["active_weeks"] >= 8,
        "all_cost_scenarios_resolved": base["unresolved_proxy_episodes"] == 0
        and stress["unresolved_proxy_episodes"] == 0,
        "stress_2x_portfolio_pnl_positive": stress["portfolio_replay"]["return_pct"] > 0,
    }
    return {"numeric_gates": gates, "passes_numeric_gates": all(gates.values()),
            "historical_independent_confirmation": False}


def _fmt(value, suffix="%", digits=2):
    return "n/a" if value is None else f"{value:.{digits}f}{suffix}"


def _run() -> dict:
    for path in (OUTPUT, OUTPUT_CSV, OUTPUT_MD):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite research artifact: {path}")

    source_report = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    source_ledger_sha = _sha256(SOURCE_LEDGER)
    source_ev_ledger_sha = _sha256(low_volatility_ev_forecast_research.SOURCE_LEDGER)
    if source_ev_ledger_sha != source_report["source_ledger_sha256"]:
        raise ValueError("upstream EV ledger hash changed")
    source_code_sha = _sha256(Path(source_research.__file__))
    if source_code_sha != source_report["analysis_code_sha256"]:
        raise ValueError("source short-only analysis code hash changed")

    with source_research._offline_inputs():
        data, manifest, cohort = broad_data.load()
    if len(manifest) != source_report["source_manifest_entries"]:
        raise ValueError("offline manifest entry count differs from the frozen short-only run")
    states = broad_research.features(data)

    with SOURCE_LEDGER.open(newline="", encoding="utf-8") as handle:
        ledger_reader = csv.DictReader(handle)
        saved_ledger = list(ledger_reader)
    saved_by_period_cost: dict[tuple[str, str], list[dict]] = {}
    for row in saved_ledger:
        saved_by_period_cost.setdefault((row["period"], row["cost"]), []).append(row)

    all_rows = []
    periods_result = {}
    control_reconciliation = {}
    control_engine_parity = {}
    for period in EVALUATION_PERIODS:
        source_section = source_report["periods"][period]
        policy, reconstruction = _decision_policy(states, source_section["weekly_decisions"], period)
        start, end = PERIODS[period]
        variants = {}
        costs_to_run = (
            ("base", BASE_SIDE_COST),
            ("stress_2x", STRESS_SIDE_COST),
            ("source_stress_1_5x", SOURCE_STRESS_SIDE_COST),
        )

        control_results = {}
        for cost_name, side_cost in costs_to_run:
            if cost_name == "source_stress_1_5x":
                episodes, portfolio = low_volatility_ev_forecast_research._simulate(
                    data, states, policy, start, end, side_cost
                )
                expected_metrics = source_section["by_cost"]["stress"]
                source_cost_key = "stress"
                actual_cost_key = "stress"
            elif cost_name == "base":
                episodes, portfolio = low_volatility_ev_forecast_research._simulate(
                    data, states, policy, start, end, side_cost
                )
                expected_metrics = source_section["by_cost"]["base"]
                source_cost_key = "base"
                actual_cost_key = "base"
            else:
                episodes, portfolio = low_volatility_ev_forecast_research._simulate(
                    data, states, policy, start, end, side_cost
                )
                expected_metrics = None
                source_cost_key = None
                actual_cost_key = cost_name

            engine_expected = {
                **broad_trade_reanalysis._summarize(episodes),
                "portfolio_replay": portfolio,
            }
            if expected_metrics is not None:
                _compare_source_metrics(engine_expected, portfolio, expected_metrics, period, source_cost_key)
                count = _compare_control_ledger(
                    episodes, saved_by_period_cost[(period, source_cost_key)], period, source_cost_key
                )
                control_reconciliation[f"{period}/{source_cost_key}"] = {
                    "status": "PASS",
                    "episodes_compared": count,
                    "cost_per_side": side_cost,
                    "source_report_metrics_match": True,
                        "source_ledger_fields_match": list(FLOAT_FIELDS) + [
                            "symbol", "direction", "entry_ms", "exit_ms", "exit_reason", "unresolved_proxy_exit"
                        ],
                }
            exact_episodes, exact_portfolio = _simulate_brackets(
                data, policy, start, end, side_cost, None, None
            )
            exact_summary = broad_trade_reanalysis._summarize(exact_episodes)
            _compare_control_ledger(exact_episodes, episodes, period, actual_cost_key)
            for field in ("episodes", "wins", "losses", "flats", "win_rate_pct", "mean_win_pct",
                          "mean_loss_pct", "net_payoff_ratio",
                          "ev_net_pct_per_episode_on_entry_notional", "unresolved_proxy_episodes"):
                left, right = exact_summary.get(field), engine_expected.get(field)
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    _assert_float(left, right, f"custom parity {period}/{actual_cost_key}/{field}")
                elif left != right:
                    raise ValueError(f"custom parity mismatch: {period}/{actual_cost_key}/{field}")
            for field in ("return_pct", "fees_pct_initial", "funding_pct_initial"):
                _assert_float(exact_portfolio[field], portfolio[field],
                              f"custom parity {period}/{actual_cost_key}/{field}")
            if exact_portfolio["unresolved_exits"] != portfolio["unresolved_exits"]:
                raise ValueError(f"custom parity mismatch: {period}/{actual_cost_key}/unresolved_exits")
            control_engine_parity[f"{period}/{actual_cost_key}"] = {
                "status": "PASS",
                "episodes_compared": len(episodes),
                "portfolio_return_and_costs_match": True,
                "drawdown_comparison": "excluded because the custom control marks daily closes and the source engine records open-to-open values",
            }
            summary = _summarize(exact_episodes, exact_portfolio)
            control_results[cost_name] = {"metrics": summary, "episodes": exact_episodes, "side_cost": side_cost}
            all_rows.extend(_episode_rows(exact_episodes, period, "no_barrier_control", None, None,
                                          actual_cost_key, side_cost))

        base_control = control_results["base"]["metrics"]
        stress_control = control_results["stress_2x"]["metrics"]
        variants["no_barrier_control"] = {
            "costs": {
                "base": base_control,
                "stress_2x": stress_control,
                "source_stress_1_5x": control_results["source_stress_1_5x"]["metrics"],
            },
            **_gate_result(base_control, stress_control),
        }

        for stop_pct in STOP_PCTS:
            for target_r in TARGET_RS:
                variant = f"stop_{int(stop_pct * 100)}_target_{target_r:g}R"
                costs_result = {}
                for cost_name, side_cost in (("base", BASE_SIDE_COST), ("stress_2x", STRESS_SIDE_COST)):
                    episodes, portfolio = _simulate_brackets(
                        data, policy, start, end, side_cost, stop_pct, target_r
                    )
                    summary = _summarize(episodes, portfolio)
                    costs_result[cost_name] = summary
                    all_rows.extend(_episode_rows(episodes, period, variant, stop_pct, target_r,
                                                  cost_name, side_cost))
                variants[variant] = {
                    "stop_pct": stop_pct,
                    "target_r": target_r,
                    "costs": costs_result,
                    **_gate_result(costs_result["base"], costs_result["stress_2x"]),
                }

        periods_result[period] = {
            "start": start,
            "end_exclusive": end,
            "direction_and_windows_previously_examined": True,
            "historical_independent_confirmation": False,
            "frozen_decision_reconstruction": reconstruction,
            "variants": variants,
        }

    input_manifest_sha = _json_sha256(manifest)
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "frozen short-only low-volatility HGB entries with fixed daily OHLC exit brackets",
        "market": "Binance USD-M perpetual futures",
        "real_orders_sent": False,
        "external_data_fetch_attempted": False,
        "model_retrained": False,
        "current_gates": {
            "base_ev_pct_strictly_above": 1.2,
            "base_payoff_minimum": 1.0,
            "base_profit_factor_minimum": 1.25,
            "base_unique_complete_episodes_minimum": 200,
            "base_active_weeks_minimum": 8,
            "stress_2x_aggregate_portfolio_return_positive": True,
            "win_rate_near_70_pct_is_preference": True,
            "drawdown_has_no_fixed_cap": True,
        },
        "frozen_sources": {
            "source_report": str(SOURCE_REPORT.relative_to(ROOT)),
            "source_report_sha256": _sha256(SOURCE_REPORT),
            "source_ledger": str(SOURCE_LEDGER.relative_to(ROOT)),
            "source_ledger_sha256": source_ledger_sha,
            "upstream_ev_ledger_sha256": source_ev_ledger_sha,
            "source_analysis_code_sha256": source_code_sha,
            "protocol": str(PROTOCOL.relative_to(ROOT)),
            "protocol_sha256": _sha256(PROTOCOL),
            "current_analysis_code_sha256": _sha256(Path(__file__)),
            "source_manifest_entries": len(manifest),
            "source_manifest_sha256": input_manifest_sha,
            "selected_symbols": len(cohort["selected"]),
        },
        "cost_model": {
            "base_side_cost": BASE_SIDE_COST,
            "stress_2x_side_cost": STRESS_SIDE_COST,
            "legacy_source_stress_side_cost_for_exact_reconciliation_only": SOURCE_STRESS_SIDE_COST,
            "side_cost_semantics": "USD-M transaction friction proxy; 5 bps fee plus 5 bps adverse slippage per side at base, both doubled under current stress",
            "funding": "observed archived rates; adverse mark-price convention; on barrier-touch days, keep adverse payments and omit positive post-open credits",
        },
        "control_reconciliation": {
            "status": "PASS",
            "source_rows": len(control_reconciliation),
            "checks": control_reconciliation,
            "custom_engine_parity_rows": len(control_engine_parity),
            "custom_engine_parity": control_engine_parity,
        },
        "periods": periods_result,
        "limits": [
            "Short direction and all included historical windows were inspected before this exit experiment.",
            "Historical results are exploratory and do not count as independent confirmation.",
            "Daily OHLC does not reveal intraday barrier order; stop-first is assumed if both barriers touch.",
            "The adverse daily drawdown is a simultaneous OHLC upper bound, not a realized path.",
            "Costs are model assumptions, not verified account-specific commissions or fills.",
            "The replay does not model account-specific maintenance margin, liquidation, or exchange price protection.",
            "Prospective frozen paper evidence is required before any trading decision; no real order was sent.",
        ],
    }

    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8", newline="\n")
    csv_fields = [
        "period", "variant", "stop_pct", "target_r", "cost", "side_cost", "symbol", "direction",
        "entry_ms", "exit_ms", "entry_price", "exit_price", "stop_price", "target_price", "hold_days",
        "entry_notional", "price_pnl",
        "funding_pnl", "fees", "net_pnl", "net_return_pct_on_entry_notional", "exit_reason",
        "unresolved_proxy_exit",
    ]
    all_rows.sort(key=lambda row: (row["period"], row["variant"], row["cost"],
                                   int(row["entry_ms"]), row["symbol"], int(row["exit_ms"])))
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(all_rows)

    lines = [
        "# Resultado: stops e alvos no candidato short-only",
        "",
        "O replay usa somente as previsões e decisões semanais já gravadas; o HGB não foi retreinado. O controle sem barreiras reproduziu o relatório e o ledger short-only publicados antes do grid. Nenhuma chamada externa ou ordem real foi feita.",
        "",
        "O custo base combina 5 bps de taxa e 5 bps de slippage adverso por lado. O stress vigente dobra ambos para 20 bps por lado. O replay de origem usava 15 bps no stress; esse custo foi repetido somente para reconciliar aquele ledger. O motor não modela margem de manutenção, liquidação nem proteção de preço da corretora.",
        "",
        "| Período | Regra | N base | Acerto | Payoff | PF | EV/op. base | Retorno base | Retorno stress 2x | DD marcado | Limite adverso | Semanas | Gates numéricos |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    individual_periods = [period for period in EVALUATION_PERIODS if period != "combined"]
    max_individual_episodes = max(
        entry["costs"]["base"]["episodes"]
        for period in individual_periods
        for entry in periods_result[period]["variants"].values()
    )
    diagnostic_numeric_passes = [
        variant for variant, entry in periods_result["combined"]["variants"].items()
        if entry["passes_numeric_gates"]
    ]
    for period in EVALUATION_PERIODS:
        for variant, entry in periods_result[period]["variants"].items():
            base = entry["costs"]["base"]
            stress = entry["costs"]["stress_2x"]
            gates = ("diagnóstico" if period == "combined" else
                     "PASS numérico" if entry["passes_numeric_gates"] else "fail")
            lines.append(
                f"| {period} | {variant} | {base['episodes']} | "
                f"{_fmt(base['win_rate_pct'])} | {_fmt(base['net_payoff_ratio'], '')} | "
                f"{_fmt(base['profit_factor'], '')} | "
                f"{_fmt(base['ev_net_pct_per_episode_on_entry_notional'])} | "
                f"{_fmt(base['portfolio_replay']['return_pct'])} | "
                f"{_fmt(stress['portfolio_replay']['return_pct'])} | "
                f"{_fmt(base['portfolio_replay']['max_drawdown_pct'])} | "
                f"{_fmt(base['portfolio_replay']['max_adverse_daily_drawdown_pct'])} | "
                f"{base['active_weeks']} | {gates} |"
            )
    lines.extend([
        "",
        "## Leitura",
        "",
        f"Nenhuma regra passa os gates em uma janela individual. O maior fold tem {max_individual_episodes} operações; todas ficam abaixo das 200 exigidas. No combinado, apenas {', '.join(diagnostic_numeric_passes) if diagnostic_numeric_passes else 'nenhuma variante'} satisfaz os números, mas esse agregado é apenas diagnóstico e não pode ser usado para somar folds. A calibração H1/2025 tem EV-base negativo em todas as variantes. A direção e as janelas já foram observadas, então nenhum resultado histórico constitui confirmação independente.",
        "",
        "Conclusão: o grid não validou uma estratégia consistente. Os resultados justificam encerrar a seleção retrospectiva e, se a hipótese continuar relevante, congelar uma única regra para coleta prospectiva em paper. Não houve ordem real.",
        "",
        f"Reconciliação do controle: {len(control_reconciliation)} pares período/custo passaram no relatório e ledger de origem. Protocolo SHA-256 `{result['frozen_sources']['protocol_sha256']}`; código `{result['frozen_sources']['current_analysis_code_sha256']}`; ledger de episódios `results/{OUTPUT_CSV.name}`.",
        "",
    ])
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    compact = {
        "control_reconciliation_pairs": len(control_reconciliation),
        "periods": {
            period: {
                variant: {
                    "n": entry["costs"]["base"]["episodes"],
                    "ev_base_pct": entry["costs"]["base"]["ev_net_pct_per_episode_on_entry_notional"],
                    "return_base_pct": entry["costs"]["base"]["portfolio_replay"]["return_pct"],
                    "return_stress_2x_pct": entry["costs"]["stress_2x"]["portfolio_replay"]["return_pct"],
                    "passes_numeric_gates": entry["passes_numeric_gates"],
                }
                for variant, entry in periods_result[period]["variants"].items()
            }
            for period in EVALUATION_PERIODS
        },
        "outputs": [str(OUTPUT), str(OUTPUT_CSV), str(OUTPUT_MD)],
    }
    print(json.dumps(compact, indent=2, allow_nan=False), flush=True)
    return result


if __name__ == "__main__":
    _run()
