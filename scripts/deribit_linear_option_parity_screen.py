"""Read-only linear option/future parity screen under a frozen protocol."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from binance_dec26_forward_quote import ROOT, read_public, utc_now
from deribit_usdc_delivery_universe_screen import API, result
from okx_usdm_delivery_universe_screen import book_cash, round_step


PROTOCOL = "docs/deribit_linear_option_parity_protocol.md"
REPORT = ROOT / "outputs/deribit_linear_option_parity.json"
BASES = ("BTC", "ETH")
EXPIRIES = ("30OCT26", "25DEC26")
TARGETS = (1000, 2000)
STRIKES_PER_GROUP = 3
OPTION_TAKER = Decimal("0.0003")
FUTURE_TAKER = Decimal("0.00035")
OPTION_DELIVERY = Decimal("0.00015")
FUTURE_DELIVERY = Decimal("0.00025")
EXECUTION_STRESS = Decimal("0.0025")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("1.25")
MIN_ANNUALIZED_RETURN = Decimal("0.04")


def select_strikes(options: list[dict], base: str, expiry: str,
                   index: Decimal) -> list[tuple[Decimal, dict, dict]]:
    matched: dict[Decimal, dict[str, dict]] = {}
    prefix = f"{base}_USDC-{expiry}-"
    for option in options:
        if (option.get("instrument_name", "").startswith(prefix)
                and option.get("is_active") and option.get("kind") == "option"
                and option.get("instrument_type") == "linear"
                and option.get("settlement_currency") == "USDC"
                and option.get("base_currency") == base):
            strike = Decimal(str(option["strike"]))
            matched.setdefault(strike, {})[option.get("option_type", "")] = option
    pairs = [(strike, sides["call"], sides["put"])
             for strike, sides in matched.items()
             if "call" in sides and "put" in sides]
    return sorted(pairs, key=lambda pair: (abs(pair[0] - index), pair[0]))[:STRIKES_PER_GROUP]


def evaluate(strike: Decimal, call: dict, put: dict, future: dict,
             index: Decimal, reads: dict) -> dict:
    row = {"strike": str(strike), "call": call["instrument_name"],
           "put": put["instrument_name"], "future": future["instrument_name"],
           "directions": {}, "passing_directions": []}
    if any(read.get("status") != "ok" for read in reads.values()):
        row["status"] = "required public request failed"
        return row
    if (not future.get("is_active") or future.get("kind") != "future"
            or future.get("settlement_currency") != "USDC"
            or future.get("instrument_type") != "linear"
            or call.get("expiration_timestamp") != put.get("expiration_timestamp")
            or call.get("expiration_timestamp") != future.get("expiration_timestamp")):
        row["status"] = "instrument metadata mismatch"
        return row
    books = {key: result(value) for key, value in reads.items() if key != "clock"}
    server_ms = int(result(reads["clock"]))
    ages = {key: (server_ms - int(book["timestamp"])) / 1000
            for key, book in books.items()}
    received = [datetime.fromisoformat(reads[key]["received_utc"])
                for key in ("call", "put", "future")]
    offset = (max(received) - min(received)).total_seconds()
    timely = all(0 <= age <= 10 for age in ages.values()) and offset <= 5
    row.update({"status": "evaluated", "book_ages_seconds": ages,
                "receive_span_seconds": offset, "timely": timely})
    if any(book.get("state") != "open" for book in books.values()):
        row["status"] = "book not open"
        return row
    if not all(books[leg].get(side) for leg in books for side in ("asks", "bids")):
        row["status"] = "required book side empty"
        return row
    days = (Decimal(int(future["expiration_timestamp"])) - Decimal(server_ms)) / Decimal(86_400_000)
    if days <= 0 or index <= 0:
        row["status"] = "invalid index or expiry"
        return row
    row["days_to_expiry"] = float(days)
    row["index_price"] = float(index)
    step = max(Decimal(str(call["min_trade_amount"])),
               Decimal(str(put["min_trade_amount"])))
    future_min = Decimal(str(future["min_trade_amount"]))
    configurations = {
        "short_call_long_put_long_future": (("call", "bids"), ("put", "asks"), ("future", "asks")),
        "long_call_short_put_short_future": (("call", "asks"), ("put", "bids"), ("future", "bids")),
    }
    for name, legs in configurations.items():
        size_rows = []
        for target in TARGETS:
            quantity = round_step(Decimal(target) / index, step, ROUND_DOWN)
            size_row = {"intended_notional": target, "quantity": str(quantity),
                        "qualifies": False}
            if quantity < step or quantity < future_min:
                size_row["status"] = "below exchange minimum"
            else:
                cash = {}
                visible = {}
                for leg, side in legs:
                    cash[leg], visible[leg] = book_cash(books[leg][side], quantity, Decimal(1))
                size_row["visible_coin"] = {leg: str(amount) for leg, amount in visible.items()}
                if any(value is None for value in cash.values()):
                    size_row["status"] = "insufficient displayed entry depth"
                else:
                    if name.startswith("short_call"):
                        gross = quantity * strike - cash["future"] + cash["call"] - cash["put"]
                        premium_paid = max(cash["put"] - cash["call"], Decimal(0))
                    else:
                        gross = cash["future"] - quantity * strike + cash["put"] - cash["call"]
                        premium_paid = max(cash["call"] - cash["put"], Decimal(0))
                    fee_reference = max(index * quantity, strike * quantity, cash["future"])
                    fees = fee_reference * (2 * OPTION_TAKER + FUTURE_TAKER
                                            + 2 * OPTION_DELIVERY + FUTURE_DELIVERY
                                            + EXECUTION_STRESS)
                    capital = CAPITAL_MULTIPLE * index * quantity + premium_paid
                    capital_charge = ANNUAL_CAPITAL_CHARGE * capital * days / 365
                    net = gross - fees - capital_charge
                    annualized = net / capital * 365 / days
                    size_row.update({"status": "conditional entry quote only",
                                     "entry_cash": {leg: float(value) for leg, value in cash.items()},
                                     "gross_cash": float(gross), "fees_and_stress": float(fees),
                                     "capital_charge": float(capital_charge),
                                     "reserved_capital": float(capital),
                                     "conditional_net_cash": float(net),
                                     "annualized_conditional_return": float(annualized),
                                     "qualifies": timely and net > 0
                                     and annualized >= MIN_ANNUALIZED_RETURN})
            size_rows.append(size_row)
        row["directions"][name] = size_rows
        if all(size_row["qualifies"] for size_row in size_rows):
            row["passing_directions"].append(name)
    return row


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "started_utc": utc_now(), "bases": BASES, "expiries": EXPIRIES,
              "targets": TARGETS, "strikes_per_group": STRIKES_PER_GROUP,
              "cost_assumptions": {"option_taker": str(OPTION_TAKER),
                                   "future_taker": str(FUTURE_TAKER),
                                   "option_delivery": str(OPTION_DELIVERY),
                                   "future_delivery": str(FUTURE_DELIVERY),
                                   "execution_stress": str(EXECUTION_STRESS),
                                   "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
                                   "capital_multiple": str(CAPITAL_MULTIPLE),
                                   "minimum_annualized_return": str(MIN_ANNUALIZED_RETURN)},
              "metadata": {}, "sources": {}, "results": {},
              "limits": "Public three-leg quotes only; no fills, account margin or orders"}
    try:
        metadata_options = read_public(API, "/api/v2/public/get_instruments",
                                       {"currency": "USDC", "kind": "option", "expired": "false"})
        metadata_futures = read_public(API, "/api/v2/public/get_instruments",
                                       {"currency": "USDC", "kind": "future", "expired": "false"})
        report["metadata"] = {"options": metadata_options, "futures": metadata_futures}
        options, futures = result(metadata_options), result(metadata_futures)
        for base in BASES:
            index_read = read_public(API, "/api/v2/public/get_index_price",
                                     {"index_name": f"{base.lower()}_usdc"})
            report["sources"][base] = {"index": index_read}
            try:
                index = Decimal(str(result(index_read)["index_price"]))
            except (ValueError, TypeError, KeyError) as error:
                for expiry in EXPIRIES:
                    report["results"][f"{base}-{expiry}"] = {"status": "index error",
                                                              "reason": str(error)}
                continue
            for expiry in EXPIRIES:
                group = f"{base}-{expiry}"
                selected = select_strikes(options, base, expiry, index)
                symbol = f"{base}_USDC-{expiry}"
                future = next((item for item in futures if item.get("instrument_name") == symbol), {})
                report["results"][group] = {"index": float(index),
                                            "selected_strikes": [str(s) for s, _, _ in selected],
                                            "pairs": []}
                if len(selected) != STRIKES_PER_GROUP or not future:
                    report["results"][group]["status"] = "missing required option pairs or future"
                    continue
                for strike, call, put in selected:
                    names = {"call": call["instrument_name"], "put": put["instrument_name"],
                             "future": symbol}
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        pending = {leg: pool.submit(read_public, API,
                                    "/api/v2/public/get_order_book",
                                    {"instrument_name": name, "depth": 100})
                                   for leg, name in names.items()}
                        reads = {leg: task.result() for leg, task in pending.items()}
                    reads["clock"] = read_public(API, "/api/v2/public/get_time")
                    report["sources"][f"{group}-{strike}"] = reads
                    try:
                        row = evaluate(strike, call, put, future, index, reads)
                    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
                        row = {"strike": str(strike), "status": "evaluation error",
                               "reason": str(error), "passing_directions": []}
                    report["results"][group]["pairs"].append(row)
                    print(group, strike, row["status"], row.get("passing_directions"), flush=True)
        report["passing_cases"] = [
            {"group": group, "strike": pair["strike"], "direction": direction}
            for group, value in report["results"].items()
            for pair in value.get("pairs", [])
            for direction in pair.get("passing_directions", [])]
    except (ValueError, TypeError, KeyError) as error:
        report["error"] = str(error)
    finally:
        report["finished_utc"] = utc_now()
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("saved", REPORT, "passing", report.get("passing_cases"), flush=True)


if __name__ == "__main__":
    main()
