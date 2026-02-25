from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from src.enums import Currency, RefundStatus, RiskLevel
from src.exchange.rate_provider import RateProvider
from src.models import RefundResult, RiskConfig, RiskFlag, Transaction

# Rough USD conversion factors: multiply by this to get USD equivalent.
_USD_CONVERSION: dict[Currency, Decimal] = {
    Currency.USD: Decimal("1"),
    Currency.EUR: Decimal("1.09"),
    Currency.BRL: Decimal("1") / Decimal("5.2"),
    Currency.MXN: Decimal("1") / Decimal("19.5"),
    Currency.COP: Decimal("1") / Decimal("4200"),
    Currency.THB: Decimal("1") / Decimal("35"),
}

_ACTIVE_REFUND_STATUSES = {RefundStatus.COMPLETED, RefundStatus.PROCESSING}


class RiskDetector:
    """Assesses risk flags for refund operations."""

    def __init__(self, config: Optional[RiskConfig] = None, rate_provider: Optional[RateProvider] = None) -> None:
        self._config = config if config is not None else RiskConfig()
        self._rate_provider = rate_provider

    def assess(
        self,
        transaction: Transaction,
        refund_result: RefundResult,
        previous_refunds: list[RefundResult],
    ) -> list[RiskFlag]:
        """Assess risk flags for a refund. Returns list of RiskFlag."""
        flags: list[RiskFlag] = []

        self._check_exchange_rate_drift(refund_result, flags)
        self._check_large_refund(refund_result, flags)
        self._check_multiple_refunds(previous_refunds, flags)
        self._check_old_transaction(transaction, flags)

        return flags

    def _check_exchange_rate_drift(
        self, refund_result: RefundResult, flags: list[RiskFlag]
    ) -> None:
        original_rate = refund_result.original_rate
        current_rate = refund_result.current_rate

        if original_rate == Decimal("0"):
            return

        drift = abs(current_rate - original_rate) / original_rate
        threshold = self._config.exchange_rate_drift_threshold

        if drift <= threshold:
            return

        drift_pct = (drift * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        level = RiskLevel.HIGH if drift > threshold * 2 else RiskLevel.MEDIUM

        flags.append(
            RiskFlag(
                level=level,
                reason=(
                    f"Exchange rate has drifted {drift_pct}% "
                    f"since original transaction"
                ),
                details={
                    "original_rate": str(original_rate),
                    "current_rate": str(current_rate),
                    "drift_percentage": str(drift_pct),
                },
            )
        )

    def _check_large_refund(
        self, refund_result: RefundResult, flags: list[RiskFlag]
    ) -> None:
        currency = refund_result.destination_currency
        amount = refund_result.destination_amount

        if self._rate_provider is not None:
            try:
                conversion_factor = self._rate_provider.get_current_rate(currency, Currency.USD)
            except (ValueError, Exception):
                conversion_factor = _USD_CONVERSION.get(currency, Decimal("1"))
        else:
            conversion_factor = _USD_CONVERSION.get(currency, Decimal("1"))
        usd_amount = (amount * conversion_factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        threshold = self._config.large_refund_threshold_usd
        if usd_amount <= threshold:
            return

        level = RiskLevel.HIGH if usd_amount > threshold * 2 else RiskLevel.MEDIUM

        flags.append(
            RiskFlag(
                level=level,
                reason=(
                    f"Refund amount equivalent to ${usd_amount} USD "
                    f"exceeds threshold"
                ),
                details={
                    "destination_amount": str(amount),
                    "destination_currency": currency.value,
                    "usd_equivalent": str(usd_amount),
                    "threshold_usd": str(threshold),
                },
            )
        )

    def _check_multiple_refunds(
        self, previous_refunds: list[RefundResult], flags: list[RiskFlag]
    ) -> None:
        active_count = sum(
            1 for r in previous_refunds if r.status in _ACTIVE_REFUND_STATUSES
        )

        if active_count < 2:
            return

        if active_count >= self._config.max_refunds_per_transaction:
            level = RiskLevel.HIGH
        else:
            level = RiskLevel.MEDIUM

        flags.append(
            RiskFlag(
                level=level,
                reason=f"Transaction has {active_count} previous refunds",
                details={"previous_refund_count": active_count},
            )
        )

    def _check_old_transaction(
        self, transaction: Transaction, flags: list[RiskFlag]
    ) -> None:
        days_old = (datetime.now(timezone.utc) - transaction.timestamp).days

        if days_old <= self._config.old_transaction_days:
            return

        flags.append(
            RiskFlag(
                level=RiskLevel.LOW,
                reason=f"Transaction is {days_old} days old",
                details={
                    "transaction_date": transaction.timestamp.isoformat(),
                    "days_old": days_old,
                },
            )
        )
