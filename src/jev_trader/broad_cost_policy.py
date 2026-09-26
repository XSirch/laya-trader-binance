"""Script-owned weekly hold/rebalance/exit choice from forecast minus costs."""

import math


def choose(states, proposed, current, side_cost):
    if side_cost < 0 or not math.isfinite(side_cost):
        raise ValueError("invalid transaction cost")
    options = {"hold": dict(current), "cash": {}, "rebalance": dict(proposed)}
    scores = {}
    for name, weights in options.items():
        if any(not math.isfinite(w) for w in weights.values()):
            raise ValueError("nonfinite portfolio weight")
        gross = sum(abs(w) for w in weights.values())
        missing = [s for s, w in weights.items() if w and
                   (s not in states or "prediction" not in states[s])]
        valid = gross <= .5 + 1e-12 and not missing
        turnover = sum(abs(weights.get(s, 0) - current.get(s, 0)) for s in set(weights) | set(current))
        alpha = sum(w * states[s]["prediction"] for s, w in weights.items() if w) if valid else None
        if alpha is not None and not math.isfinite(alpha):
            raise ValueError("nonfinite forecast")
        cost = side_cost * turnover
        scores[name] = {"valid": valid, "gross_weight": gross, "missing_forecasts": missing,
                        "expected_alpha": alpha, "turnover": turnover, "expected_cost": cost,
                        "net_score": alpha - cost if valid else None}
    valid = [name for name, row in scores.items() if row["valid"]]
    # Exact ties prefer less turnover and then holding; no fitted threshold.
    preference = {"hold": 2, "cash": 1, "rebalance": 0}
    selected = max(valid, key=lambda n: (scores[n]["net_score"], -scores[n]["turnover"], preference[n]))
    return options[selected], {"chosen": selected, "current_weights": current, "proposed_weights": proposed,
                               "alternatives": scores, "expected_cost_fraction": scores[selected]["expected_cost"],
                               "side_cost": side_cost}


if __name__ == "__main__":
    import argparse
    from .broad_prediction import run
    from .broad_technical import feature_bundle
    from .broad_nonlinear import models
    parser = argparse.ArgumentParser()
    parser.add_argument("family", choices=("economic", "technical", "nonlinear"))
    parser.add_argument("--settlement-bounds", action="store_true")
    args = parser.parse_args()
    run(None if args.family == "economic" else feature_bundle, args.family, args.settlement_bounds,
        models if args.family == "nonlinear" else None, decision_policy=choose)
