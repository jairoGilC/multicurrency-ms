from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.enums import (
    Currency,
    PaymentMethod,
    RefundPolicy,
    RefundStatus,
    RiskLevel,
    TransactionStatus,
    TransactionType,
)
from src.models import RefundResult, RiskConfig, RiskFlag, Transaction
from src.validation.risk_detector import RiskDetector


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def config() -> RiskConfig:
    return RiskConfig()


@pytest.fixture
def detector(config: RiskConfig) -> RiskDetector:
    return RiskDetector(config=config)


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
    )


@pytest.fixture
def refund_result() -> RefundResult:
    return RefundResult(
        request_id="req-001",
        transaction_id="txn-001",
        original_amount=Decimal("500.00"),
        original_currency=Currency.USD,
        refund_amount_before_fees=Decimal("500.00"),
        destination_currency=Currency.BRL,
        destination_amount=Decimal("2600.00"),
        original_rate=Decimal("5.20"),
        current_rate=Decimal("5.20"),
        rate_used=Decimal("5.20"),
        policy_applied=RefundPolicy.ORIGINAL_RATE,
        status=RefundStatus.CALCULATED,
    )


def _make_previous_refund(
    status: RefundStatus = RefundStatus.COMPLETED,
) -> RefundResult:
    return RefundResult(
        request_id="req-prev",
        transaction_id="txn-001",
        original_amount=Decimal("100.00"),
        original_currency=Currency.USD,
        refund_amount_before_fees=Decimal("100.00"),
        destination_currency=Currency.BRL,
        destination_amount=Decimal("520.00"),
        original_rate=Decimal("5.20"),
        current_rate=Decimal("5.20"),
        rate_used=Decimal("5.20"),
        policy_applied=RefundPolicy.ORIGINAL_RATE,
        status=status,
    )


class TestExchangeRateDrift:
    def test_no_drift_no_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        flags = detector.assess(transaction, refund_result, [])
        drift_flags = [f for f in flags if "drift" in f.reason.lower()]
        assert len(drift_flags) == 0

    def test_medium_drift_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.current_rate = Decimal("5.80")  # ~11.5% drift
        flags = detector.assess(transaction, refund_result, [])
        drift_flags = [f for f in flags if "drift" in f.reason.lower()]
        assert len(drift_flags) == 1
        assert drift_flags[0].level == RiskLevel.MEDIUM

    def test_high_drift_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.current_rate = Decimal("6.50")  # ~25% drift > 2x threshold (20%)
        flags = detector.assess(transaction, refund_result, [])
        drift_flags = [f for f in flags if "drift" in f.reason.lower()]
        assert len(drift_flags) == 1
        assert drift_flags[0].level == RiskLevel.HIGH

    def test_drift_below_threshold_no_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.current_rate = Decimal("5.25")  # ~1% drift
        flags = detector.assess(transaction, refund_result, [])
        drift_flags = [f for f in flags if "drift" in f.reason.lower()]
        assert len(drift_flags) == 0


