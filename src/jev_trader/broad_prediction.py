"""Rolling weekly cross-sectional forecasts with purged, completed labels."""

import hashlib
import json
import math
from datetime import datetime, timezone

from .binance_data import utc_ms
from .broad_data import load as load_daily
from .broad_execution import evaluate
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, features
from .cli import ROOT, RESULTS
from .extended import solve
from .statistics import family_bootstrap

FIELDS = ("momentum7", "momentum30", "momentum90", "reversal1", "reversal7", "carry30",
          "volatility", "taker_flow20", "beta60", "time_series_ensemble")
PENALTIES = (.1, 1.0, 10.0)
WEEK = 7 * DAY_MS
PERIODS = {"development": ("2022-01-01", "2024-01-01"),
           "validation_2024": ("2024-01-01", "2025-01-01"),
           "validation_2025": ("2025-01-01", "2026-01-01"),
           "validation_2026": ("2026-01-01", "2026-08-01"),
           "combined": ("2024-01-01", "2026-08-01")}


def eligible(states):
    return {s: f for s, f in states.items() if f["quote_volume20"] >= 10_000_000
            and .005 <= f["volatility"] <= .15}


def rank_vectors(states):
    """Midranks preserve equal observations instead of inventing symbol alpha."""
    output = {s: [] for s in states}
    if len(states) < 2:
        return output
    for field in FIELDS:
        values = sorted(f[field] for f in states.values())
        for s, f in states.items():
            lower = sum(v < f[field] for v in values)
            ties = sum(v == f[field] for v in values)
            output[s].append((lower + (ties - 1) / 2) / (len(values) - 1) - .5)
    return output


