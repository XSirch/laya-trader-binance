"""Replay a frozen weekday-only spot exposure rule on cached Binance klines."""

from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import platform
from statistics import median

from .binance_data import HOUR_MS, load_cached_range

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
FIRST_MONTH = "2023-01"
LAST_MONTH = "2026-08"
SIDE_COSTS = (0.0015, 0.0025)
INITIAL_EQUITY = 1.0
HOUR = HOUR_MS
DAY = 24 * HOUR

ROOT = Path.cwd()
DATA_ROOT = ROOT / "data" / "binance" / "spot" / "1h"
PROTOCOL_PATH = ROOT / "docs" / "calendar_seasonality_protocol_2026-09-27.md"
SOURCES_PATH = ROOT / "docs" / "calendar_strategy_sources_2026-09-27.md"
REPORT_PATH = ROOT / "docs" / "calendar_seasonality_research_2026-09-27.md"
JSON_PATH = ROOT / "results" / "calendar_seasonality_research.json"
CURVE_PATHS = {
    0.0015: ROOT / "results" / "calendar_seasonality_curves_0p15.csv",
    0.0025: ROOT / "results" / "calendar_seasonality_curves_0p25.csv",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def utc_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def read_verified_data() -> tuple[dict[str, list], list[dict], int, int, list[int]]:
    frames, manifest = load_cached_range(list(SYMBOLS), FIRST_MONTH, LAST_MONTH, DATA_ROOT)
    bars_by_symbol = {symbol: {bar.open_ms: bar for bar in bars}
                      for symbol, bars in frames.items()}
    common = set.intersection(*(set(bars) for bars in bars_by_symbol.values()))
    common_timestamps = sorted(common)
    if not common_timestamps:
        raise ValueError("the selected symbols have no common hourly timestamps")

    archive_gaps = []
    for row in manifest:
        for gap in row.get("gaps", []):
            archive_gaps.append({"symbol": row["symbol"], "month": row["month"], **gap})
    last_gap_boundary = max((row["before_open_ms"] for row in archive_gaps), default=0)

    start = None
    for timestamp in common_timestamps:
        stamp = utc_datetime(timestamp)
        if timestamp >= last_gap_boundary and stamp.weekday() == 0 and stamp.hour == 0:
            start = timestamp
            break
    if start is None:
        raise ValueError("no Monday 00:00 UTC boundary follows the last archived gap")

    end_candidates = []
    for timestamp in common_timestamps:
        if timestamp < start:
            continue
        stamp = utc_datetime(timestamp)
        if stamp.weekday() == 5 and stamp.hour == 0:
            end_candidates.append(timestamp)
    if not end_candidates:
        raise ValueError("no Saturday 00:00 UTC terminal boundary follows the start")
    end = end_candidates[-1]

    # Gaps before the first trade are documented and excluded. Any later gap
    # would make the exposure and adverse drawdown path incomplete.
    for symbol, bars in bars_by_symbol.items():
        for timestamp in range(start, end + HOUR, HOUR):
            if timestamp not in bars:
                raise ValueError(f"unresolved hourly data gap for {symbol} at {timestamp}")

    week_starts = []
    for timestamp in range(start, end + HOUR, 7 * DAY):
        stamp = utc_datetime(timestamp)
        if stamp.weekday() != 0 or stamp.hour != 0:
            raise ValueError("weekly schedule is not aligned to Monday 00:00 UTC")
        saturday = timestamp + 5 * DAY
        if saturday <= end:
            if any(timestamp not in bars_by_symbol[symbol]
                   or saturday not in bars_by_symbol[symbol] for symbol in SYMBOLS):
                raise ValueError("a weekly entry or exit boundary is missing")
            week_starts.append(timestamp)
    if not week_starts or week_starts[-1] + 5 * DAY != end:
        raise ValueError("the last complete candidate cycle does not end at the terminal Saturday")
    return bars_by_symbol, manifest, start, end, week_starts


def drawdown_pct(values: list[float]) -> float:
    peak = 0.0
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, 1.0 - value / peak)
    return 100.0 * maximum


