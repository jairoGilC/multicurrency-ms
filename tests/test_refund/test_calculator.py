"""Tests for the RefundCalculator."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import pytest

from src.enums import Currency, FeeType, RefundPolicy, RefundStatus
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import Fee, RefundRequest, Transaction
from src.refund.calculator import RefundCalculator


_SIXTY_DAYS_AGO = datetime.now(timezone.utc) - timedelta(days=60)
_NOW = datetime.now(timezone.utc)


def _make_transaction(**overrides) -> Transaction:
    """Helper to build a Transaction with sensible defaults."""
    defaults = dict(
        id="txn-calc-001",
        customer_id="cust-001",
        amount=Decimal("1000"),
        currency=Currency.BRL,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("192"),
        exchange_rate_used=Decimal("0.192"),
        transaction_type="FLIGHT",
        payment_method="CREDIT_CARD",
        timestamp=_SIXTY_DAYS_AGO,
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def _make_request(**overrides) -> RefundRequest:
    """Helper to build a RefundRequest with sensible defaults."""
    defaults = dict(
        transaction_id="txn-calc-001",
        policy=RefundPolicy.ORIGINAL_RATE,
        timestamp=_NOW,
    )
    defaults.update(overrides)
    return RefundRequest(**defaults)


class TestRefundCalculator:
    """RefundCalculator orchestrates rate selection, fees, and conversion."""

    def test_same_currency_full_refund(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """When destination == transaction currency, no conversion occurs."""
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction()
        req = _make_request(destination_currency=Currency.BRL)

        result = calc.calculate(txn, req)

        assert result.destination_currency == Currency.BRL
        assert result.destination_amount == Decimal("1000")
        assert result.rate_used == Decimal("1")
        assert result.status == RefundStatus.CALCULATED

    def test_cross_currency_original_rate(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """Cross-currency refund using ORIGINAL_RATE policy uses the original rate."""
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction()
        req = _make_request(
            destination_currency=Currency.USD,
            policy=RefundPolicy.ORIGINAL_RATE,
        )

        result = calc.calculate(txn, req)

        assert result.rate_used == Decimal("0.192")
        expected_destination = (Decimal("1000") * Decimal("0.192")).quantize(
            Decimal("0.01")
        )
        assert result.destination_amount == expected_destination
        assert result.destination_currency == Currency.USD

    def test_cross_currency_customer_favorable(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """CUSTOMER_FAVORABLE picks the higher rate (current 0.200 > original 0.192)."""
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction()
        req = _make_request(
            destination_currency=Currency.USD,
            policy=RefundPolicy.CUSTOMER_FAVORABLE,
        )

        result = calc.calculate(txn, req)

        # Current BRL->USD rate is 0.200 which is > 0.192 (original)
        assert result.rate_used == Decimal("0.200")
        expected = (Decimal("1000") * Decimal("0.200")).quantize(Decimal("0.01"))
        assert result.destination_amount == expected

    def test_partial_refund_with_fees_and_conversion(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """Partial refund of 500 BRL with 10% fee, converted to USD at original rate.

        500 BRL - 10% fee (50) = 450 BRL after fees
        450 * 0.192 = 86.40 USD
        """
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction()
        req = _make_request(
            requested_amount=Decimal("500"),
            destination_currency=Currency.USD,
            policy=RefundPolicy.ORIGINAL_RATE,
            fees=[Fee(type=FeeType.PERCENTAGE, value=Decimal("10"))],
        )

        result = calc.calculate(txn, req)

        assert result.original_amount == Decimal("500")
        assert result.refund_amount_after_fees == Decimal("450")
        assert result.total_fees == Decimal("50.00")
        expected_dest = (Decimal("450") * Decimal("0.192")).quantize(Decimal("0.01"))
        assert result.destination_amount == expected_dest

    def test_audit_entries_created_for_each_step(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """The calculator creates audit entries for each processing step."""
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction()
        req = _make_request(destination_currency=Currency.USD)

        result = calc.calculate(txn, req)

        actions = [e.action for e in result.audit_entries]
        assert "determine_refund_amount" in actions
        assert "determine_destination_currency" in actions
        assert "rate_lookup" in actions
        assert "policy_applied" in actions
        assert "fee_application" in actions
        assert "conversion" in actions
        assert "final_calculation" in actions

    def test_destination_defaults_to_transaction_currency(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """When no destination_currency is specified, it defaults to the transaction currency."""
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction()
        req = _make_request()  # no destination_currency set

        result = calc.calculate(txn, req)

        assert result.destination_currency == txn.currency

    def test_quantize_uses_round_half_up(
        self, rate_provider: InMemoryRateProvider
    ) -> None:
        """Monetary conversion rounds .005 up (banker-friendly), not to-even.

        With amount=999 BRL and rate=0.19005, the raw product is 189.91995.
        Quantizing to 2 decimal places:
          - ROUND_HALF_EVEN (default): 189.92 (rounds .005 to even -> 189.92)
          - ROUND_HALF_UP:             189.92 (rounds .005 up   -> 189.92)

        We need a case where they actually differ.  With amount=1 and rate
        that produces exactly X.XX5:
          amount=100, rate=0.18005 -> 18.005
            ROUND_HALF_EVEN -> 18.00 (rounds to even)
            ROUND_HALF_UP   -> 18.01 (rounds up)
        """
        calc = RefundCalculator(rate_provider)
        txn = _make_transaction(
            amount=Decimal("100"),
            exchange_rate_used=Decimal("0.18005"),
        )
        # Use ORIGINAL_RATE so rate_used = 0.18005
        req = _make_request(
            destination_currency=Currency.USD,
            policy=RefundPolicy.ORIGINAL_RATE,
        )

        result = calc.calculate(txn, req)

        # 100 * 0.18005 = 18.005 -> ROUND_HALF_UP -> 18.01
        expected = Decimal("18.005").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert expected == Decimal("18.01")
        assert result.destination_amount == Decimal("18.01")
