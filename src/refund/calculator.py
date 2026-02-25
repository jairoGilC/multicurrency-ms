from decimal import ROUND_HALF_UP, Decimal

from src.enums import Currency
from src.exchange.rate_provider import RateProvider
from src.models import (
    AuditEntry,
    RefundRequest,
    RefundResult,
    RefundStatus,
    Transaction,
)
from src.refund.fee_calculator import FeeCalculator
from src.refund.policies import get_policy


class RefundCalculator:
    """Core calculation engine for multi-currency refunds.

    Orchestrates rate selection (via policy), fee deduction, and currency
    conversion to produce a fully-audited ``RefundResult``.
    """

    def __init__(self, rate_provider: RateProvider) -> None:
        self._rate_provider = rate_provider
        self._fee_calculator = FeeCalculator(rate_provider)

    def calculate(
        self,
        transaction: Transaction,
        request: RefundRequest,
    ) -> RefundResult:
        """Calculate the refund for *transaction* given *request*.

        Steps
        -----
        1. Determine refund amount in the customer's original currency.
        2. Determine the destination currency.
        3. Look up original and current exchange rates.
        4. Apply the policy to select the rate.
        5. Apply fees via ``FeeCalculator``.
        6. Convert to the destination currency.
        7. Build and return ``RefundResult`` with full audit trail.
        """
        audit: list[AuditEntry] = []

        # ------------------------------------------------------------------
        # 1. Refund amount in the customer's original currency
        # ------------------------------------------------------------------
        refund_amount = (
            request.requested_amount
            if request.requested_amount is not None
            else transaction.refundable_amount
        )
        refund_amount = min(refund_amount, transaction.refundable_amount)

        audit.append(
            AuditEntry(
                action="determine_refund_amount",
                details=(f"Refund amount determined: {refund_amount} {transaction.currency.value}"),
                data={
                    "requested_amount": str(request.requested_amount),
                    "refundable_amount": str(transaction.refundable_amount),
                    "refund_amount": str(refund_amount),
                },
            )
        )

        # ------------------------------------------------------------------
        # 2. Destination currency
        # ------------------------------------------------------------------
        destination_currency: Currency = (
            request.destination_currency
            if request.destination_currency is not None
            else transaction.currency
        )

        audit.append(
            AuditEntry(
                action="determine_destination_currency",
                details=f"Destination currency: {destination_currency.value}",
                data={"destination_currency": destination_currency.value},
            )
        )

        # ------------------------------------------------------------------
        # 3. Original and current exchange rates
        # ------------------------------------------------------------------
        same_currency = transaction.currency == destination_currency

        if same_currency:
            original_rate = Decimal("1")
            current_rate = Decimal("1")
        else:
            # When the destination matches the supplier currency, the booking
            # rate (transaction.exchange_rate_used) is the correct original
            # rate.  Otherwise, look up the historical rate for the actual
            # currency pair so that policies compare like-for-like rates.
            if destination_currency == transaction.supplier_currency:
                original_rate = transaction.exchange_rate_used
            else:
                original_rate = self._rate_provider.get_rate(
                    transaction.currency,
                    destination_currency,
                    transaction.timestamp,
                )
            current_rate = self._rate_provider.get_current_rate(
                transaction.currency,
                destination_currency,
            )

        audit.append(
            AuditEntry(
                action="rate_lookup",
                details=(f"Original rate: {original_rate}, Current rate: {current_rate}"),
                data={
                    "original_rate": str(original_rate),
                    "current_rate": str(current_rate),
                    "source_currency": transaction.currency.value,
                    "destination_currency": destination_currency.value,
                },
            )
        )

        # ------------------------------------------------------------------
        # 4. Apply policy to select the rate
        # ------------------------------------------------------------------
        days_elapsed = (request.timestamp - transaction.timestamp).days
        policy_strategy = get_policy(request.policy)

        if same_currency:
            rate_used = Decimal("1")
        else:
            rate_used = policy_strategy.calculate_rate(
                original_rate,
                current_rate,
                days_elapsed,
            )

        audit.append(
            AuditEntry(
                action="policy_applied",
                details=(
                    f"Policy '{policy_strategy.name}' selected rate: {rate_used} "
                    f"(days_elapsed={days_elapsed})"
                ),
                data={
                    "policy": request.policy.value,
                    "rate_used": str(rate_used),
                    "days_elapsed": days_elapsed,
                },
            )
        )

        # ------------------------------------------------------------------
        # 5. Apply fees
        # ------------------------------------------------------------------
        after_fees, applied_fees = self._fee_calculator.apply_fees(
            refund_amount,
            transaction.currency,
            request.fees,
        )

        total_fees = refund_amount - after_fees

        audit.append(
            AuditEntry(
                action="fee_application",
                details=(
                    f"Fees applied: {len(applied_fees)} fee(s), "
                    f"total deducted: {total_fees} {transaction.currency.value}"
                ),
                data={
                    "fees_count": len(applied_fees),
                    "total_fees": str(total_fees),
                    "amount_after_fees": str(after_fees),
                },
            )
        )

        # ------------------------------------------------------------------
        # 6. Convert to destination currency
        # ------------------------------------------------------------------
        if same_currency:
            destination_amount = after_fees
        else:
            destination_amount = (after_fees * rate_used).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        audit.append(
            AuditEntry(
                action="conversion",
                details=(
                    f"Converted {after_fees} {transaction.currency.value} -> "
                    f"{destination_amount} {destination_currency.value} "
                    f"at rate {rate_used}"
                ),
                data={
                    "source_amount": str(after_fees),
                    "source_currency": transaction.currency.value,
                    "destination_amount": str(destination_amount),
                    "destination_currency": destination_currency.value,
                    "rate_used": str(rate_used),
                },
            )
        )

        # ------------------------------------------------------------------
        # 7. Build result
        # ------------------------------------------------------------------
        audit.append(
            AuditEntry(
                action="final_calculation",
                details=(
                    f"Refund result: {destination_amount} {destination_currency.value} "
                    f"(original: {refund_amount} {transaction.currency.value})"
                ),
                data={
                    "original_amount": str(refund_amount),
                    "destination_amount": str(destination_amount),
                    "policy": request.policy.value,
                    "rate_used": str(rate_used),
                    "total_fees": str(total_fees),
                },
            )
        )

        return RefundResult(
            request_id=request.id,
            transaction_id=transaction.id,
            original_amount=refund_amount,
            original_currency=transaction.currency,
            refund_amount_before_fees=refund_amount,
            fees_applied=applied_fees,
            total_fees=total_fees,
            refund_amount_after_fees=after_fees,
            destination_currency=destination_currency,
            destination_amount=destination_amount,
            original_rate=original_rate,
            current_rate=current_rate,
            rate_used=rate_used,
            policy_applied=request.policy,
            status=RefundStatus.CALCULATED,
            audit_entries=audit,
        )
