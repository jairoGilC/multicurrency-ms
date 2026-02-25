from decimal import Decimal

from src.enums import Currency, RefundStatus, RiskLevel
from src.models import BatchResult, RefundResult

# Currency symbol mapping for formatted output.
_CURRENCY_SYMBOLS: dict[str, str] = {
    Currency.USD.value: "$",
    Currency.EUR.value: "\u20ac",
    Currency.BRL.value: "R$",
    Currency.MXN.value: "MX$",
    Currency.COP.value: "COL$",
    Currency.THB.value: "\u0e3f",
}


class BatchReportGenerator:
    """Generates formatted summary reports from batch refund results."""

    @staticmethod
    def generate_summary(batch_result: BatchResult) -> str:
        """Generate a human-readable summary report string.

        Includes overall counts, per-currency totals, and details for
        any flagged or rejected refunds.
        """
        lines: list[str] = []

        # Header
        lines.append("=== Batch Refund Processing Report ===")
        lines.append(f"Total Processed: {batch_result.total_processed}")
        lines.append(
            f"Approved: {batch_result.total_approved} | "
            f"Flagged: {batch_result.total_flagged} | "
            f"Rejected: {batch_result.total_rejected}"
        )

        # By currency
        if batch_result.by_currency:
            lines.append("")
            lines.append("By Currency:")
            for currency_code, total in sorted(batch_result.by_currency.items()):
                formatted = _format_currency(total, currency_code)
                lines.append(f"  {currency_code}: {formatted}")

        # Flagged refunds
        flagged = [
            r for r in batch_result.results
            if r.status == RefundStatus.FLAGGED
        ]
        if flagged:
            lines.append("")
            lines.append("Flagged Refunds:")
            for refund in flagged:
                flag_details = _format_risk_flags(refund)
                lines.append(f"  - {refund.id}: {flag_details}")

        # Rejected refunds
        rejected = [
            r for r in batch_result.results
            if r.status == RefundStatus.REJECTED
        ]
        if rejected:
            lines.append("")
            lines.append("Rejected Refunds:")
            for refund in rejected:
                reason = refund.rejection_reason or "Unknown reason"
                lines.append(f"  - {refund.id}: {reason}")

        return "\n".join(lines)


def _format_currency(amount: Decimal, currency_code: str) -> str:
    """Format a monetary amount with its currency symbol."""
    symbol = _CURRENCY_SYMBOLS.get(currency_code, currency_code + " ")
    return f"{symbol}{amount:,.2f}"


def _format_risk_flags(refund: RefundResult) -> str:
    """Summarize risk flags for a single refund."""
    if not refund.risk_flags:
        return "No risk flags"
    parts: list[str] = []
    for flag in refund.risk_flags:
        parts.append(f"{flag.reason} ({flag.level.value})")
    return ", ".join(parts)