def period_returns(timestamps: list[int], pre: list[float], post: list[float],
                   start: int, end: int) -> dict:
    by_time = {timestamp: index for index, timestamp in enumerate(timestamps)}
    start_dt = utc_datetime(start)
    end_dt = utc_datetime(end)
    annual = []
    for year in range(start_dt.year, end_dt.year + 1):
        left = datetime(year, 1, 1, tzinfo=timezone.utc)
        right = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        left_ms = int(left.timestamp() * 1000)
        right_ms = int(right.timestamp() * 1000)
        if year == start_dt.year:
            left_ms = start
            left_value = INITIAL_EQUITY
        else:
            left_value = pre[by_time[left_ms]] if left_ms in by_time else None
        if year == end_dt.year:
            right_ms = end
            right_value = post[by_time[right_ms]]
        else:
            right_value = pre[by_time[right_ms]] if right_ms in by_time else None
        if left_value is not None and right_value is not None:
            partial_start = year == start_dt.year and utc_datetime(left_ms).month != 1
            partial_end = year == end_dt.year and end_dt.month != 12
            annual.append({
                "period": f"{year} (parcial)" if partial_start or partial_end else str(year),
                "start_utc": utc_datetime(left_ms).isoformat(),
                "end_utc": utc_datetime(right_ms).isoformat(),
                "return_pct": 100.0 * (right_value / left_value - 1.0),
            })

    month_boundaries = []
    for index, timestamp in enumerate(timestamps):
        stamp = utc_datetime(timestamp)
        if stamp.day == 1 and stamp.hour == 0 and timestamp >= start:
            month_boundaries.append((stamp.year, stamp.month, pre[index]))
    monthly = []
    for current, following in zip(month_boundaries, month_boundaries[1:]):
        year, month, left_value = current
        next_year, next_month, right_value = following
        expected_next = (year + 1, 1) if month == 12 else (year, month + 1)
        if expected_next != (next_year, next_month):
            continue
        monthly.append({"month": f"{year:04d}-{month:02d}",
                        "return_pct": 100.0 * (right_value / left_value - 1.0)})
    return {"annual": annual, "monthly": monthly,
            "positive_full_months": sum(row["return_pct"] > 0 for row in monthly),
            "full_month_count": len(monthly),
            "positive_full_month_share_pct":
                100.0 * sum(row["return_pct"] > 0 for row in monthly) / len(monthly)
                if monthly else 0.0,
            "longest_losing_month_streak": longest_losing_streak(monthly)}


