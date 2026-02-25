from decimal import Decimal
from typing import Optional

from src.enums import RefundStatus, TransactionStatus
from src.models import (
    RefundRequest,
    RefundResult,
    Transaction,
    ValidationError,
    ValidationResult,
)

_ELIGIBLE_STATUSES = {TransactionStatus.SUCCESS, TransactionStatus.PARTIALLY_REFUNDED}
_ACTIVE_REFUND_STATUSES = {RefundStatus.COMPLETED, RefundStatus.PROCESSING}


class RefundValidator:
    """Validates refund requests against business rules."""

    def validate(
        self,
        request: RefundRequest,
        transaction: Optional[Transaction],
        previous_refunds: list[RefundResult],
    ) -> ValidationResult:
        """
        Validate a refund request. Returns ValidationResult with is_valid and errors.

        Checks are ordered so that if the transaction is missing, we short-circuit
        since all subsequent checks depend on it.
        """
        errors: list[ValidationError] = []

        if transaction is None:
            errors.append(
                ValidationError(
                    code="TRANSACTION_NOT_FOUND",
                    message="Transaction does not exist",
                )
            )
            return ValidationResult(is_valid=False, errors=errors)

        self._check_transaction_status(transaction, errors)
        self._check_amount(request, transaction, errors)
        self._check_duplicate(request, previous_refunds, errors)

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def _check_transaction_status(
        self, transaction: Transaction, errors: list[ValidationError]
    ) -> None:
        if transaction.status not in _ELIGIBLE_STATUSES:
            errors.append(
                ValidationError(
                    code="TRANSACTION_NOT_ELIGIBLE",
                    message=(
                        f"Transaction status '{transaction.status.value}' "
                        f"is not eligible for refund"
                    ),
                )
            )

    def _check_amount(
        self,
        request: RefundRequest,
        transaction: Transaction,
        errors: list[ValidationError],
    ) -> None:
        if request.requested_amount is not None:
            if request.requested_amount == Decimal("0"):
                errors.append(
                    ValidationError(
                        code="INVALID_AMOUNT",
                        message="Requested amount must not be zero",
                    )
                )
            elif request.requested_amount > transaction.refundable_amount:
                errors.append(
                    ValidationError(
                        code="AMOUNT_EXCEEDS_REMAINING",
                        message=(
                            f"Requested amount {request.requested_amount} exceeds "
                            f"refundable amount {transaction.refundable_amount}"
                        ),
                    )
                )
        else:
            if transaction.refundable_amount <= Decimal("0"):
                errors.append(
                    ValidationError(
                        code="NOTHING_TO_REFUND",
                        message="No refundable amount remaining on this transaction",
                    )
                )

    def _check_duplicate(
        self,
        request: RefundRequest,
        previous_refunds: list[RefundResult],
        errors: list[ValidationError],
    ) -> None:
        for refund in previous_refunds:
            if (
                refund.transaction_id == request.transaction_id
                and refund.original_amount == request.requested_amount
                and refund.status in _ACTIVE_REFUND_STATUSES
            ):
                errors.append(
                    ValidationError(
                        code="DUPLICATE_REFUND",
                        message=(
                            f"A refund for the same amount on transaction "
                            f"'{request.transaction_id}' is already "
                            f"{refund.status.value}"
                        ),
                    )
                )
                break
