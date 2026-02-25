"""Tests for the RefundProcessor orchestration layer."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.enums import (
    Currency,
    RefundPolicy,
    RefundStatus,
    TransactionStatus,
    TransactionType,
    PaymentMethod,
)
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import RefundRequest, RiskConfig, Transaction
from src.notifications.notifier import RefundNotifier
from src.refund.processor import RefundProcessor
from src.storage.repository import RefundRepository, TransactionRepository


_SIXTY_DAYS_AGO = datetime.utcnow() - timedelta(days=60)
_NOW = datetime.utcnow()


def _make_transaction(**overrides) -> Transaction:
    defaults = dict(
        id="txn-proc-001",
        customer_id="cust-001",
        amount=Decimal("1000"),
        currency=Currency.BRL,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("192"),
        exchange_rate_used=Decimal("0.192"),
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=_SIXTY_DAYS_AGO,
        status=TransactionStatus.SUCCESS,
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def _save_transaction(
    repo: TransactionRepository, **overrides
) -> Transaction:
    txn = _make_transaction(**overrides)
    repo.save(txn)
    return txn


class TestRefundProcessorFullFlow:
    """Successful full refund: validate -> calculate -> approve -> save."""

    def test_successful_full_refund(
        self,
        processor: RefundProcessor,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
        notifier: RefundNotifier,
    ) -> None:
        txn = _save_transaction(transaction_repo)
        req = RefundRequest(
            transaction_id=txn.id,
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )

        result = processor.process_refund(req)

        # Status should be APPROVED (or FLAGGED if risk detected -- old txn triggers LOW flag only)
        assert result.status in (RefundStatus.APPROVED, RefundStatus.FLAGGED)
        assert result.transaction_id == txn.id
        assert result.original_amount == Decimal("1000")
        assert result.destination_currency == Currency.BRL

        # Persisted in the refund repo
        stored = refund_repo.get(result.id)
        assert stored is not None
        assert stored.id == result.id

        # Transaction status updated
        updated_txn = transaction_repo.get(txn.id)
        assert updated_txn is not None
        assert updated_txn.total_refunded == Decimal("1000")
        assert updated_txn.status == TransactionStatus.REFUNDED

        # Notifications were sent
        notes = notifier.get_notifications()
        assert len(notes) >= 1


class TestRefundProcessorRejection:
    """Rejected refund when the transaction doesn't exist."""

    def test_rejected_for_missing_transaction(
        self,
        processor: RefundProcessor,
        refund_repo: RefundRepository,
        notifier: RefundNotifier,
    ) -> None:
        req = RefundRequest(
            transaction_id="non-existent-txn",
            requested_amount=Decimal("500"),
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )

        result = processor.process_refund(req)

        assert result.status == RefundStatus.REJECTED
        assert result.rejection_reason is not None
        assert "does not exist" in result.rejection_reason

        # Still saved
        stored = refund_repo.get(result.id)
        assert stored is not None

        # Notification sent with REJECTED event
        events = [n["event"] for n in notifier.get_notifications()]
        assert "REFUND_REJECTED" in events


class TestRefundProcessorFlagged:
    """Flagged refund when exchange rate drift exceeds threshold."""

    def test_flagged_for_high_drift(
        self,
        rate_provider: InMemoryRateProvider,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
        notifier: RefundNotifier,
    ) -> None:
        # Use a very low drift threshold so the normal ~4% drift triggers HIGH
        processor = RefundProcessor(
            rate_provider=rate_provider,
            transaction_repo=transaction_repo,
            refund_repo=refund_repo,
            risk_config=RiskConfig(
                exchange_rate_drift_threshold=Decimal("0.01"),
            ),
            notifier=notifier,
        )

        txn = _save_transaction(transaction_repo)
        req = RefundRequest(
            transaction_id=txn.id,
            destination_currency=Currency.USD,
            policy=RefundPolicy.CURRENT_RATE,
            timestamp=_NOW,
        )

        result = processor.process_refund(req)

        assert result.status == RefundStatus.FLAGGED
        assert any(f.reason for f in result.risk_flags)

        events = [n["event"] for n in notifier.get_notifications()]
        assert "REFUND_FLAGGED" in events


class TestTransactionStatusUpdates:
    """Transaction status transitions correctly with partial and full refunds."""

    def test_partial_then_full_refund(
        self,
        processor: RefundProcessor,
        transaction_repo: TransactionRepository,
    ) -> None:
        txn = _save_transaction(transaction_repo)

        # First: partial refund of 400
        req1 = RefundRequest(
            transaction_id=txn.id,
            requested_amount=Decimal("400"),
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result1 = processor.process_refund(req1)
        assert result1.status in (RefundStatus.APPROVED, RefundStatus.FLAGGED)

        updated = transaction_repo.get(txn.id)
        assert updated is not None
        assert updated.total_refunded == Decimal("400")
        assert updated.status == TransactionStatus.PARTIALLY_REFUNDED

        # Second: refund remaining 600
        req2 = RefundRequest(
            transaction_id=txn.id,
            requested_amount=Decimal("600"),
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result2 = processor.process_refund(req2)
        assert result2.status in (RefundStatus.APPROVED, RefundStatus.FLAGGED)

        updated2 = transaction_repo.get(txn.id)
        assert updated2 is not None
        assert updated2.total_refunded == Decimal("1000")
        assert updated2.status == TransactionStatus.REFUNDED


class TestNotificationOnStatusChange:
    """A notification is sent for each refund status determination."""

    def test_notification_per_status_change(
        self,
        processor: RefundProcessor,
        transaction_repo: TransactionRepository,
        notifier: RefundNotifier,
    ) -> None:
        txn = _save_transaction(transaction_repo)
        req = RefundRequest(
            transaction_id=txn.id,
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )

        processor.process_refund(req)

        notifications = notifier.get_notifications()
        # Should have at least REFUND_CALCULATED and REFUND_APPROVED/FLAGGED
        events = [n["event"] for n in notifications]
        assert "REFUND_CALCULATED" in events
        assert any(e in ("REFUND_APPROVED", "REFUND_FLAGGED") for e in events)


class TestSecondRefundOnSameTransaction:
    """A second refund on the same transaction works when amount is available."""

    def test_second_refund_succeeds(
        self,
        processor: RefundProcessor,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
    ) -> None:
        txn = _save_transaction(transaction_repo)

        req1 = RefundRequest(
            transaction_id=txn.id,
            requested_amount=Decimal("300"),
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result1 = processor.process_refund(req1)
        assert result1.status != RefundStatus.REJECTED

        req2 = RefundRequest(
            transaction_id=txn.id,
            requested_amount=Decimal("200"),
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result2 = processor.process_refund(req2)
        assert result2.status != RefundStatus.REJECTED

        # Both should be saved
        all_refunds = refund_repo.get_by_transaction(txn.id)
        assert len(all_refunds) == 2

        updated = transaction_repo.get(txn.id)
        assert updated is not None
        assert updated.total_refunded == Decimal("500")
