from decimal import ROUND_HALF_UP, Decimal

from src.enums import Currency, FeeType
from src.exchange.rate_provider import RateProvider
from src.models import AppliedFee, Fee


class FeeCalculator:
    """Applies a list of fees to a refund amount.

    Percentage fees are applied first (each against the remaining balance),
    then fixed fees (converted to the refund currency when necessary).
    The net amount never drops below zero.
    """

    def __init__(self, rate_provider: RateProvider) -> None:
        self._rate_provider = rate_provider

    def apply_fees(
        self,
        amount: Decimal,
        currency: Currency,
        fees: list[Fee],
    ) -> tuple[Decimal, list[AppliedFee]]:
        """Apply *fees* to *amount* denominated in *currency*.

        Returns ``(net_amount, applied_fees)`` where *net_amount* is the
        remaining balance after all deductions (floored at zero) and
        *applied_fees* records each individual deduction.
        """
        percentage_fees = [f for f in fees if f.type == FeeType.PERCENTAGE]
        fixed_fees = [f for f in fees if f.type == FeeType.FIXED]

        remaining = amount
        applied: list[AppliedFee] = []

        # --- percentage fees first ---
        for fee in percentage_fees:
            deduction = (remaining * fee.value / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
            deduction = min(deduction, remaining)
            remaining -= deduction
            applied.append(
                AppliedFee(
                    description=fee.description or f"Percentage fee ({fee.value}%)",
                    type=FeeType.PERCENTAGE,
                    original_value=fee.value,
                    deducted_amount=deduction,
                    currency=currency,
                )
            )

        # --- fixed fees second ---
        for fee in fixed_fees:
            fee_currency = fee.currency or currency
            if fee_currency == currency:
                deduction = fee.value
            else:
                conversion_rate = self._rate_provider.get_current_rate(
                    fee_currency, currency,
                )
                deduction = (fee.value * conversion_rate).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP,
                )

            deduction = min(deduction, remaining)
            remaining -= deduction
            applied.append(
                AppliedFee(
                    description=fee.description or f"Fixed fee ({fee.value} {fee_currency.value})",
                    type=FeeType.FIXED,
                    original_value=fee.value,
                    deducted_amount=deduction,
                    currency=currency,
                )
            )

        remaining = max(remaining, Decimal("0"))
        return remaining, applied