def longest_losing_streak(monthly: list[dict]) -> int:
    longest = current = 0
    for row in monthly:
        if row["return_pct"] < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def simulate_cost(bars_by_symbol: dict[str, dict], start: int, end: int,
                  week_starts: list[int], side_cost: float) -> dict:
    timestamps = list(range(start, end + HOUR, HOUR))
    candidate_pre_by_symbol = {}
    candidate_post_by_symbol = {}
    candidate_low_by_symbol = {}
    benchmark_pre_by_symbol = {}
    benchmark_post_by_symbol = {}
    benchmark_low_by_symbol = {}
    candidate_fees = candidate_turnover = 0.0
    benchmark_fees = benchmark_turnover = 0.0
    candidate_sides = benchmark_sides = 0
    fills = []
    weekend = {symbol: [] for symbol in SYMBOLS}
    weekday = {symbol: [] for symbol in SYMBOLS}
    candidate_asset_summary = {}

    for symbol in SYMBOLS:
        bars = bars_by_symbol[symbol]
        cash = INITIAL_EQUITY / len(SYMBOLS)
        quantity = 0.0
        benchmark_cash = INITIAL_EQUITY / len(SYMBOLS)
        benchmark_quantity = 0.0
        pre_path = []
        post_path = []
        low_path = []
        adverse_trace = [INITIAL_EQUITY / len(SYMBOLS)]
        benchmark_pre = []
        benchmark_post = []
        benchmark_low = []
        asset_fees = asset_turnover = 0.0
        asset_sides = 0

        for timestamp in timestamps:
            bar = bars[timestamp]
            dt = utc_datetime(timestamp)
            pre_equity = cash + quantity * bar.open
            benchmark_pre_equity = benchmark_cash + benchmark_quantity * bar.open
            pre_path.append(pre_equity)
            benchmark_pre.append(benchmark_pre_equity)
            adverse_trace.append(pre_equity)

            if timestamp in week_starts:
                notional = cash / (1.0 + side_cost)
                fee = notional * side_cost
                quantity = notional / bar.open
                cash = 0.0
                fills.append({"strategy": "calendar_weekdays", "symbol": symbol,
                    "timestamp_utc": utc_datetime(timestamp).isoformat(), "side": "BUY",
                    "price": bar.open, "quantity": quantity, "quote_notional": notional,
                    "fee_quote": fee, "cash_after": cash, "quantity_after": quantity})
                candidate_fees += fee
                candidate_turnover += notional
                candidate_sides += 1
                asset_fees += fee
                asset_turnover += notional
                asset_sides += 1
            if dt.weekday() == 5 and dt.hour == 0 and quantity > 0:
                notional = quantity * bar.open
                fee = notional * side_cost
                cash = notional - fee
                fills.append({"strategy": "calendar_weekdays", "symbol": symbol,
                    "timestamp_utc": utc_datetime(timestamp).isoformat(), "side": "SELL",
                    "price": bar.open, "quantity": quantity, "quote_notional": notional,
                    "fee_quote": fee, "cash_after": cash, "quantity_after": 0.0})
                quantity = 0.0
                candidate_fees += fee
                candidate_turnover += notional
                candidate_sides += 1
                asset_fees += fee
                asset_turnover += notional
                asset_sides += 1

            if timestamp == start:
                notional = benchmark_cash / (1.0 + side_cost)
                fee = notional * side_cost
                benchmark_quantity = notional / bar.open
                benchmark_cash = 0.0
                fills.append({"strategy": "buy_and_hold", "symbol": symbol,
                    "timestamp_utc": utc_datetime(timestamp).isoformat(), "side": "BUY",
                    "price": bar.open, "quantity": benchmark_quantity,
                    "quote_notional": notional, "fee_quote": fee,
                    "cash_after": benchmark_cash, "quantity_after": benchmark_quantity})
                benchmark_fees += fee
                benchmark_turnover += notional
                benchmark_sides += 1
            if timestamp == end:
                notional = benchmark_quantity * bar.open
                fee = notional * side_cost
                benchmark_cash = notional - fee
                fills.append({"strategy": "buy_and_hold", "symbol": symbol,
                    "timestamp_utc": utc_datetime(timestamp).isoformat(), "side": "SELL",
                    "price": bar.open, "quantity": benchmark_quantity,
                    "quote_notional": notional, "fee_quote": fee,
                    "cash_after": benchmark_cash, "quantity_after": 0.0})
                benchmark_quantity = 0.0
                benchmark_fees += fee
                benchmark_turnover += notional
                benchmark_sides += 1

            candidate_value = cash + quantity * bar.open
            candidate_low_value = cash + quantity * bar.low
            benchmark_value = benchmark_cash + benchmark_quantity * bar.open
            benchmark_low_value = benchmark_cash + benchmark_quantity * bar.low
            post_path.append(candidate_value)
            low_path.append(candidate_low_value)
            benchmark_post.append(benchmark_value)
            benchmark_low.append(benchmark_low_value)
            adverse_trace.extend((candidate_value, candidate_low_value))

        candidate_pre_by_symbol[symbol] = pre_path
        candidate_post_by_symbol[symbol] = post_path
        candidate_low_by_symbol[symbol] = low_path
        benchmark_pre_by_symbol[symbol] = benchmark_pre
        benchmark_post_by_symbol[symbol] = benchmark_post
        benchmark_low_by_symbol[symbol] = benchmark_low
        candidate_asset_summary[symbol] = {
            "initial_allocation_pct": 100.0 / len(SYMBOLS),
            "ending_equity": post_path[-1],
            "return_pct_on_initial_asset_sleeve":
                100.0 * (post_path[-1] / (INITIAL_EQUITY / len(SYMBOLS)) - 1.0),
            "max_drawdown_open_pct": drawdown_pct([INITIAL_EQUITY / len(SYMBOLS)] +
                [value for pair in zip(pre_path, post_path) for value in pair]),
            "adverse_intrahour_drawdown_bound_pct": drawdown_pct(adverse_trace),
            "fees_paid": asset_fees,
            "quote_turnover": asset_turnover,
            "trade_sides": asset_sides,
        }

        for monday in week_starts:
            saturday = monday + 5 * DAY
            next_monday = monday + 7 * DAY
            monday_open = bars[monday].open
            saturday_open = bars[saturday].open
            weekend_return = bars[next_monday].open / saturday_open - 1.0 \
                if next_monday in bars else None
            weekday_return = saturday_open / monday_open - 1.0
            weekday[symbol].append(weekday_return)
            if weekend_return is not None:
                weekend[symbol].append(weekend_return)

    def sum_paths(paths: dict[str, list[float]]) -> list[float]:
        return [sum(paths[symbol][index] for symbol in SYMBOLS)
                for index in range(len(timestamps))]

    candidate_pre = sum_paths(candidate_pre_by_symbol)
    candidate_post = sum_paths(candidate_post_by_symbol)
    candidate_low = sum_paths(candidate_low_by_symbol)
    benchmark_pre = sum_paths(benchmark_pre_by_symbol)
    benchmark_post = sum_paths(benchmark_post_by_symbol)
    benchmark_low = sum_paths(benchmark_low_by_symbol)

    elapsed_years = (end - start) / (365.2425 * DAY)
    def strategy_metrics(pre: list[float], post: list[float], adverse_trace: list[float],
                         fees: float, turnover: float, sides: int) -> dict:
        final_equity = post[-1]
        return {
            "ending_equity": final_equity,
            "net_return_pct": 100.0 * (final_equity / INITIAL_EQUITY - 1.0),
            "cagr_pct": 100.0 * ((final_equity / INITIAL_EQUITY) **
                                  (1.0 / elapsed_years) - 1.0),
            "max_drawdown_open_pct": drawdown_pct(
                [INITIAL_EQUITY] + [value for pair in zip(pre, post) for value in pair]),
            "adverse_intrahour_drawdown_bound_pct": drawdown_pct(adverse_trace),
            "fees_paid": fees,
            "fees_pct_of_initial_equity": 100.0 * fees / INITIAL_EQUITY,
            "quote_turnover": turnover,
            "trade_sides": sides,
            **period_returns(timestamps, pre, post, start, end),
        }

    candidate_adverse_trace = [INITIAL_EQUITY]
    benchmark_adverse_trace = [INITIAL_EQUITY]
    for index in range(len(timestamps)):
        candidate_adverse_trace.extend((candidate_pre[index], candidate_post[index], candidate_low[index]))
        benchmark_adverse_trace.extend((benchmark_pre[index], benchmark_post[index], benchmark_low[index]))

    candidate_metrics = strategy_metrics(candidate_pre, candidate_post, candidate_adverse_trace,
                                         candidate_fees, candidate_turnover, candidate_sides)
    benchmark_metrics = strategy_metrics(benchmark_pre, benchmark_post, benchmark_adverse_trace,
                                         benchmark_fees, benchmark_turnover, benchmark_sides)

    index_by_time = {timestamp: index for index, timestamp in enumerate(timestamps)}
    weekly_ledger = []
    candidate_week_returns = []
    benchmark_week_returns = []
    for monday in week_starts:
        saturday = monday + 5 * DAY
        monday_index = index_by_time[monday]
        saturday_index = index_by_time[saturday]
        candidate_return = candidate_post[saturday_index] / candidate_pre[monday_index] - 1.0
        benchmark_return = benchmark_post[saturday_index] / benchmark_pre[monday_index] - 1.0
        candidate_week_returns.append(candidate_return)
        benchmark_week_returns.append(benchmark_return)
        weekly_ledger.append({
            "monday_utc": utc_datetime(monday).isoformat(),
            "saturday_utc": utc_datetime(saturday).isoformat(),
            "candidate_net_return_pct": 100.0 * candidate_return,
            "buy_and_hold_net_return_pct": 100.0 * benchmark_return,
            "active_return_pct": 100.0 * (candidate_return - benchmark_return),
        })
    candidate_metrics.update({
        "positive_weeks": sum(value > 0 for value in candidate_week_returns),
        "complete_week_count": len(candidate_week_returns),
        "positive_week_share_pct": 100.0 * sum(value > 0 for value in candidate_week_returns) /
            len(candidate_week_returns),
        "longest_losing_week_streak": longest_losing_streak(
            [{"return_pct": 100.0 * value} for value in candidate_week_returns]),
    })
    benchmark_metrics.update({
        "positive_weeks": sum(value > 0 for value in benchmark_week_returns),
        "complete_week_count": len(benchmark_week_returns),
        "positive_week_share_pct": 100.0 * sum(value > 0 for value in benchmark_week_returns) /
            len(benchmark_week_returns),
        "longest_losing_week_streak": longest_losing_streak(
            [{"return_pct": 100.0 * value} for value in benchmark_week_returns]),
    })

    weekend_summary = {}
    for symbol in SYMBOLS:
        weekend_values = weekend[symbol]
        weekday_values = weekday[symbol]
        weekend_summary[symbol] = {
            "complete_weekend_observations": len(weekend_values),
            "weekend_mean_return_pct": 100.0 * sum(weekend_values) / len(weekend_values)
                if weekend_values else None,
            "weekend_median_return_pct": 100.0 * median(weekend_values)
                if weekend_values else None,
            "weekend_positive_share_pct": 100.0 * sum(value > 0 for value in weekend_values) /
                len(weekend_values) if weekend_values else None,
            "weekday_mon_sat_mean_return_pct": 100.0 * sum(weekday_values) / len(weekday_values)
                if weekday_values else None,
            "weekend_gross_returns_pct": [100.0 * value for value in weekend_values],
            "weekday_gross_returns_pct": [100.0 * value for value in weekday_values],
        }

    curve_path = CURVE_PATHS[side_cost]
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["timestamp_utc", "candidate_pre", "candidate_post", "candidate_adverse_low",
               "buy_and_hold_pre", "buy_and_hold_post", "buy_and_hold_adverse_low"]
    for symbol in SYMBOLS:
        columns.extend((f"candidate_{symbol}_pre", f"candidate_{symbol}_post",
                        f"candidate_{symbol}_adverse_low", f"buy_and_hold_{symbol}_pre",
                        f"buy_and_hold_{symbol}_post", f"buy_and_hold_{symbol}_adverse_low"))
    with curve_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for index, timestamp in enumerate(timestamps):
            record = {
                "timestamp_utc": utc_datetime(timestamp).isoformat(),
                "candidate_pre": candidate_pre[index],
                "candidate_post": candidate_post[index],
                "candidate_adverse_low": candidate_low[index],
                "buy_and_hold_pre": benchmark_pre[index],
                "buy_and_hold_post": benchmark_post[index],
                "buy_and_hold_adverse_low": benchmark_low[index],
            }
            for symbol in SYMBOLS:
                record.update({
                    f"candidate_{symbol}_pre": candidate_pre_by_symbol[symbol][index],
                    f"candidate_{symbol}_post": candidate_post_by_symbol[symbol][index],
                    f"candidate_{symbol}_adverse_low": candidate_low_by_symbol[symbol][index],
                    f"buy_and_hold_{symbol}_pre": benchmark_pre_by_symbol[symbol][index],
                    f"buy_and_hold_{symbol}_post": benchmark_post_by_symbol[symbol][index],
                    f"buy_and_hold_{symbol}_adverse_low": benchmark_low_by_symbol[symbol][index],
                })
            writer.writerow(record)
    curve_artifact = {"path": curve_path.relative_to(ROOT).as_posix(),
                      "sha256": sha256(curve_path.read_bytes()),
                      "rows": len(timestamps), "columns": columns}

    fills.sort(key=lambda row: (row["timestamp_utc"], row["symbol"],
                               row["strategy"], row["side"]))
    return {
        "side_cost": side_cost,
        "candidate": candidate_metrics,
        "buy_and_hold": benchmark_metrics,
        "candidate_assets": candidate_asset_summary,
        "fills": fills,
        "weekly_ledger": weekly_ledger,
        "equity_curve_csv": curve_artifact,
        "weekend_observations": weekend_summary,
        "terminal_equity_ratio_vs_buy_and_hold_pct":
            100.0 * (candidate_post[-1] / benchmark_post[-1] - 1.0),
        "gate_pass": candidate_metrics["cagr_pct"] >= 50.0 and
                     candidate_metrics["adverse_intrahour_drawdown_bound_pct"] <= 10.0,
    }


