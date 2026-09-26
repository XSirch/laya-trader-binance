"""Causal BTC/ETH residual mean reversion; isolated retrospective hypothesis."""

import math

from .broad_research import DAY_MS


FACTORS = ("BTCUSDT", "ETHUSDT")
WINDOW = 60
MODEL_RETURNS = 2*WINDOW
ENTRY_Z = 1.25
EXIT_Z = .5
MAX_SIGNAL_DAYS = 10
HURDLE_SIDE_COST = .0015


def mean(values):
    return math.fsum(values) / len(values)


def fit_residual(asset, btc, eth):
    """Fit factors on older 60 returns; fit AR(1) on next 60 residual returns."""
    if any(len(x) != MODEL_RETURNS for x in (asset, btc, eth)):
        raise ValueError("residual model requires exactly 120 aligned returns")
    if any(not math.isfinite(v) for values in (asset, btc, eth) for v in values):
        raise ValueError("nonfinite model input")
    training_asset, training_btc, training_eth = (values[:WINDOW] for values in (asset, btc, eth))
    ay, ax, az = mean(training_asset), mean(training_btc), mean(training_eth)
    y, x, z = ([v - average for v in values] for values, average in
               ((training_asset, ay), (training_btc, ax), (training_eth, az)))
    xx, zz = math.fsum(v*v for v in x), math.fsum(v*v for v in z)
    xz = math.fsum(a*b for a, b in zip(x, z))
    xy = math.fsum(a*b for a, b in zip(x, y))
    zy = math.fsum(a*b for a, b in zip(z, y))
    determinant = xx*zz - xz*xz
    if xx <= 0 or zz <= 0 or determinant <= 1e-8*xx*zz:
        return None
    b_btc, b_eth = (xy*zz - zy*xz)/determinant, (zy*xx - xy*xz)/determinant
    if abs(b_btc) + abs(b_eth) > 5:
        return None
    intercept = ay - b_btc*ax - b_eth*az
    residual = [a - intercept - b_btc*b - b_eth*c
                for a, b, c in zip(asset[WINDOW:], btc[WINDOW:], eth[WINDOW:])]
    path, total = [], 0.0
    for value in residual:
        total += value
        path.append(total)
    before, after = path[:-1], path[1:]
    mx, my = mean(before), mean(after)
    variance = math.fsum((v-mx)**2 for v in before)
    if variance <= 1e-12:
        return None
    phi = math.fsum((a-mx)*(b-my) for a, b in zip(before, after))/variance
    if not 0 < phi < math.exp(-1/30):
        return None
    intercept_ar = my - phi*mx
    innovations = [b - intercept_ar - phi*a for a, b in zip(before, after)]
    innovation_var = math.fsum(v*v for v in innovations)/(len(innovations)-2)
    equilibrium_std = math.sqrt(innovation_var/(1-phi*phi))
    if equilibrium_std < 1e-6:
        return None
    equilibrium = intercept_ar/(1-phi)
    deviation = path[-1] - equilibrium
    return {"beta_btc": b_btc, "beta_eth": b_eth, "intercept_daily": intercept,
            "phi": phi, "reversion_days": -1/math.log(phi),
            "equilibrium_std": equilibrium_std, "z": deviation/equilibrium_std,
            "expected_reversion_10d": abs(deviation)*(1-phi**MAX_SIGNAL_DAYS),
            "residual_daily_std": math.sqrt(math.fsum(v*v for v in residual)/(WINDOW-3))}


def enrich_states(data, base_states):
    """Attach models using only daily returns whose bars end at each state cutoff."""
    returns = {}
    for symbol, bars in data["klines"].items():
        returns[symbol] = {b.open_ms + DAY_MS: math.log(b.close/a.close)
                           for a, b in zip(bars, bars[1:])
                           if b.open_ms - a.open_ms == DAY_MS}
    output, quality = {}, {"models_valid": 0, "models_rejected": 0, "history_missing": 0}
    for symbol, rows in base_states.items():
        output[symbol] = {}
        for cutoff, row in rows.items():
            if row["latest_observed_close_ms"] != cutoff:
                raise ValueError("feature timestamp differs from completed daily close")
            timestamps = list(range(cutoff-(MODEL_RETURNS-1)*DAY_MS, cutoff+1, DAY_MS))
            if any(t not in returns.get(s, {}) for s in (symbol, *FACTORS) for t in timestamps):
                quality["history_missing"] += 1
                continue
            history = [returns[symbol][t] for t in timestamps]
            model = None if symbol in FACTORS else fit_residual(
                history, [returns[FACTORS[0]][t] for t in timestamps],
                [returns[FACTORS[1]][t] for t in timestamps])
            if symbol not in FACTORS:
                quality["models_valid" if model is not None else "models_rejected"] += 1
            output[symbol][cutoff] = {**row, "return_history60": history[-WINDOW:], "residual_model": model,
                                    "factor_fit_end_ms": cutoff-WINDOW*DAY_MS}
    return output, quality