class TestLargeRefundAmount:
    def test_small_refund_no_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.destination_amount = Decimal("500.00")
        refund_result.destination_currency = Currency.USD
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 0

    def test_medium_large_refund_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.destination_amount = Decimal("2500.00")
        refund_result.destination_currency = Currency.USD
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 1
        assert large_flags[0].level == RiskLevel.MEDIUM

    def test_high_large_refund_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.destination_amount = Decimal("5000.00")
        refund_result.destination_currency = Currency.USD
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 1
        assert large_flags[0].level == RiskLevel.HIGH

    def test_brl_conversion(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.destination_amount = Decimal("15600.00")  # 15600/5.2 = 3000 USD
        refund_result.destination_currency = Currency.BRL
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 1
        assert large_flags[0].level == RiskLevel.MEDIUM

    def test_eur_conversion(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        refund_result.destination_amount = Decimal("2000.00")  # 2000*1.09 = 2180 USD
        refund_result.destination_currency = Currency.EUR
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 1
        assert large_flags[0].level == RiskLevel.MEDIUM


class TestMultipleRefunds:
    def test_no_previous_refunds_no_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        flags = detector.assess(transaction, refund_result, [])
        multi_flags = [f for f in flags if "previous refunds" in f.reason.lower()]
        assert len(multi_flags) == 0

    def test_two_previous_refunds_medium_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        previous = [_make_previous_refund(), _make_previous_refund()]
        flags = detector.assess(transaction, refund_result, previous)
        multi_flags = [f for f in flags if "previous refunds" in f.reason.lower()]
        assert len(multi_flags) == 1
        assert multi_flags[0].level == RiskLevel.MEDIUM

    def test_max_refunds_high_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        previous = [_make_previous_refund() for _ in range(3)]
        flags = detector.assess(transaction, refund_result, previous)
        multi_flags = [f for f in flags if "previous refunds" in f.reason.lower()]
        assert len(multi_flags) == 1
        assert multi_flags[0].level == RiskLevel.HIGH

    def test_rejected_refunds_not_counted(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        previous = [
            _make_previous_refund(status=RefundStatus.REJECTED),
            _make_previous_refund(status=RefundStatus.REJECTED),
        ]
        flags = detector.assess(transaction, refund_result, previous)
        multi_flags = [f for f in flags if "previous refunds" in f.reason.lower()]
        assert len(multi_flags) == 0


class TestOldTransaction:
    def test_recent_transaction_no_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        transaction.timestamp = datetime.now(timezone.utc) - timedelta(days=5)
        flags = detector.assess(transaction, refund_result, [])
        old_flags = [f for f in flags if "days old" in f.reason.lower()]
        assert len(old_flags) == 0

    def test_old_transaction_low_flag(
        self,
        detector: RiskDetector,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        transaction.timestamp = datetime.now(timezone.utc) - timedelta(days=60)
        flags = detector.assess(transaction, refund_result, [])
        old_flags = [f for f in flags if "days old" in f.reason.lower()]
        assert len(old_flags) == 1
        assert old_flags[0].level == RiskLevel.LOW


class TestDefaultConfig:
    def test_default_config_used_when_none(self) -> None:
        detector = RiskDetector(config=None)
        assert detector._config.exchange_rate_drift_threshold == Decimal("0.10")
        assert detector._config.large_refund_threshold_usd == Decimal("2000")
        assert detector._config.max_refunds_per_transaction == 3
        assert detector._config.old_transaction_days == 30

    def test_custom_config(self) -> None:
        custom = RiskConfig(
            exchange_rate_drift_threshold=Decimal("0.05"),
            large_refund_threshold_usd=Decimal("500"),
            max_refunds_per_transaction=2,
            old_transaction_days=15,
        )
        detector = RiskDetector(config=custom)
        assert detector._config == custom


class TestRateProviderInjection:
    """RiskDetector uses injected rate_provider for dynamic USD conversion."""

    def test_dynamic_rate_from_provider(
        self,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        """When rate_provider is given, it should use dynamic rates."""

        class MockRateProvider:
            def get_current_rate(self, source: Currency, target: Currency) -> Decimal:
                # Return a known conversion factor: 1 BRL = 0.25 USD
                if source == Currency.BRL and target == Currency.USD:
                    return Decimal("0.25")
                raise ValueError("Unexpected pair")

        # 2600 BRL * 0.25 = 650 USD (below 2000 threshold)
        refund_result.destination_amount = Decimal("2600.00")
        refund_result.destination_currency = Currency.BRL

        detector = RiskDetector(config=None, rate_provider=MockRateProvider())
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 0

    def test_fallback_to_static_when_no_provider(
        self,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        """When rate_provider is None, fall back to static rates."""
        # 15600 BRL / 5.2 (static) = 3000 USD > 2000 threshold
        refund_result.destination_amount = Decimal("15600.00")
        refund_result.destination_currency = Currency.BRL

        detector = RiskDetector(config=None, rate_provider=None)
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 1

    def test_fallback_when_provider_raises(
        self,
        transaction: Transaction,
        refund_result: RefundResult,
    ) -> None:
        """When rate_provider raises ValueError, fall back to static rates."""

        class FailingRateProvider:
            def get_current_rate(self, source: Currency, target: Currency) -> Decimal:
                raise ValueError("Rate unavailable")

        # 15600 BRL / 5.2 (static fallback) = 3000 USD > 2000 threshold
        refund_result.destination_amount = Decimal("15600.00")
        refund_result.destination_currency = Currency.BRL

        detector = RiskDetector(config=None, rate_provider=FailingRateProvider())
        flags = detector.assess(transaction, refund_result, [])
        large_flags = [f for f in flags if "threshold" in f.reason.lower()]
        assert len(large_flags) == 1
