from decimal import Decimal

import pytest

from src.exchange.rate_comparator import RateComparator
from src.exchange.rate_provider import InMemoryRateProvider


@pytest.fixture
def comparator() -> RateComparator:
    provider = InMemoryRateProvider()
    return RateComparator(rate_provider=provider)


class TestCompareRates:
    def test_no_change(self, comparator: RateComparator) -> None:
        result = comparator.compare_rates(Decimal("1.0"), Decimal("1.0"))
        assert result == Decimal("0")

    def test_rate_increased(self, comparator: RateComparator) -> None:
        result = comparator.compare_rates(Decimal("1.0"), Decimal("1.10"))
        assert result == Decimal("0.1")

    def test_rate_decreased(self, comparator: RateComparator) -> None:
        result = comparator.compare_rates(Decimal("1.0"), Decimal("0.90"))
        assert result == Decimal("-0.1")

    def test_large_drift(self, comparator: RateComparator) -> None:
        result = comparator.compare_rates(Decimal("5.20"), Decimal("6.24"))
        assert result == Decimal("0.2")


class TestIsSignificantDrift:
    def test_within_threshold(self, comparator: RateComparator) -> None:
        assert not comparator.is_significant_drift(
            Decimal("1.0"), Decimal("1.05")
        )

    def test_exceeds_default_threshold(self, comparator: RateComparator) -> None:
        assert comparator.is_significant_drift(
            Decimal("1.0"), Decimal("1.15")
        )

    def test_negative_drift_exceeds_threshold(self, comparator: RateComparator) -> None:
        assert comparator.is_significant_drift(
            Decimal("1.0"), Decimal("0.85")
        )

    def test_custom_threshold(self, comparator: RateComparator) -> None:
        assert comparator.is_significant_drift(
            Decimal("1.0"), Decimal("1.06"), threshold=Decimal("0.05")
        )

    def test_at_exact_threshold_not_significant(
        self, comparator: RateComparator
    ) -> None:
        assert not comparator.is_significant_drift(
            Decimal("1.0"), Decimal("1.10"), threshold=Decimal("0.10")
        )


class TestGetRateImpact:
    def test_impact_with_rate_increase(self, comparator: RateComparator) -> None:
        result = comparator.get_rate_impact(
            amount=Decimal("100"),
            original_rate=Decimal("5.00"),
            current_rate=Decimal("5.50"),
        )
        assert result["amount_at_original"] == Decimal("500")
        assert result["amount_at_current"] == Decimal("550")
        assert result["difference"] == Decimal("50")
        assert result["percentage"] == Decimal("0.1")

    def test_impact_with_rate_decrease(self, comparator: RateComparator) -> None:
        result = comparator.get_rate_impact(
            amount=Decimal("200"),
            original_rate=Decimal("10.00"),
            current_rate=Decimal("9.00"),
        )
        assert result["amount_at_original"] == Decimal("2000")
        assert result["amount_at_current"] == Decimal("1800")
        assert result["difference"] == Decimal("-200")
        assert result["percentage"] == Decimal("-0.1")

    def test_impact_no_change(self, comparator: RateComparator) -> None:
        result = comparator.get_rate_impact(
            amount=Decimal("50"),
            original_rate=Decimal("1.0"),
            current_rate=Decimal("1.0"),
        )
        assert result["difference"] == Decimal("0")
        assert result["percentage"] == Decimal("0")