def training_weeks(data, states):
    prices = {s: {b.open_ms: b for b in bars} for s, bars in data["klines"].items()}
    marks = {s: {b.open_ms: b for b in bars} for s, bars in data["markPriceKlines"].items()}
    funding = {s: {} for s in prices}
    for s, events in data["fundingRate"].items():
        for row in events:
            funding[s].setdefault(row.timestamp_ms // DAY_MS * DAY_MS, []).append(row)
    dates = sorted({t for rows in states.values() for t in rows
                    if datetime.fromtimestamp(t / 1000, timezone.utc).weekday() == 0})
    weeks, unavailable = [], []
    for t in dates:
        current = eligible({s: rows[t] for s, rows in states.items() if t in rows})
        if len(current) < 8:
            continue
        vectors, targets = rank_vectors(current), {}
        for s in current:
            if t not in prices[s] or t + WEEK not in prices[s] or any(
                    day not in marks[s] for day in range(t, t + WEEK, DAY_MS)):
                break
            entry = prices[s][t].open
            value = prices[s][t + WEEK].open / entry - 1
            for day in range(t, t + WEEK, DAY_MS):
                mark = marks[s][day]
                for event in funding[s].get(day, []):
                    scalar = -event.rate
                    if event.timestamp_ms - t < 60_000:
                        scalar = min(scalar, 0)
                    value += scalar * (mark.low if scalar > 0 else mark.high) / entry
            targets[s] = value
        if len(targets) != len(current):
            unavailable.append({"signal_ms": t, "label_end_ms": t + WEEK,
                                "reason": "Complete cross-section label unavailable; entire week excluded from training."})
            continue
        mean = sum(targets.values()) / len(targets)
        n = len(current)
        ys = {s: targets[s] - mean for s in current}
        gram = [[sum(vectors[s][a] * vectors[s][b] for s in current) / n
                 for b in range(len(FIELDS))] for a in range(len(FIELDS))]
        rhs = [sum(vectors[s][a] * ys[s] for s in current) / n for a in range(len(FIELDS))]
        weeks.append({"signal_ms": t, "label_end_ms": t + WEEK, "gram": gram, "rhs": rhs,
                      "targets": ys, "vectors": vectors})
    return weeks, unavailable, dates


def forecasts(states, weeks, dates):
    output = {str(p): {s: {} for s in states} for p in PENALTIES}
    audits, errors = [], {str(p): [] for p in PENALTIES}
    labels = {week["signal_ms"]: week for week in weeks}
    for t in dates:
        # Strictly earlier than signal cutoff: even a label ending at today's
        # 00:00 execution proxy is purged, since this price was not known before it.
        known = [w for w in weeks if t - 104 * WEEK <= w["signal_ms"] and w["label_end_ms"] < t]
        if len(known) < 52:
            continue
        current = eligible({s: rows[t] for s, rows in states.items() if t in rows})
        if len(current) < 8:
            continue
        vectors = rank_vectors(current)
        n = len(known)
        gram = [[sum(w["gram"][a][b] for w in known) / n for b in range(len(FIELDS))]
                for a in range(len(FIELDS))]
        rhs = [sum(w["rhs"][a] for w in known) / n for a in range(len(FIELDS))]
        audit = {"signal_ms": t, "latest_label_end_ms": max(w["label_end_ms"] for w in known),
                 "first_training_signal_ms": known[0]["signal_ms"], "training_weeks": n,
                 "prediction_assets": len(current), "coefficients": {}}
        for penalty in PENALTIES:
            key = str(penalty)
            weights = solve([[v + (penalty if a == b else 0) for b, v in enumerate(row)]
                             for a, row in enumerate(gram)], rhs)
            audit["coefficients"][key] = weights
            for s, vector in vectors.items():
                prediction = sum(a * b for a, b in zip(weights, vector))
                output[key][s][t] = {**current[s], "prediction": prediction}
                if t in labels and s in labels[t]["targets"]:
                    errors[key].append({"signal_ms": t, "symbol": s, "prediction": prediction,
                                        "actual": labels[t]["targets"][s]})
        audits.append(audit)
    return output, audits, errors


def portfolio(states, sizing):
    current = eligible(states)
    if sizing == "zero" or len(current) < 8 or "BTCUSDT" not in states:
        return {}
    if max(f["prediction"] for f in current.values()) - min(f["prediction"] for f in current.values()) < 1e-12:
        return {}
    ranked = sorted(current, key=lambda s: (current[s]["prediction"], s))
    count = max(2, len(ranked) // 5)
    weights = {}
    for side, symbols in ((-1, ranked[:count]), (1, ranked[-count:])):
        raw = {s: 1 / current[s]["volatility"] if sizing == "inverse_vol" else 1 for s in symbols}
        total = sum(raw.values())
        weights.update({s: side * .25 * value / total for s, value in raw.items()})
    beta = sum(w * states[s]["beta60"] for s, w in weights.items())
    weights["BTCUSDT"] = weights.get("BTCUSDT", 0) - beta / states["BTCUSDT"]["beta60"]
    scale = min(1, .5 / sum(abs(v) for v in weights.values()))
    return {s: w * scale for s, w in weights.items() if abs(w) > 1e-12}


def summarize_errors(rows, start, end):
    rows = [r for r in rows if utc_ms(start) <= r["signal_ms"] < utc_ms(end)]
    if not rows:
        return {"samples": 0}
    mse = sum((r["prediction"] - r["actual"]) ** 2 for r in rows) / len(rows)
    null = sum(r["actual"] ** 2 for r in rows) / len(rows)
    return {"samples": len(rows), "mse": mse, "zero_prediction_mse": null,
            "out_of_sample_r2": 1 - mse / null if null else None,
            "direction_accuracy": sum((r["prediction"] > 0) == (r["actual"] > 0) for r in rows) / len(rows)}


def run():
    data, _, _ = load_daily()
    state = features(data)
    weeks, unavailable, dates = training_weeks(data, state)
    signals, audits, errors = forecasts(state, weeks, dates)
    hourly, sources = load_hourly(data)
    training, training_sources = load_hourly(data, "training_hourly_manifest.json")
    for kind in hourly:
        for s in hourly[kind]:
            hourly[kind][s].update(training[kind][s])
    results = {}
    variants = [(f"ridge{p}_{sizing}", signals[str(p)], sizing) for p in PENALTIES
                for sizing in ("equal", "inverse_vol")] + [("zero", state, "zero")]
    for name, signal, sizing in variants:
        results[name] = {}
        for period, dates in PERIODS.items():
            results[name][period] = {}
            for label, cost in (("base", .001), ("stress", .0015), ("double_stress", .003)):
                try:
                    m = evaluate(hourly, data["fundingRate"], signal, sizing, *dates, cost,
                                 target_policy=portfolio)
                    m["status"] = "complete"
                except ValueError as exc:
                    m = {"status": "invalid_execution", "error": str(exc)}
                results[name][period][label] = m
        m = results[name]["combined"]["stress"]
        print(name, {k: m[k] for k in ("status", "return_pct", "max_drawdown_pct", "positive_months", "months", "error") if k in m}, flush=True)
    candidates = [name for name in results if name != "zero" and
                  results[name]["development"]["stress"]["status"] == "complete"]
    selected = max(candidates, key=lambda name: results[name]["development"]["stress"]["return_pct"]) if candidates else None
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "fields": FIELDS, "results": results,
              "selected_on_development": selected, "training_audits": audits, "unavailable_label_weeks": unavailable,
              "prediction_scores": {p: {period: summarize_errors(rows, *dates) for period, dates in PERIODS.items()}
                                    for p, rows in errors.items()},
              "deployable": False, "verified_hourly_sources": len(sources) + len(training_sources),
              "hourly_sources_sha256": hashlib.sha256(json.dumps(
                  [{k: v for k, v in r.items() if k != "path"} for r in sources + training_sources],
                  sort_keys=True).encode()).hexdigest(),
              "source_code_sha256": {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                                     for name in ("broad_prediction.py", "broad_execution.py", "broad_hourly.py")},
              "limits": ["Retrospective after multiple previous strategy searches; not independent confirmation.",
                         "Training target uses midnight daily opens and adverse daily funding marks; execution delayed to 01:00.",
                         "Unavailable full cross-section weeks are omitted only when training after their end; no imputed delisting price."]}
    curves = {name: row["combined"]["stress"]["daily_equity"] for name, row in results.items()
              if row["combined"]["stress"]["status"] == "complete"}
    if selected in curves and len(curves) == len(results):
        report["statistical_diagnostic"] = family_bootstrap(curves, selected)
    else:
        report["statistical_diagnostic"] = {"status": "incomplete_family_execution", "valid_members": list(curves)}
    (RESULTS / "broad_prediction.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"development selection: {selected}", flush=True)
    return report


if __name__ == "__main__":
    run()
