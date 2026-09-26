"""Fixed random Fourier features for causal nonlinear indicator interactions."""

import math
import random

from .broad_prediction import forecasts, rank_vectors, run, training_weeks
from .broad_technical import feature_bundle


class FourierVectors:
    def __init__(self, dimensions, scale, components=64, seed=548):
        if dimensions < 1 or scale <= 0 or components < 1:
            raise ValueError("invalid fixed Fourier design")
        rng = random.Random(seed)
        self.dimensions = dimensions
        self.weights = [[rng.gauss(0, 1) / scale for _ in range(dimensions)] for _ in range(components)]
        self.phases = [rng.uniform(0, 2 * math.pi) for _ in range(components)]
        self.normalization = math.sqrt(2 / components)

    def transform(self, vector):
        if len(vector) != self.dimensions or any(not math.isfinite(x) for x in vector):
            raise ValueError("invalid Fourier input")
        return [self.normalization * math.cos(sum(w * x for w, x in zip(weights, vector)) + phase)
                for weights, phase in zip(self.weights, self.phases)]

    def __call__(self, states, fields):
        return {s: self.transform(v) for s, v in rank_vectors(states, fields).items()}


def models(data, state, fields):
    output, audits, errors, unavailable = {}, [], {}, []
    for scale in (1, 2, 4):
        name = f"rff_scale{scale}"
        vectorizer = FourierVectors(len(fields), scale)
        weeks, absent, dates = training_weeks(data, state, fields, vectorizer)
        signals, audit, error = forecasts(state, weeks, dates, fields, vectorizer, penalties=(.1,))
        output[name] = signals["0.1"]
        audits.extend({**row, "model": name} for row in audit)
        errors[name] = error["0.1"]
        if not unavailable:
            unavailable = absent
        elif unavailable != absent:
            raise ValueError("label availability unexpectedly differs between fixed transforms")
        print(f"nonlinear model {name}: {len(audit)} causal weekly fits", flush=True)
    design = {"type": "fixed_random_fourier_ridge", "components": 64, "seed": 548,
              "scales": [1, 2, 4], "ridge_penalty": .1,
              "input": "cross-sectional midranks of all 60 economic and technical fields",
              "random_weights_fit_to_outcomes": False}
    return output, audits, errors, unavailable, design


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--settlement-bounds", action="store_true")
    args = parser.parse_args()
    run(feature_bundle, "nonlinear", args.settlement_bounds, models)
