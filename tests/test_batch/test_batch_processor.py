"""Tests for the BatchReportGenerator."""

from decimal import Decimal

from src.batch.batch_processor import BatchReportGenerator
from src.enums import Currency, RefundPolicy, RefundStatus, RiskLevel
from src.models import BatchResult, RefundResult, RiskFlag


def _make_result(
    *,
    status: RefundStatus = RefundStatus.APPROVED,
    dest_currency: Currency = Currency.BRL,
    dest_amount: Decimal = Decimal("500"),
    risk_flags: list[RiskFlag] | None = None,
    rejection_reason: str | None = None,
) -> RefundResult:
    """Build a minimal RefundResult for batch report tests."""
    return RefundResult(
        request_id="req-001",
        transaction_id="txn-001",
        original_amount=Decimal("1000"),
        original_currency=Currency.BRL,
        refund_amount_before_fees=Decimal("1000"),
        destination_currency=dest_currency,
        destination_amount=dest_amount,
        original_rate=Decimal("0.192"),
        current_rate=Decimal("0.200"),
        rate_used=Decimal("0.192"),
        policy_applied=RefundPolicy.ORIGINAL_RATE,
        status=status,
        risk_flags=risk_flags or [],
        rejection_reason=rejection_reason,
    )


class TestBatchReportGeneratorMixed:
    """generate_summary with a mix of approved, flagged, and rejected."""

    def test_mixed_summary(self) -> None:
        results = [
            _make_result(status=RefundStatus.APPROVED, dest_amount=Decimal("500")),
            _make_result(
                status=RefundStatus.FLAGGED,
                dest_amount=Decimal("300"),
                risk_flags=[RiskFlag(level=RiskLevel.HIGH, reason="High drift")],
            ),
            _make_result(
                status=RefundStatus.REJECTED,
                dest_amount=Decimal("0"),
                rejection_reason="Transaction not found",
            ),
        ]

        batch = BatchResult(
            total_processed=3,
            total_approved=1,
            total_flagged=1,
            total_rejected=1,
            by_currency={Currency.BRL.value: Decimal("800")},
            results=results,
        )

        report = BatchReportGenerator.generate_summary(batch)

        assert "Total Processed: 3" in report
        assert "Approved: 1" in report
        assert "Flagged: 1" in report
        assert "Rejected: 1" in report
        assert "BRL" in report
        assert "High drift" in report
        assert "Transaction not found" in report


class TestBatchAllApproved:
    """Batch where all items are approved."""

    def test_all_approved(self) -> None:
        results = [
            _make_result(status=RefundStatus.APPROVED, dest_amount=Decimal("200")),
            _make_result(
                status=RefundStatus.APPROVED,
                dest_amount=Decimal("300"),
                dest_currency=Currency.USD,
            ),
        ]

        batch = BatchResult(
            total_processed=2,
            total_approved=2,
            total_flagged=0,
            total_rejected=0,
            by_currency={
                Currency.BRL.value: Decimal("200"),
                Currency.USD.value: Decimal("300"),
            },
            results=results,
        )

        report = BatchReportGenerator.generate_summary(batch)

        assert "Approved: 2" in report
        assert "Flagged: 0" in report
        assert "Rejected: 0" in report
        # No "Flagged Refunds:" or "Rejected Refunds:" sections
        assert "Flagged Refunds:" not in report
        assert "Rejected Refunds:" not in report


class TestBatchFlaggedAndRejected:
    """Batch with flagged and rejected items includes detail sections."""

    def test_flagged_and_rejected_details(self) -> None:
        flagged_result = _make_result(
            status=RefundStatus.FLAGGED,
            dest_amount=Decimal("1500"),
            risk_flags=[
                RiskFlag(level=RiskLevel.HIGH, reason="Exchange rate drift 15%"),
                RiskFlag(level=RiskLevel.MEDIUM, reason="Large refund amount"),
            ],
        )
        rejected_result = _make_result(
            status=RefundStatus.REJECTED,
            dest_amount=Decimal("0"),
            rejection_reason="Amount exceeds refundable",
        )

        batch = BatchResult(
            total_processed=2,
            total_approved=0,
            total_flagged=1,
            total_rejected=1,
            by_currency={Currency.BRL.value: Decimal("1500")},
            results=[flagged_result, rejected_result],
        )

        report = BatchReportGenerator.generate_summary(batch)

        assert "Flagged Refunds:" in report
        assert "Exchange rate drift 15%" in report
        assert "Large refund amount" in report
        assert "Rejected Refunds:" in report
        assert "Amount exceeds refundable" in report


class TestByCurrencyTotals:
    """By-currency totals appear in the report."""

    def test_currency_totals_formatted(self) -> None:
        batch = BatchResult(
            total_processed=3,
            total_approved=3,
            total_flagged=0,
            total_rejected=0,
            by_currency={
                Currency.BRL.value: Decimal("1500.50"),
                Currency.USD.value: Decimal("200.00"),
                Currency.EUR.value: Decimal("350.75"),
            },
            results=[],
        )

        report = BatchReportGenerator.generate_summary(batch)

        assert "By Currency:" in report
        assert "BRL" in report
        assert "USD" in report
        assert "EUR" in report
        # Check amounts appear formatted
        assert "1,500.50" in report
        assert "200.00" in report
        assert "350.75" in report


class TestReportIncludesAllSections:
    """A full report includes header, currency, flagged, and rejected sections."""

    def test_all_sections_present(self) -> None:
        flagged = _make_result(
            status=RefundStatus.FLAGGED,
            dest_amount=Decimal("100"),
            risk_flags=[RiskFlag(level=RiskLevel.HIGH, reason="Drift")],
        )
        rejected = _make_result(
            status=RefundStatus.REJECTED,
            dest_amount=Decimal("0"),
            rejection_reason="Invalid",
        )
        approved = _make_result(
            status=RefundStatus.APPROVED,
            dest_amount=Decimal("250"),
        )

        batch = BatchResult(
            total_processed=3,
            total_approved=1,
            total_flagged=1,
            total_rejected=1,
            by_currency={Currency.BRL.value: Decimal("350")},
            results=[approved, flagged, rejected],
        )

        report = BatchReportGenerator.generate_summary(batch)

        # Header
        assert "=== Batch Refund Processing Report ===" in report
        assert "Total Processed: 3" in report
        # By currency
        assert "By Currency:" in report
        # Flagged section
        assert "Flagged Refunds:" in report
        # Rejected section
        assert "Rejected Refunds:" in report
