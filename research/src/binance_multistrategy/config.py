from __future__ import annotations
from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class ResearchConfig:
    market: str = "spot"
    fee_bps: float = 10.0  # PER SIDE; assumption, never an account-specific quote.
    slippage_bps: float = 5.0  # PER SIDE, includes assumed spread/adverse execution.
    stress_multiplier: float = 2.0
    risk_fraction: float = 0.0025
    max_notional_equity: float = 1.0  # No leveraged research in v0.1.
    min_stop_fraction: float = 0.002
    max_stop_fraction: float = 0.06
    candidate_cooldown_minutes: int = 5
    embargo_minutes: int = 480
    minimum_probability: float = 0.35  # Search from a useful floor; win rate remains a preference.
    target_win_rate: float = 0.70  # Preference, not a hard promotion gate.
    min_validation_trades: int = 200
    min_validation_weeks: int = 8
    min_profit_factor: float = 1.25
    max_drawdown: float | None = None  # Legacy field; drawdown is never a promotion gate.
    min_net_ev_per_trade: float = 0.012
    min_payoff_ratio: float = 1.0
    min_expected_r: float = 0.05
    confidence_lower_bound_required: bool = False  # Legacy field; confidence bounds are diagnostic only.
    bootstrap_iterations: int = 1000
    max_training_rows: int = 250_000
    random_seed: int = 27
    n_threads: int = 4

    def __post_init__(self) -> None:
        if self.market not in {"spot", "usd_m"}:
            raise ValueError("market must be spot or usd_m")
        for name, value in asdict(self).items():
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError(f"non-finite configuration: {name}")
        if self.fee_bps < 0 or self.slippage_bps < 0 or self.stress_multiplier < 1:
            raise ValueError("Costs must be nonnegative; stress_multiplier >= 1")
        if not 0 < self.risk_fraction <= 0.01:
            raise ValueError("Research risk_fraction must be in (0, 0.01]")
        if not 0 < self.max_notional_equity <= 1:
            raise ValueError("v0.1 supports at most 1x notional/equity, no liquidation model")
        if not 0 < self.min_stop_fraction < self.max_stop_fraction < 1:
            raise ValueError("Invalid stop bounds")
        if not 0 < self.minimum_probability < 1 or not 0 < self.target_win_rate < 1:
            raise ValueError("Probabilities must be in (0, 1)")
        if self.max_drawdown is not None and not 0 < self.max_drawdown < 1:
            raise ValueError("max_drawdown must be in (0, 1) when an explicit ceiling is used")
        if self.min_net_ev_per_trade < 0 or self.min_payoff_ratio <= 0:
            raise ValueError("EV threshold must be nonnegative and payoff ratio positive")
        if self.candidate_cooldown_minutes < 1 or self.embargo_minutes < 480:
            raise ValueError("Cooldown >= 1, embargo >= maximum 480-minute holding horizon")
        if min(self.min_validation_trades, self.min_validation_weeks,
               self.max_training_rows, self.bootstrap_iterations, self.n_threads) < 1:
            raise ValueError("Sample counts and n_threads must be positive")

    def to_dict(self) -> dict:
        return asdict(self)
