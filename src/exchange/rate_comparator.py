from decimal import Decimal

from src.exchange.rate_provider import RateProvider


class RateComparator:
    def __init__(self, rate_provider: RateProvider) -> None:
        self._rate_provider = rate_provider

    def compare_rates(self, original_rate: Decimal, current_rate: Decimal) -> Decimal:
        return (current_rate - original_rate) / original_rate

    def is_significant_drift(
        self,
        original_rate: Decimal,
        current_rate: Decimal,
        threshold: Decimal = Decimal("0.10"),
    ) -> bool:
        drift = abs(self.compare_rates(original_rate, current_rate))
        return drift > threshold

    def get_rate_impact(
        self,
        amount: Decimal,
        original_rate: Decimal,
        current_rate: Decimal,
    ) -> dict[str, Decimal]:
        amount_at_original = amount * original_rate
        amount_at_current = amount * current_rate
        return {
            "amount_at_original": amount_at_original,
            "amount_at_current": amount_at_current,
            "difference": amount_at_current - amount_at_original,
            "percentage": self.compare_rates(original_rate, current_rate),
        }