class ResidualPolicy:
    """Signal hysteresis plus model-neutral hedge and trailing historical sizing."""

    def __init__(self, risk_scale=1):
        if risk_scale not in (1, 2):
            raise ValueError("only fixed risk scales 1 and 2 are permitted")
        self.risk_scale, self.active, self.audit = risk_scale, {}, []
        self.previous_day = None

    def __call__(self, states, rule):
        cutoffs = {row["latest_observed_close_ms"] for row in states.values()}
        if len(cutoffs) != 1:
            raise ValueError("one completed daily cutoff required")
        day = cutoffs.pop()
        if self.previous_day is not None and day <= self.previous_day:
            raise ValueError("policy decisions must advance in time")
        self.previous_day = day
        if any(f not in states or states[f]["quote_volume20"] < 10_000_000 for f in FACTORS):
            self.active.clear()
            self.audit.append({"cutoff_ms": day, "reason": "hedge_unavailable", "target_weights": {}})
            return {}
        eligible = {s: row for s, row in states.items() if s not in FACTORS
                    and row["residual_model"] is not None and row["quote_volume20"] >= 10_000_000
                    and .005 <= row["volatility"] <= .15}
        exited = set()
        for symbol, record in list(self.active.items()):
            row = eligible.get(symbol)
            z = row["residual_model"]["z"] if row else 0
            if (row is None or abs(z) <= EXIT_Z or record["side"]*z >= 0
                    or day-record["opened"] >= MAX_SIGNAL_DAYS*DAY_MS):
                del self.active[symbol]
                exited.add(symbol)
        candidates = passed_hurdle = 0
        for symbol, row in sorted(eligible.items()):
            if symbol in self.active or symbol in exited:
                continue
            model = row["residual_model"]
            if abs(model["z"]) < ENTRY_Z:
                continue
            candidates += 1
            side = -1 if model["z"] > 0 else 1
            hedge_carry = (row["carry30"] - model["beta_btc"]*states[FACTORS[0]]["carry30"]
                           - model["beta_eth"]*states[FACTORS[1]]["carry30"])
            adverse_carry = max(0, -side*hedge_carry)*MAX_SIGNAL_DAYS/365
            adverse_drift = max(0, -side*model["intercept_daily"])*MAX_SIGNAL_DAYS
            roundtrip = 2*HURDLE_SIDE_COST*(1+abs(model["beta_btc"])+abs(model["beta_eth"]))
            if model["expected_reversion_10d"] <= roundtrip + adverse_carry + adverse_drift:
                continue
            passed_hurdle += 1
            self.active[symbol] = {"side": side, "opened": day}
        raw = {s: record["side"]/eligible[s]["residual_model"]["equilibrium_std"]
               for s, record in self.active.items()}
        for factor, key in zip(FACTORS, ("beta_btc", "beta_eth")):
            raw[factor] = -math.fsum(raw[s]*eligible[s]["residual_model"][key] for s in self.active)
        raw = {s: w for s, w in raw.items() if w}
        raw_gross = math.fsum(abs(w) for w in raw.values())
        expected_vol, weights = 0.0, {}
        if raw_gross:
            raw = {s: w/raw_gross for s, w in raw.items()}
            history = [math.fsum(w*states[s]["return_history60"][i] for s, w in raw.items())
                       for i in range(WINDOW)]
            average = mean(history)
            expected_vol = math.sqrt(math.fsum((r-average)**2 for r in history)/(WINDOW-1)*365)
            scale = min(self.risk_scale, .10*self.risk_scale/max(expected_vol, 1e-8))
            scale = min(scale, min((.50 if s in FACTORS else .10)*self.risk_scale/abs(w)
                                   for s, w in raw.items()))
            weights = {s: w*scale for s, w in raw.items()}
            expected_vol *= scale
        beta_error = {factor: weights.get(factor, 0) + math.fsum(
            weights.get(s, 0)*eligible[s]["residual_model"][key] for s in self.active)
            for factor, key in zip(FACTORS, ("beta_btc", "beta_eth"))}
        if any(abs(v) > 1e-10 for v in beta_error.values()):
            raise ValueError("factor hedge lost during sizing")
        self.audit.append({"cutoff_ms": day, "eligible_models": len(eligible),
                           "new_candidates": candidates, "passed_cost_hurdle": passed_hurdle,
                           "active_signal_count": len(self.active), "closed_signals": sorted(exited),
                           "estimated_annual_volatility": expected_vol,
                           "gross_target": math.fsum(abs(w) for w in weights.values()),
                           "beta_error": beta_error, "target_weights": weights})
        return weights
