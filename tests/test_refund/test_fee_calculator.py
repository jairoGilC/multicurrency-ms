"""Tests for the FeeCalculator."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.enums import Currency, FeeType
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import Fee
from src.refund.fee_calculator import FeeCalculator


class TestFeeCalculator:
    """FeeCalculator.apply_fees deducts percentage then fixed fees."""

    def test_percentage_fee_only(self, rate_provider: InMemoryRateProvider) -> None:
        """15% of 1000 = 150 deducted, net = 850."""
        calc = FeeCalculator(rate_provider)
        fees = [Fee(type=FeeType.PERCENTAGE, value=Decimal("15"), description="15% cancellation")]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        assert net == Decimal("850")
        assert len(applied) == 1
        assert applied[0].deducted_amount == Decimal("150.00")
        assert applied[0].type == FeeType.PERCENTAGE

    def test_fixed_fee_only(self, rate_provider: InMemoryRateProvider) -> None:
        """Fixed $25 BRL deducted from 1000 BRL, net = 975."""
        calc = FeeCalculator(rate_provider)
        fees = [Fee(type=FeeType.FIXED, value=Decimal("25"), currency=Currency.BRL)]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        assert net == Decimal("975")
        assert len(applied) == 1
        assert applied[0].deducted_amount == Decimal("25")
        assert applied[0].type == FeeType.FIXED

    def test_mixed_fees(self, rate_provider: InMemoryRateProvider) -> None:
        """10% first (1000 -> 900), then fixed 50 (900 -> 850)."""
        calc = FeeCalculator(rate_provider)
        fees = [
            Fee(type=FeeType.PERCENTAGE, value=Decimal("10")),
            Fee(type=FeeType.FIXED, value=Decimal("50"), currency=Currency.BRL),
        ]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        assert net == Decimal("850")
        assert len(applied) == 2
        # First applied is percentage
        assert applied[0].deducted_amount == Decimal("100.00")
        # Second applied is fixed
        assert applied[1].deducted_amount == Decimal("50")

    def test_fixed_fee_in_different_currency(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """Fixed fee of 10 USD applied to a BRL refund converts via current rate."""
        calc = FeeCalculator(rate_provider)
        fees = [Fee(type=FeeType.FIXED, value=Decimal("10"), currency=Currency.USD)]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        # Current USD -> BRL rate is 5.000
        expected_deduction = (Decimal("10") * Decimal("5.000")).quantize(Decimal("0.01"))
        assert applied[0].deducted_amount == expected_deduction
        assert net == Decimal("1000") - expected_deduction

    def test_fee_exceeds_amount_floors_at_zero(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """When fees exceed the amount, net floors at 0."""
        calc = FeeCalculator(rate_provider)
        fees = [Fee(type=FeeType.FIXED, value=Decimal("2000"), currency=Currency.BRL)]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        assert net == Decimal("0")
        # Deduction is capped at the remaining amount
        assert applied[0].deducted_amount == Decimal("1000")

    def test_empty_fee_list(self, rate_provider: InMemoryRateProvider) -> None:
        """No fees means original amount is returned unchanged."""
        calc = FeeCalculator(rate_provider)
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, [])

        assert net == Decimal("1000")
        assert applied == []

    def test_multiple_percentage_fees_compound(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """Multiple percentage fees compound: each applies to the remaining balance.

        10% of 1000 = 100  -> remaining 900
        20% of 900  = 180  -> remaining 720
        """
        calc = FeeCalculator(rate_provider)
        fees = [
            Fee(type=FeeType.PERCENTAGE, value=Decimal("10")),
            Fee(type=FeeType.PERCENTAGE, value=Decimal("20")),
        ]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        assert applied[0].deducted_amount == Decimal("100.00")
        assert applied[1].deducted_amount == Decimal("180.00")
        assert net == Decimal("720")

    def test_multiple_fixed_fees_cache_rate_lookups(self) -> None:
        """Two fixed fees in the same foreign currency should only trigger one rate lookup."""
        mock_provider = MagicMock()
        mock_provider.get_current_rate.return_value = Decimal("5.00")

        calc = FeeCalculator(mock_provider)
        fees = [
            Fee(type=FeeType.FIXED, value=Decimal("10"), currency=Currency.USD),
            Fee(type=FeeType.FIXED, value=Decimal("20"), currency=Currency.USD),
        ]
        net, applied = calc.apply_fees(Decimal("1000"), Currency.BRL, fees)

        # Rate lookup should happen only once for the (USD, BRL) pair
        mock_provider.get_current_rate.assert_called_once_with(Currency.USD, Currency.BRL)

        # 10 USD * 5.00 = 50 BRL, 20 USD * 5.00 = 100 BRL => net = 1000 - 50 - 100 = 850
        assert applied[0].deducted_amount == Decimal("50.00")
        assert applied[1].deducted_amount == Decimal("100.00")
        assert net == Decimal("850")
