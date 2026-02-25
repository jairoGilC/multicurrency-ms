from datetime import datetime
from decimal import Decimal

import pytest

from src.enums import (
    Currency,
    PaymentMethod,
    RefundPolicy,
    RefundStatus,
    TransactionStatus,
    TransactionType,
)
from src.models import RefundRequest, RefundResult, Transaction, ValidationError, ValidationResult
from src.validation.validator import RefundValidator


@pytest.fixture
def validator() -> RefundValidator:
    return RefundValidator()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 2, 25, 12, 0, 0)


@pytest.fixture
def transaction(now: datetime) -> Transaction:
    return Transaction(
        id="txn-001",
        customer_id="cust-001",
        amount=Decimal("1000.00"),
        currency=Currency.USD,
        supplier_currency=Currency.BRL,
        supplier_amount=Decimal("5200.00"),
        exchange_rate_used=Decimal("5.20"),
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=now,
        status=TransactionStatus.SUCCESS,
        total_refunded=Decimal("0"),
    )


@pytest.fixture
def refund_request() -> RefundRequest:
    return RefundRequest(
        transaction_id="txn-001",
        requested_amount=Decimal("500.00"),
        policy=RefundPolicy.ORIGINAL_RATE,
    )


def _make_refund_result(
    transaction_id: str = "txn-001",
    requested_amount: Decimal = Decimal("500.00"),
    status: RefundStatus = RefundStatus.COMPLETED,
) -> RefundResult:
    return RefundResult(
        request_id="req-001",
        transaction_id=transaction_id,
        original_amount=requested_amount,
        original_currency=Currency.USD,
        refund_amount_before_fees=requested_amount,
        destination_currency=Currency.BRL,
        destination_amount=requested_amount * Decimal("5.20"),
        original_rate=Decimal("5.20"),
        current_rate=Decimal("5.20"),
        rate_used=Decimal("5.20"),
        policy_applied=RefundPolicy.ORIGINAL_RATE,
        status=status,
    )


class TestTransactionExists:
    def test_missing_transaction_fails(
        self, validator: RefundValidator, refund_request: RefundRequest
    ) -> None:
        result = validator.validate(refund_request, None, [])
        assert not result.is_valid
        assert any(e.code == "TRANSACTION_NOT_FOUND" for e in result.errors)

    def test_existing_transaction_passes(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        result = validator.validate(refund_request, transaction, [])
        assert result.is_valid


class TestTransactionStatus:
    def test_success_is_eligible(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        transaction.status = TransactionStatus.SUCCESS
        result = validator.validate(refund_request, transaction, [])
        assert result.is_valid

    def test_partially_refunded_is_eligible(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        transaction.status = TransactionStatus.PARTIALLY_REFUNDED
        transaction.total_refunded = Decimal("200.00")
        result = validator.validate(refund_request, transaction, [])
        assert result.is_valid

    def test_failed_is_not_eligible(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        transaction.status = TransactionStatus.FAILED
        result = validator.validate(refund_request, transaction, [])
        assert not result.is_valid
        assert any(e.code == "TRANSACTION_NOT_ELIGIBLE" for e in result.errors)

    def test_refunded_is_not_eligible(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        transaction.status = TransactionStatus.REFUNDED
        result = validator.validate(refund_request, transaction, [])
        assert not result.is_valid
        assert any(e.code == "TRANSACTION_NOT_ELIGIBLE" for e in result.errors)


class TestAmountExceedsRemaining:
    def test_amount_within_refundable(
        self,
        validator: RefundValidator,
        transaction: Transaction,
    ) -> None:
        request = RefundRequest(
            transaction_id="txn-001",
            requested_amount=Decimal("1000.00"),
        )
        result = validator.validate(request, transaction, [])
        assert result.is_valid

    def test_amount_exceeds_refundable(
        self,
        validator: RefundValidator,
        transaction: Transaction,
    ) -> None:
        transaction.total_refunded = Decimal("800.00")
        request = RefundRequest(
            transaction_id="txn-001",
            requested_amount=Decimal("300.00"),
        )
        result = validator.validate(request, transaction, [])
        assert not result.is_valid
        assert any(e.code == "AMOUNT_EXCEEDS_REMAINING" for e in result.errors)


class TestNothingToRefund:
    def test_full_refund_with_zero_refundable(
        self,
        validator: RefundValidator,
        transaction: Transaction,
    ) -> None:
        transaction.total_refunded = Decimal("1000.00")
        transaction.status = TransactionStatus.PARTIALLY_REFUNDED
        request = RefundRequest(
            transaction_id="txn-001",
            requested_amount=None,
        )
        result = validator.validate(request, transaction, [])
        assert not result.is_valid
        assert any(e.code == "NOTHING_TO_REFUND" for e in result.errors)

    def test_full_refund_with_positive_refundable(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        request = RefundRequest(
            transaction_id="txn-001",
            requested_amount=None,
        )
        result = validator.validate(request, transaction, [])
        assert result.is_valid


class TestDuplicateRefund:
    def test_duplicate_completed_refund(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        previous = [_make_refund_result(status=RefundStatus.COMPLETED)]
        result = validator.validate(refund_request, transaction, previous)
        assert not result.is_valid
        assert any(e.code == "DUPLICATE_REFUND" for e in result.errors)

    def test_duplicate_processing_refund(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        previous = [_make_refund_result(status=RefundStatus.PROCESSING)]
        result = validator.validate(refund_request, transaction, previous)
        assert not result.is_valid
        assert any(e.code == "DUPLICATE_REFUND" for e in result.errors)

    def test_rejected_refund_is_not_duplicate(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        previous = [_make_refund_result(status=RefundStatus.REJECTED)]
        result = validator.validate(refund_request, transaction, previous)
        assert result.is_valid

    def test_different_amount_is_not_duplicate(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        previous = [
            _make_refund_result(
                requested_amount=Decimal("200.00"),
                status=RefundStatus.COMPLETED,
            )
        ]
        result = validator.validate(refund_request, transaction, previous)
        assert result.is_valid

    def test_different_transaction_is_not_duplicate(
        self,
        validator: RefundValidator,
        refund_request: RefundRequest,
        transaction: Transaction,
    ) -> None:
        previous = [
            _make_refund_result(
                transaction_id="txn-999",
                status=RefundStatus.COMPLETED,
            )
        ]
        result = validator.validate(refund_request, transaction, previous)
        assert result.is_valid


class TestInvalidAmount:
    def test_zero_amount_is_invalid(
        self,
        validator: RefundValidator,
        transaction: Transaction,
    ) -> None:
        """RefundRequest validator rejects zero, but if bypassed, our validator catches it."""
        request = RefundRequest.model_construct(
            id="req-zero",
            transaction_id="txn-001",
            requested_amount=Decimal("0"),
            destination_currency=None,
            policy=RefundPolicy.ORIGINAL_RATE,
            fees=[],
            timestamp=datetime.utcnow(),
        )
        result = validator.validate(request, transaction, [])
        assert not result.is_valid
        assert any(e.code == "INVALID_AMOUNT" for e in result.errors)


class TestMultipleErrors:
    def test_collects_all_errors(self, validator: RefundValidator) -> None:
        """When transaction is None, only TRANSACTION_NOT_FOUND should be returned
        since other checks depend on the transaction."""
        request = RefundRequest(
            transaction_id="txn-001",
            requested_amount=Decimal("500.00"),
        )
        result = validator.validate(request, None, [])
        assert not result.is_valid
        assert len(result.errors) >= 1
        assert result.errors[0].code == "TRANSACTION_NOT_FOUND"