def pct(value: float | None, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return "n/d"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def render_report(payload: dict) -> str:
    lines = [
        "# Replay exploratório: exposição Spot apenas durante a semana",
        "",
        f"Execução: {payload['run_utc']} UTC. Período de operações: "
        f"{payload['period']['start_utc']} a {payload['period']['end_utc']}.",
        "",
        "## Resultado",
        "",
        "A regra fixa não atingiu o gate local em nenhum custo. O replay cobra compras e "
        "vendas em cada semana e não inclui spread ou slippage; todo o histórico já havia "
        "sido visto em pesquisas anteriores, portanto os números são exploratórios.",
        "",
        "| Custo por lado | Regra: CAGR / retorno / DD horário / limite adverso | "
        "Buy-and-hold: CAGR / retorno / DD horário | Diferença final | Gate |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in payload["scenarios"]:
        candidate = row["candidate"]
        benchmark = row["buy_and_hold"]
        lines.append(
            f"| {row['side_cost'] * 100:.2f}% | "
            f"{pct(candidate['cagr_pct'])} / {pct(candidate['net_return_pct'])} / "
            f"{pct(candidate['max_drawdown_open_pct'], signed=False)} / "
            f"{pct(candidate['adverse_intrahour_drawdown_bound_pct'], signed=False)} | "
            f"{pct(benchmark['cagr_pct'])} / {pct(benchmark['net_return_pct'])} / "
            f"{pct(benchmark['max_drawdown_open_pct'], signed=False)} | "
            f"{pct(row['terminal_equity_ratio_vs_buy_and_hold_pct'])} | "
            f"{'sim' if row['gate_pass'] else 'não'} |"
        )

    lines += ["", "## Resultados anuais por custo", "",
              "Os anos inicial e final são parciais. CAGR e retornos são líquidos das "
              "taxas simuladas.", "", "| Custo | Conta | Ano | Retorno |", "|---:|---|---:|---:|"]
    for row in payload["scenarios"]:
        for name, label in (("candidate", "Regra"), ("buy_and_hold", "Buy-and-hold")):
            for annual in row[name]["annual"]:
                lines.append(f"| {row['side_cost'] * 100:.2f}% | {label} | "
                             f"{annual['period']} | {pct(annual['return_pct'])} |")

    lines += ["", "## Comparação por ativo", "", "Custo por lado conforme o título da tabela. "
              "Cada sleeve começa com 25% do capital total.", ""]
    for row in payload["scenarios"]:
        lines += [f"### {row['side_cost'] * 100:.2f}% por lado", "",
                  "| Ativo | Regra: retorno da parcela | DD horário | Limite adverso | "
                  "Fim de semana médio bruto | Fins de semana positivos |",
                  "|---|---:|---:|---:|---:|---:|"]
        for symbol in SYMBOLS:
            asset = row["candidate_assets"][symbol]
            market = row["weekend_observations"][symbol]
            lines.append(
                f"| {symbol} | {pct(asset['return_pct_on_initial_asset_sleeve'])} | "
                f"{pct(asset['max_drawdown_open_pct'], signed=False)} | "
                f"{pct(asset['adverse_intrahour_drawdown_bound_pct'], signed=False)} | "
                f"{pct(market['weekend_mean_return_pct'])} | "
                f"{market['weekend_positive_share_pct']:.1f}% "
                f"({market['complete_weekend_observations']}) |"
            )

    lines += ["", "## Custos e consistência", "",
              f"- Semanas completas negociadas: **{payload['period']['complete_weeks']}**.",
              f"- Exposição planejada: **{payload['period']['planned_time_exposure_pct']:.2f}%** do tempo.",
              f"- Semanas positivas no custo base: "
              f"**{payload['scenarios'][0]['candidate']['positive_weeks']} de "
              f"{payload['scenarios'][0]['candidate']['complete_week_count']}** "
              f"({payload['scenarios'][0]['candidate']['positive_week_share_pct']:.1f}%); "
              f"sequência perdedora mais longa: "
              f"**{payload['scenarios'][0]['candidate']['longest_losing_week_streak']} semanas**.",
              f"- Execuções simuladas por custo: **{payload['scenarios'][0]['candidate']['trade_sides']} "
              "lados de ordem** na carteira; cada lado representa uma conta em um ativo.",
              f"- Custos pagos / giro de cotações no cenário base: "
              f"**{payload['scenarios'][0]['candidate']['fees_paid']:.6f} / "
              f"{payload['scenarios'][0]['candidate']['quote_turnover']:.6f}** unidades "
              "sobre capital inicial 1.",
              f"- Meses completos positivos no custo base: "
              f"**{payload['scenarios'][0]['candidate']['positive_full_months']} de "
              f"{payload['scenarios'][0]['candidate']['full_month_count']}**; sequência "
              f"perdedora mais longa: **{payload['scenarios'][0]['candidate']['longest_losing_month_streak']} meses**.",
              "- O limite adverso aplica as mínimas de cada candle enquanto há posição. "
              "É uma estimativa conservadora de marcação, não um fill ou caminho intrabar provado.",
              "- A regra usa somente o calendário. Não há ajuste ML: cerca de 180 fins de semana "
              "não justificam pesquisar combinações ou treinar um gate sem multiplicar a seleção.",
              "", "## Dados e reprodutibilidade", "",
              f"- Arquivos Binance mensais conferidos pelo manifesto: **{payload['data']['archive_count']}**.",
              f"- Horários comuns: **{payload['data']['common_timestamp_count']}**; lacunas arquivadas antes do início: **{len(payload['data']['excluded_gaps'])}**.",
              f"- Símbolos: {', '.join(SYMBOLS)}; candles de 1h em UTC.",
              f"- Identidade agregada dos arquivos: `{payload['data']['archive_identity_sha256']}`.",
              f"- Hash do código: `{payload['source_hashes']['script']}`.",
              f"- Hash do protocolo: `{payload['source_hashes']['protocol']}`.",
              f"- Hash das fontes: `{payload['source_hashes']['sources']}`.",
              "- Ledger de cada fill e retornos por ciclo semanal preservados no JSON; "
              "curvas horárias totais e por ativo estão nos CSVs referenciados no JSON.",
              "- Nenhuma ordem real, chamada JEV, download ou teste de software foi executado.",
              "", "## Conclusão", "",
              "A hipótese não é aprovada. Uma diferença histórica favorável, se presente, "
              "não demonstraria que o efeito continua existindo: calendário, custos reais, "
              "spread e slippage precisam ser observados prospectivamente antes de qualquer "
              "decisão de trading. Não use este replay para autorizar capital real.", ""]
    return "\n".join(lines)


def main() -> None:
    bars_by_symbol, manifest, start, end, week_starts = read_verified_data()
    timestamps = list(range(start, end + HOUR, HOUR))
    common_count = len(set.intersection(*(set(bars) for bars in bars_by_symbol.values())))
    gaps = []
    for row in manifest:
        for gap in row.get("gaps", []):
            if gap["before_open_ms"] <= start:
                gaps.append({"symbol": row["symbol"], "month": row["month"], **gap})
    archive_identity = [{"symbol": row["symbol"], "month": row["month"],
                         "sha256": row["sha256"], "bytes": row["bytes"],
                         "rows": row.get("rows"), "gaps": row.get("gaps", [])}
                        for row in sorted(manifest, key=lambda item: (item["symbol"], item["month"]))]
    identity_digest = sha256(json.dumps(archive_identity, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8"))
    source_hashes = {
        "script": sha256(Path(__file__).read_bytes()),
        "protocol": sha256(PROTOCOL_PATH.read_bytes()),
        "sources": sha256(SOURCES_PATH.read_bytes()),
        "binance_data": sha256((ROOT / "src" / "jev_trader" / "binance_data.py").read_bytes()),
    }
    scenarios = [simulate_cost(bars_by_symbol, start, end, week_starts, cost)
                 for cost in SIDE_COSTS]
    payload = {
        "schema_version": 1,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "symbols": list(SYMBOLS),
        "rule": "buy Monday 00:00 UTC; sell Saturday 00:00 UTC; cash over weekend",
        "period": {"start_utc": utc_datetime(start).isoformat(),
                   "end_utc": utc_datetime(end).isoformat(),
                   "elapsed_years": (end - start) / (365.2425 * DAY),
                   "complete_weeks": len(week_starts),
                   "planned_time_exposure_pct": 100.0 * (5.0 / 7.0)},
        "data": {"archive_count": len(manifest), "common_timestamp_count": common_count,
                 "excluded_gaps": gaps, "archive_identity": archive_identity,
                 "archive_identity_sha256": identity_digest,
                 "source": "local Binance monthly public Spot 1h archives",
                 "downloads": 0},
        "costs_side": list(SIDE_COSTS),
        "gate": {"target_cagr_pct": 50.0, "maximum_adverse_drawdown_pct": 10.0,
                 "passed_both_costs": all(row["gate_pass"] for row in scenarios)},
        "source_hashes": source_hashes,
        "scenarios": scenarios,
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8", newline="\n")
    payload["report_sha256"] = sha256(REPORT_PATH.read_bytes())
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    print(json.dumps({"report": str(REPORT_PATH), "json": str(JSON_PATH),
                      "period": payload["period"], "gate": payload["gate"],
                      "scenarios": [{"side_cost": row["side_cost"],
                                     "candidate": row["candidate"],
                                     "buy_and_hold": row["buy_and_hold"],
                                     "gate_pass": row["gate_pass"]}
                                    for row in scenarios]}, indent=2))


if __name__ == "__main__":
    main()
