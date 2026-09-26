"""Dependent-data bootstrap diagnostics with a within-family max statistic."""

from __future__ import annotations

import math
import random


def family_bootstrap(equities, selected, block_days=30, draws=2000, seed=1907):
    """Circular blocks share resampling indices across all candidate strategies.

    Cash earns zero. The max-mean centered bootstrap adjusts only for the input
    family, not past experiments. It is a diagnostic, not evidence of live alpha.
    """
    if selected not in equities or draws < 100:
        raise ValueError("missing selected candidate or too few bootstrap draws")
    names = sorted(equities)
    calendars = {name: sorted((int(t), value) for t, value in equities[name].items()) for name in names}
    dates = [t for t, _ in calendars[names[0]]]
    if any([t for t, _ in calendars[name]] != dates for name in names):
        raise ValueError("candidate calendars differ")
    if any(b - a != 86_400_000 for a, b in zip(dates, dates[1:])):
        raise ValueError("bootstrap requires a complete daily equity calendar")
    returns = {}
    for name, path in calendars.items():
        if any(not math.isfinite(value) or value <= 0 for _, value in path):
            raise ValueError("equity must be finite and positive")
        returns[name] = [math.log(b / a) for (_, a), (_, b) in zip(path, path[1:])]
    n = len(returns[names[0]])
    if n < 2 * block_days or block_days < 1:
        raise ValueError("insufficient history for block bootstrap")
    means = {name: sum(values) / n for name, values in returns.items()}
    block_sums, remainder_sums = {}, {}
    whole, remainder = divmod(n, block_days)
    for name, values in returns.items():
        prefix = [0.0]
        for value in values + values[:block_days]:
            prefix.append(prefix[-1] + value)
        block_sums[name] = [prefix[i + block_days] - prefix[i] for i in range(n)]
        remainder_sums[name] = [prefix[i + remainder] - prefix[i] for i in range(n)]
    rng = random.Random(seed)
    selected_draws, max_null = [], []
    for _ in range(draws):
        starts = [rng.randrange(n) for _ in range(whole)]
        tail = rng.randrange(n)
        bootstrap_means = {name: (sum(block_sums[name][i] for i in starts) + remainder_sums[name][tail]) / n
                           for name in names}
        selected_draws.append(365 * bootstrap_means[selected])
        max_null.append(max(0.0, max(bootstrap_means[name] - means[name] for name in names)))
    selected_draws.sort()
    maximum_observed = max(0.0, max(means.values()))
    return {
        "days": n, "block_days": block_days, "draws": draws, "seed": seed,
        "family_size": len(names), "selection": selected,
        "cash_benchmark_return": 0,
        "selected_annualized_log_return_pct": 36500 * means[selected],
        "selected_annualized_geometric_return_95_interval_pct": [
            100 * math.expm1(selected_draws[int(draws * .025)]),
            100 * math.expm1(selected_draws[min(draws - 1, int(draws * .975))])],
        "max_mean_reality_check_pvalue": (1 + sum(v >= maximum_observed for v in max_null)) / (draws + 1),
        "selected_mean_family_adjusted_pvalue": (1 + sum(v >= means[selected] for v in max_null)) / (draws + 1),
        "limits": ["Centered circular moving-block bootstrap; finite-sample approximation.",
                   "Adjustment covers only the supplied family, not every prior research trial.",
                   "No risk-free yield, live fills, delisting uncertainty or structural breaks are resolved by a p-value."]}
