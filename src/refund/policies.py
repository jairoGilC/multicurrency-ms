from decimal import Decimal
from typing import Protocol

from src.enums import RefundPolicy
from src.exceptions import RefundEngineError


class RefundPolicyStrategy(Protocol):
    """Protocol defining the interface for refund policy strategies."""

    def calculate_rate(
        self,
        original_rate: Decimal,
        current_rate: Decimal,
        days_elapsed: int,
    ) -> Decimal: ...

    @property
    def name(self) -> str: ...


class CustomerFavorablePolicy:
    """Returns max(original_rate, current_rate).

    This assumes rates represent source->destination conversion
    (e.g., BRL->USD = 0.19 means 1 BRL buys 0.19 USD).  Under this
    convention, a higher rate yields more destination currency, which
    is favorable to the customer receiving the refund.
    """

    @property
    def name(self) -> str:
        return RefundPolicy.CUSTOMER_FAVORABLE.value

    def calculate_rate(
        self,
        original_rate: Decimal,
        current_rate: Decimal,
        days_elapsed: int,
    ) -> Decimal:
        return max(original_rate, current_rate)


class OriginalRatePolicy:
    """Returns the original exchange rate used at booking time."""

    @property
    def name(self) -> str:
        return RefundPolicy.ORIGINAL_RATE.value

    def calculate_rate(
        self,
        original_rate: Decimal,
        current_rate: Decimal,
        days_elapsed: int,
    ) -> Decimal:
        return original_rate


class CurrentRatePolicy:
    """Returns the current market exchange rate."""

    @property
    def name(self) -> str:
        return RefundPolicy.CURRENT_RATE.value

    def calculate_rate(
        self,
        original_rate: Decimal,
        current_rate: Decimal,
        days_elapsed: int,
    ) -> Decimal:
        return current_rate


class TimeWeightedPolicy:
    """Blends original and current rates based on time elapsed.

    Recent cancellations lean toward the original rate; older ones
    toward the current rate.  The blending window is 90 days.
    """

    @property
    def name(self) -> str:
        return RefundPolicy.TIME_WEIGHTED.value

    def calculate_rate(
        self,
        original_rate: Decimal,
        current_rate: Decimal,
        days_elapsed: int,
    ) -> Decimal:
        weight = Decimal(str(min(days_elapsed / 90, 1.0)))
        return original_rate * (1 - weight) + current_rate * weight


_POLICY_MAP: dict[RefundPolicy, RefundPolicyStrategy] = {
    RefundPolicy.CUSTOMER_FAVORABLE: CustomerFavorablePolicy(),
    RefundPolicy.ORIGINAL_RATE: OriginalRatePolicy(),
    RefundPolicy.CURRENT_RATE: CurrentRatePolicy(),
    RefundPolicy.TIME_WEIGHTED: TimeWeightedPolicy(),
}


def get_policy(policy: RefundPolicy) -> RefundPolicyStrategy:
    """Factory: return the strategy instance for *policy*."""
    strategy = _POLICY_MAP.get(policy)
    if strategy is None:
        raise RefundEngineError(f"Unknown refund policy: {policy}")
    return strategy
