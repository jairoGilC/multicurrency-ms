from decimal import Decimal
from typing import Protocol

from src.enums import RefundPolicy


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
    """Returns max(original_rate, current_rate) -- the rate that gives
    the customer more money in the destination currency."""

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


_POLICY_MAP: dict[RefundPolicy, type[RefundPolicyStrategy]] = {
    RefundPolicy.CUSTOMER_FAVORABLE: CustomerFavorablePolicy,  # type: ignore[dict-item]
    RefundPolicy.ORIGINAL_RATE: OriginalRatePolicy,  # type: ignore[dict-item]
    RefundPolicy.CURRENT_RATE: CurrentRatePolicy,  # type: ignore[dict-item]
    RefundPolicy.TIME_WEIGHTED: TimeWeightedPolicy,  # type: ignore[dict-item]
}


def get_policy(policy: RefundPolicy) -> RefundPolicyStrategy:
    """Factory: return the strategy instance for *policy*."""
    strategy_cls = _POLICY_MAP.get(policy)
    if strategy_cls is None:
        raise ValueError(f"Unknown refund policy: {policy}")
    return strategy_cls()  # type: ignore[return-value]
