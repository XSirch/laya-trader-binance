"""Audit completed paper trades against the revised per-trade targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES_DIR = ROOT / "results" / "minute_jev_paper_20260927"
LEDGER = SERIES_DIR / "events.jsonl"
OUTPUT_JSON = SERIES_DIR / "target_metrics.json"
OUTPUT_MD = SERIES_DIR / "target_metrics.md"
SERIES = "minute_jev_paper_20260927"
WIN_RATE_TARGET = 0.70
MIN_PAYOFF = 1.0
IDEAL_PAYOFF = (1.2, 1.5)
EV_TARGET_PCT = 1.2
MAX_DRAWDOWN_PCT = 10.0
MIN_SCREEN_TRADES = 30
MIN_VALIDATION_TRADES = 100
FEE_RATE = 0.001
ZERO_SHA256 = "0" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _read_complete_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    raw = LEDGER.read_bytes()
    complete = raw.splitlines(keepends=True)
    if complete and not complete[-1].endswith((b"\n", b"\r")):
        complete.pop()
    rows: list[dict] = []
    previous = ZERO_SHA256
    for line in complete:
        row = json.loads(line)
        body = {key: value for key, value in row.items() if key != "record_sha256"}
        if body.get("previous_sha256") != previous:
            raise ValueError("trade ledger chain has a broken previous hash")
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        if digest != row.get("record_sha256"):
            raise ValueError("trade ledger record hash does not match")
        rows.append(row)
        previous = digest
    return rows


def _wilson_interval(wins: int, count: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    if count <= 0:
        return None
    rate = wins / count
    denom = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denom
    margin = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _block_bootstrap_ev(values: list[float], samples: int = 2_000) -> tuple[float, float] | None:
    if len(values) < 20:
        return None
    rng = random.Random(20260927)
    count = len(values)
    block = max(1, round(math.sqrt(count)))
    means: list[float] = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < count:
            start = rng.randrange(count)
            sample.extend(values[(start + offset) % count] for offset in range(block))
        means.append(math.fsum(sample[:count]) / count)
    means.sort()
    return means[math.floor(0.025 * (samples - 1))], means[math.ceil(0.975 * (samples - 1))]


def build_report() -> dict:
    rows = _read_complete_ledger()
    processed = [row for row in rows if row.get("record_type") == "minute_decision"
                 and row.get("status") == "processed" and row.get("jev")]
    account = processed[-1].get("account_after", {}) if processed else {}
    round_trips = account.get("round_trips", [])
    trade_returns: list[float] = []
    wins = losses = breakevens = 0
    winning_returns: list[float] = []
    losing_returns: list[float] = []
    for trade in round_trips:
        notional = float(trade["quantity"]) * float(trade["entry_price"])
        committed_capital = notional * (1 + FEE_RATE)
        net_pnl = float(trade["net_pnl_usdt"])
        if committed_capital <= 0 or not math.isfinite(net_pnl):
            raise ValueError("closed trade has invalid capital or net PnL")
        result_pct = 100 * net_pnl / committed_capital
        trade_returns.append(result_pct)
        if net_pnl > 0:
            wins += 1
            winning_returns.append(net_pnl)
        elif net_pnl < 0:
            losses += 1
            losing_returns.append(abs(net_pnl))
        else:
            breakevens += 1

    count = len(trade_returns)
    win_rate = wins / count if count else None
    mean_win = math.fsum(winning_returns) / len(winning_returns) if winning_returns else None
    mean_loss = math.fsum(losing_returns) / len(losing_returns) if losing_returns else None
    payoff = mean_win / mean_loss if mean_win is not None and mean_loss else None
    ev_pct = math.fsum(trade_returns) / count if count else None
    ev_interval = _block_bootstrap_ev(trade_returns)
    win_interval = _wilson_interval(wins, count)
    max_observed_dd = max((float(row.get("account_after", {}).get("max_drawdown_pct", 0.0))
                           for row in rows), default=0.0)
    max_adverse_dd = max((float(row.get("account_after", {}).get("max_adverse_drawdown_pct", 0.0))
                          for row in rows), default=0.0)
    max_dd = max(max_observed_dd, max_adverse_dd)

    numeric_checks = {
        "win_rate_at_least_70_pct": win_rate is not None and win_rate >= WIN_RATE_TARGET,
        "net_payoff_at_least_1_to_1": payoff is not None and payoff >= MIN_PAYOFF,
        "net_ev_above_1_2_pct_per_trade": ev_pct is not None and ev_pct > EV_TARGET_PCT,
        "max_drawdown_at_most_10_pct": max_dd <= MAX_DRAWDOWN_PCT,
    }
    screen_passed = count >= MIN_SCREEN_TRADES and all(numeric_checks.values())
    validation_sample_met = count >= MIN_VALIDATION_TRADES
    report = {
        "schema_version": 1,
        "series": SERIES,
        "mode": "paper",
        "ledger_records_verified": len(rows),
        "processed_minutes": len(processed),
        "closed_round_trips": count,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "win_rate_wilson_95_pct": [100 * value for value in win_interval] if win_interval else None,
        "average_winner_usdt": mean_win,
        "average_loser_usdt": mean_loss,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_trade_on_committed_capital": ev_pct,
        "ev_block_bootstrap_95_pct": list(ev_interval) if ev_interval else None,
        "max_observed_drawdown_pct": max_observed_dd,
        "max_adverse_drawdown_pct": max_adverse_dd,
        "max_drawdown_pct": max_dd,
        "targets": {
            "win_rate_minimum": WIN_RATE_TARGET,
            "payoff_minimum": MIN_PAYOFF,
            "payoff_ideal_range": list(IDEAL_PAYOFF),
            "ev_strictly_above_pct_per_trade": EV_TARGET_PCT,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "drawdown_target_retained_provisionally": True,
            "ev_basis": "mean net closed-trade PnL divided by capital committed at entry; fees and slippage included",
        },
        "checks": numeric_checks,
        "preliminary_screen_minimum_trades": MIN_SCREEN_TRADES,
        "preliminary_screen_passed": screen_passed,
        "validation_minimum_trades": MIN_VALIDATION_TRADES,
        "validation_sample_met": validation_sample_met,
        "targets_met_on_observed_sample": screen_passed,
        "full_goal_validated": False,
        "full_validation_reason": "one BTCUSDT Spot paper run of at most 72 hours does not establish consistency across regimes or pairs",
        "interpretation": (
            "insufficient_closed_trades" if count < MIN_SCREEN_TRADES else
            "preliminary_screen_passed_requires_more_validation" if screen_passed and not validation_sample_met else
            "targets_met_on_sample_but_validation_incomplete" if screen_passed else
            "preliminary_screen_failed"
        ),
        "live_orders_enabled": False,
    }
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                            encoding="utf-8")
    lines = [
        "# Métricas da meta por operação",
        "",
        f"Interpretação: **{report['interpretation']}**. Esta análise não altera o ledger congelado.",
        "",
        f"- Trades fechados: {count}; vitórias/derrotas/empates: {wins}/{losses}/{breakevens}.",
        f"- Taxa de acerto: {100 * win_rate:.2f}%" if win_rate is not None else "- Taxa de acerto: sem amostra.",
        f"- Payoff líquido: {payoff:.3f}:1" if payoff is not None else "- Payoff líquido: sem vitórias e derrotas suficientes.",
        f"- EV líquido por operação/capital alocado: {ev_pct:.3f}%" if ev_pct is not None else "- EV líquido por operação: sem amostra.",
        f"- Drawdown máximo observado/adverso: {max_observed_dd:.3f}% / {max_adverse_dd:.3f}%.",
        f"- Ledger: {len(rows)} registros verificados; cadeia SHA-256 íntegra.",
        "",
        "A triagem exige 30 operações fechadas. Cem operações são apenas um primeiro tamanho mínimo para revisar incerteza; esta série única não comprova consistência entre regimes ou pares.",
        "A meta de drawdown de 10% foi mantida provisoriamente. EV é calculado líquido sobre o capital comprometido em cada entrada.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    else:
        print(f"{report['interpretation']}: {report['closed_round_trips']} closed trades; "
              f"ledger verified={report['ledger_records_verified']}")


if __name__ == "__main__":
    main()
