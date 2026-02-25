"""End-to-end integration tests for the Multi-Currency Refund Engine."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.enums import (
    Currency,
    FeeType,
    PaymentMethod,
    RefundPolicy,
    RefundStatus,
    TransactionStatus,
    TransactionType,
)
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import (
    ExchangeRate,
    Fee,
    RefundRequest,
    RiskConfig,
    Transaction,
)
from src.notifications.notifier import RefundNotifier
from src.refund.processor import RefundProcessor
from src.storage.repository import RefundRepository, TransactionRepository


_SIXTY_DAYS_AGO = datetime.now(timezone.utc) - timedelta(days=60)
_NOW = datetime.now(timezone.utc)


class TestCompleteRefundFlow:
    """Full flow: create transaction -> process refund -> verify audit trail."""

    def test_complete_flow(
        self,
        rate_provider: InMemoryRateProvider,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
        notifier: RefundNotifier,
        processor: RefundProcessor,
    ) -> None:
        # 1. Create and save a transaction
        txn = Transaction(
            id="txn-e2e-001",
            customer_id="cust-e2e",
            amount=Decimal("2000"),
            currency=Currency.BRL,
            supplier_currency=Currency.USD,
            supplier_amount=Decimal("384"),
            exchange_rate_used=Decimal("0.192"),
            transaction_type=TransactionType.HOTEL,
            payment_method=PaymentMethod.CREDIT_CARD,
            timestamp=_SIXTY_DAYS_AGO,
            status=TransactionStatus.SUCCESS,
        )
        transaction_repo.save(txn)

        # 2. Process a full refund to the original currency
        req = RefundRequest(
            transaction_id=txn.id,
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result = processor.process_refund(req)

        # 3. Verify the result
        assert result.status in (RefundStatus.APPROVED, RefundStatus.FLAGGED)
        assert result.original_amount == Decimal("2000")
        assert result.destination_currency == Currency.BRL
        assert result.destination_amount == Decimal("2000")

        # 4. Verify audit trail exists and has entries
        assert len(result.audit_entries) > 0
        actions = [e.action for e in result.audit_entries]
        assert "determine_refund_amount" in actions
        assert "lookup_transaction" in actions

        # 5. Verify transaction status
        updated_txn = transaction_repo.get(txn.id)
        assert updated_txn is not None
        assert updated_txn.status == TransactionStatus.REFUNDED
        assert updated_txn.total_refunded == Decimal("2000")

        # 6. Verify persisted refund
        stored = refund_repo.get(result.id)
        assert stored is not None

        # 7. Verify notifications were sent
        assert len(notifier.get_notifications()) >= 1


class TestMultiplePartialRefundsUntilFull:
    """Multiple partial refunds until the transaction is fully refunded."""

    def test_partial_refunds_exhaust_amount(
        self,
        rate_provider: InMemoryRateProvider,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
        processor: RefundProcessor,
    ) -> None:
        txn = Transaction(
            id="txn-e2e-partial",
            customer_id="cust-e2e",
            amount=Decimal("900"),
            currency=Currency.BRL,
            supplier_currency=Currency.USD,
            supplier_amount=Decimal("172.80"),
            exchange_rate_used=Decimal("0.192"),
            transaction_type=TransactionType.FLIGHT,
            payment_method=PaymentMethod.BANK_TRANSFER,
            timestamp=_SIXTY_DAYS_AGO,
            status=TransactionStatus.SUCCESS,
        )
        transaction_repo.save(txn)

        refund_amounts = [Decimal("300"), Decimal("300"), Decimal("300")]
        results = []

        for amount in refund_amounts:
            req = RefundRequest(
                transaction_id=txn.id,
                requested_amount=amount,
                policy=RefundPolicy.ORIGINAL_RATE,
                timestamp=_NOW,
            )
            result = processor.process_refund(req)
            results.append(result)

        # All three should succeed
        for r in results:
            assert r.status != RefundStatus.REJECTED

        # Transaction should be fully refunded
        final_txn = transaction_repo.get(txn.id)
        assert final_txn is not None
        assert final_txn.total_refunded == Decimal("900")
        assert final_txn.status == TransactionStatus.REFUNDED

        # All refunds stored
        all_refunds = refund_repo.get_by_transaction(txn.id)
        assert len(all_refunds) == 3


class TestBatchMixedOutcomes:
    """Batch of 5 refunds with mixed outcomes."""

    def test_batch_mixed(
        self,
        rate_provider: InMemoryRateProvider,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
        notifier: RefundNotifier,
    ) -> None:
        # Use a processor with very low drift threshold to trigger flagging
        processor = RefundProcessor(
            rate_provider=rate_provider,
            transaction_repo=transaction_repo,
            refund_repo=refund_repo,
            risk_config=RiskConfig(
                exchange_rate_drift_threshold=Decimal("0.01"),
                large_refund_threshold_usd=Decimal("2000"),
            ),
            notifier=notifier,
        )

        # Create 4 valid transactions + 1 missing
        transactions = []
        for i in range(4):
            txn = Transaction(
                id=f"txn-batch-{i}",
                customer_id=f"cust-{i}",
                amount=Decimal("500"),
                currency=Currency.BRL,
                supplier_currency=Currency.USD,
                supplier_amount=Decimal("96"),
                exchange_rate_used=Decimal("0.192"),
                transaction_type=TransactionType.FLIGHT,
                payment_method=PaymentMethod.CREDIT_CARD,
                timestamp=_SIXTY_DAYS_AGO,
                status=TransactionStatus.SUCCESS,
            )
            transaction_repo.save(txn)
            transactions.append(txn)

        requests = [
            # Approved (same currency, no drift issue)
            RefundRequest(
                transaction_id="txn-batch-0",
                policy=RefundPolicy.ORIGINAL_RATE,
                timestamp=_NOW,
            ),
            # Flagged (cross-currency with low drift threshold)
            RefundRequest(
                transaction_id="txn-batch-1",
                destination_currency=Currency.USD,
                policy=RefundPolicy.CURRENT_RATE,
                timestamp=_NOW,
            ),
            # Approved (same currency)
            RefundRequest(
                transaction_id="txn-batch-2",
                policy=RefundPolicy.ORIGINAL_RATE,
                timestamp=_NOW,
            ),
            # Flagged (cross-currency)
            RefundRequest(
                transaction_id="txn-batch-3",
                destination_currency=Currency.USD,
                policy=RefundPolicy.CURRENT_RATE,
                timestamp=_NOW,
            ),
            # Rejected (missing transaction)
            RefundRequest(
                transaction_id="txn-batch-missing",
                requested_amount=Decimal("100"),
                policy=RefundPolicy.ORIGINAL_RATE,
                timestamp=_NOW,
            ),
        ]

        batch_result = processor.process_batch(requests)

        assert batch_result.total_processed == 5
        assert batch_result.total_rejected >= 1

        # At least some non-rejected
        non_rejected = [
            r for r in batch_result.results
            if r.status != RefundStatus.REJECTED
        ]
        assert len(non_rejected) >= 2

        # by_currency should have entries for non-rejected
        assert len(batch_result.by_currency) >= 1


class TestDuplicateRefundAfterFullRefund:
    """After a full refund, a second full refund should be rejected (nothing to refund)."""

    def test_duplicate_rejection(
        self,
        rate_provider: InMemoryRateProvider,
        transaction_repo: TransactionRepository,
        refund_repo: RefundRepository,
        processor: RefundProcessor,
    ) -> None:
        txn = Transaction(
            id="txn-e2e-dup",
            customer_id="cust-dup",
            amount=Decimal("500"),
            currency=Currency.BRL,
            supplier_currency=Currency.USD,
            supplier_amount=Decimal("96"),
            exchange_rate_used=Decimal("0.192"),
            transaction_type=TransactionType.TOUR_PACKAGE,
            payment_method=PaymentMethod.DIGITAL_WALLET,
            timestamp=_SIXTY_DAYS_AGO,
            status=TransactionStatus.SUCCESS,
        )
        transaction_repo.save(txn)

        # First full refund succeeds
        req1 = RefundRequest(
            transaction_id=txn.id,
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result1 = processor.process_refund(req1)
        assert result1.status != RefundStatus.REJECTED

        # Second full refund should be rejected (transaction is now REFUNDED)
        req2 = RefundRequest(
            transaction_id=txn.id,
            policy=RefundPolicy.ORIGINAL_RATE,
            timestamp=_NOW,
        )
        result2 = processor.process_refund(req2)

        assert result2.status == RefundStatus.REJECTED
        assert result2.rejection_reason is not None
