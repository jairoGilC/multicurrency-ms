from decimal import Decimal

from src.audit.audit_trail import AuditTrail
from src.enums import Currency, RefundStatus, RiskLevel, TransactionStatus
from src.exchange.rate_provider import RateProvider
from src.models import (
    BatchResult,
    RefundRequest,
    RefundResult,
    RiskConfig,
    Transaction,
)
from src.notifications.notifier import RefundNotifier
from src.refund.calculator import RefundCalculator
from src.storage.repository import (
    RefundRepositoryProtocol,
    TransactionRepositoryProtocol,
)
from src.validation.risk_detector import RiskDetector
from src.validation.validator import RefundValidator


class RefundProcessor:
    """Orchestrates the full refund processing pipeline.

    Coordinates validation, calculation, risk assessment, persistence,
    and notification for individual and batch refund requests.
    """

    def __init__(
        self,
        rate_provider: RateProvider,
        transaction_repo: TransactionRepositoryProtocol,
        refund_repo: RefundRepositoryProtocol,
        risk_config: RiskConfig | None = None,
        notifier: RefundNotifier | None = None,
    ) -> None:
        self._rate_provider = rate_provider
        self._transaction_repo = transaction_repo
        self._refund_repo = refund_repo
        self._notifier = notifier

        self._validator = RefundValidator()
        self._calculator = RefundCalculator(rate_provider)
        self._risk_detector = RiskDetector(config=risk_config, rate_provider=rate_provider)

    # ------------------------------------------------------------------
    # Single refund
    # ------------------------------------------------------------------

    def process_refund(self, request: RefundRequest) -> RefundResult:
        """Execute the full refund processing pipeline.

        Steps:
            1. Look up transaction from repository.
            2. Gather previous refunds for this transaction.
            3. Validate using RefundValidator.
            4. If invalid, return RefundResult with REJECTED status.
            5. Calculate using RefundCalculator.
            6. Assess risk using RiskDetector.
            7. Set status: FLAGGED if any HIGH risk, APPROVED otherwise.
            8. Save to refund repository.
            9. Update transaction total_refunded and status.
            10. Send notification if notifier is provided.
            11. Return result with full audit trail.
        """
        audit = AuditTrail()

        # 1. Look up transaction
        transaction = self._transaction_repo.get(request.transaction_id)

        audit.record(
            action="lookup_transaction",
            details=f"Transaction lookup for {request.transaction_id}",
            data={"found": transaction is not None},
        )

        # 2. Previous refunds
        previous_refunds = self._refund_repo.get_by_transaction(request.transaction_id)

        audit.record(
            action="lookup_previous_refunds",
            details=f"Found {len(previous_refunds)} previous refund(s)",
            data={"count": len(previous_refunds)},
        )

        # 3. Validate
        validation = self._validator.validate(request, transaction, previous_refunds)

        audit.record(
            action="validation",
            details=f"Validation result: {'PASS' if validation.is_valid else 'FAIL'}",
            data={
                "is_valid": validation.is_valid,
                "errors": [e.model_dump() for e in validation.errors],
            },
        )

        # 4. Reject if invalid
        if not validation.is_valid:
            rejection_reason = "; ".join(e.message for e in validation.errors)
            result = self._build_rejected_result(request, transaction, rejection_reason, audit)
            self._refund_repo.save(result)
            self._send_notification(result, "REFUND_REJECTED")
            return result

        # From here, transaction is guaranteed to be non-None
        assert transaction is not None

        # 5. Calculate
        result = self._calculator.calculate(transaction, request)

        audit.record(
            action="calculation",
            details=(
                f"Calculated refund: {result.destination_amount} "
                f"{result.destination_currency.value}"
            ),
            data={
                "destination_amount": str(result.destination_amount),
                "rate_used": str(result.rate_used),
                "policy": result.policy_applied.value,
            },
        )

        self._send_notification(result, "REFUND_CALCULATED")

        # 6. Assess risk
        risk_flags = self._risk_detector.assess(transaction, result, previous_refunds)

        audit.record(
            action="risk_assessment",
            details=f"Risk flags: {len(risk_flags)}",
            data={
                "flags": [{"level": f.level.value, "reason": f.reason} for f in risk_flags],
            },
        )

        # 7. Determine status
        has_high_risk = any(f.level == RiskLevel.HIGH for f in risk_flags)
        status = RefundStatus.FLAGGED if has_high_risk else RefundStatus.APPROVED

        audit.record(
            action="status_determination",
            details=f"Status set to {status.value}",
            data={"has_high_risk": has_high_risk},
        )

        # Merge audit entries from calculator and our trail
        merged_audit = list(result.audit_entries) + audit.get_entries()

        result = result.model_copy(
            update={
                "status": status,
                "risk_flags": risk_flags,
                "audit_entries": merged_audit,
            }
        )

        # 8. Save refund
        self._refund_repo.save(result)

        # 9. Update transaction
        new_total_refunded = transaction.total_refunded + result.original_amount
        new_tx_status = (
            TransactionStatus.REFUNDED
            if new_total_refunded >= transaction.amount
            else TransactionStatus.PARTIALLY_REFUNDED
        )
        updated_tx = transaction.model_copy(
            update={
                "total_refunded": new_total_refunded,
                "status": new_tx_status,
            }
        )
        self._transaction_repo.update(updated_tx)

        audit.record(
            action="transaction_updated",
            details=(
                f"Transaction {transaction.id} updated: "
                f"total_refunded={new_total_refunded}, status={new_tx_status.value}"
            ),
            data={
                "total_refunded": str(new_total_refunded),
                "transaction_status": new_tx_status.value,
            },
        )

        # 10. Send notification
        event = "REFUND_FLAGGED" if status == RefundStatus.FLAGGED else "REFUND_APPROVED"
        self._send_notification(result, event)

        # 11. Return result
        return result

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def process_batch(self, requests: list[RefundRequest]) -> BatchResult:
        """Process multiple refund requests and aggregate results.

        Returns a ``BatchResult`` with counts and per-currency totals.
        """
        results: list[RefundResult] = []
        total_approved = 0
        total_flagged = 0
        total_rejected = 0
        by_currency: dict[str, Decimal] = {}

        for request in requests:
            result = self.process_refund(request)
            results.append(result)

            if result.status == RefundStatus.APPROVED:
                total_approved += 1
            elif result.status == RefundStatus.FLAGGED:
                total_flagged += 1
            elif result.status == RefundStatus.REJECTED:
                total_rejected += 1

            # Accumulate by currency for non-rejected refunds
            if result.status != RefundStatus.REJECTED:
                currency_code = result.destination_currency.value
                by_currency[currency_code] = (
                    by_currency.get(currency_code, Decimal("0")) + result.destination_amount
                )

        return BatchResult(
            total_processed=len(requests),
            total_approved=total_approved,
            total_flagged=total_flagged,
            total_rejected=total_rejected,
            by_currency=by_currency,
            results=results,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_rejected_result(
        request: RefundRequest,
        transaction: Transaction | None,
        rejection_reason: str,
        audit: AuditTrail,
    ) -> RefundResult:
        """Build a minimal RefundResult with REJECTED status."""
        if transaction is None:
            original_currency = request.destination_currency or Currency.USD
            destination_currency = original_currency
            original_rate = Decimal("0")
            current_rate = Decimal("0")
        else:
            original_currency = transaction.currency
            destination_currency = request.destination_currency or transaction.currency
            original_rate = transaction.exchange_rate_used
            current_rate = original_rate

        audit.record(
            action="rejected",
            details=f"Refund rejected: {rejection_reason}",
        )

        return RefundResult(
            request_id=request.id,
            transaction_id=request.transaction_id,
            original_amount=request.requested_amount or Decimal("0"),
            original_currency=original_currency,
            refund_amount_before_fees=Decimal("0"),
            destination_currency=destination_currency,
            destination_amount=Decimal("0"),
            original_rate=original_rate,
            current_rate=current_rate,
            rate_used=Decimal("0"),
            policy_applied=request.policy,
            status=RefundStatus.REJECTED,
            rejection_reason=rejection_reason,
            audit_entries=audit.get_entries(),
        )

    def _send_notification(self, result: RefundResult, event: str) -> None:
        """Dispatch notification if a notifier is configured."""
        if self._notifier is not None:
            self._notifier.notify(result, event)
