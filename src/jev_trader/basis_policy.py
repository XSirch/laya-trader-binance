"""Fixed economic entry hurdle and segregated-margin guard; no orders or JEV."""

import math

FUNDAMENTAL_R0 = 1/1.0005-1


class BasisPolicy:
    def __init__(self, reference, spot_cost, future_cost, spot_fraction, max_hold_hours):
        if reference not in ("fundamental_r0", "median720"):
            raise ValueError("unknown fixed basis reference")
        if not 0 < spot_fraction < 1 or max_hold_hours not in (24, 168):
            raise ValueError("unsupported allocation or horizon")
        if not all(math.isfinite(x) and x >= 0 for x in (spot_cost, future_cost)):
            raise ValueError("invalid costs")
        self.reference, self.spot_cost, self.future_cost = reference, spot_cost, future_cost
        self.spot_fraction, self.max_hold_hours = spot_fraction, max_hold_hours

    def __call__(self, state, position):
        basis = state["basis_fraction"]
        context = {"context_sha256": state["context_sha256"], "observed_basis": basis}
        if position is not None:
            converged = basis <= position["target_basis"]
            return {"action": "exit" if converged else "hold",
                    "reason": "basis_converged" if converged else "await_convergence", **context}
        target = FUNDAMENTAL_R0 if self.reference == "fundamental_r0" else state["basis_previous720_median"]
        roundtrip = 2*self.spot_cost+2*self.future_cost*(1+basis)
        adverse_funding = max(-state["funding_past30_mean_rate"], 0)*math.ceil(self.max_hold_hours/8)*(1+basis)
        edge = basis-target-roundtrip-adverse_funding
        context.update(target_basis=target, projected_convergence_fraction=basis-target,
                       cost_hurdle_fraction=roundtrip, adverse_funding_hurdle_fraction=adverse_funding,
                       surplus_fraction=edge)
        for leg in ("spot", "futures"):
            volume = state["quote_volume24"][leg]
            count = state[leg+"_hourly"]["participation"]["trade_count"]
            if volume is None or volume < 10_000_000 or count is None or count <= 0:
                return {"action": "hold", "reason": "past_liquidity_guard", **context}
        volatility = state["futures_hourly"]["volatility"]
        shock = 3*max(volatility["realized20_per_bar_pct"], volatility["atr14_pct"])/100*math.sqrt(self.max_hold_hours)
        initial_margin = (1-self.spot_fraction)/self.spot_fraction-self.future_cost
        funding_reserve = max(-state["funding_past30_mean_rate"], 0)*math.ceil(self.max_hold_hours/8)
        stressed_margin = (initial_margin-shock)/(1+shock)-funding_reserve
        context.update(adverse_price_shock_fraction=shock, prospective_margin_ratio=stressed_margin,
                       prospective_funding_margin_debit=funding_reserve)
        if stressed_margin < .20:
            return {"action": "hold", "reason": "past_volatility_margin_guard", **context}
        return {"action": "enter" if edge > 0 else "hold",
                "reason": "basis_exceeds_costs" if edge > 0 else "insufficient_basis", **context}
