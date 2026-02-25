"""Shared pytest fixtures for the Multi-Currency Refund Engine test suite."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.enums import (
    Currency,
    PaymentMethod,
    RefundPolicy,
    TransactionStatus,
    TransactionType,
)
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import ExchangeRate, RiskConfig, Transaction
from src.notifications.notifier import RefundNotifier
from src.refund.processor import RefundProcessor
from src.storage.repository import RefundRepository, TransactionRepository


_SIXTY_DAYS_AGO = datetime.utcnow() - timedelta(days=60)
_TODAY = datetime.utcnow()


def _build_test_rates() -> list[ExchangeRate]:
    """Build a deterministic set of exchange rates for two dates.

    Rates at ``_TODAY`` are slightly different from ``_SIXTY_DAYS_AGO`` so
    that tests can verify drift-detection logic.
    """
    pairs_60d: list[tuple[Currency, Currency, str]] = [
        # BRL -> USD
        (Currency.BRL, Currency.USD, "0.192"),
        # USD -> BRL (inverse)
        (Currency.USD, Currency.BRL, "5.208"),
        # EUR -> USD
        (Currency.EUR, Currency.USD, "1.090"),
        # USD -> EUR
        (Currency.USD, Currency.EUR, "0.917"),
        # MXN -> USD
        (Currency.MXN, Currency.USD, "0.051"),
        # USD -> MXN
        (Currency.USD, Currency.MXN, "19.500"),
        # COP -> USD
        (Currency.COP, Currency.USD, "0.000238"),
        # USD -> COP
        (Currency.USD, Currency.COP, "4200.00"),
        # THB -> USD
        (Currency.THB, Currency.USD, "0.02857"),
        # USD -> THB
        (Currency.USD, Currency.THB, "35.00"),
    ]

    # Today's rates drift ~3-5 % from 60 days ago
    pairs_today: list[tuple[Currency, Currency, str]] = [
        (Currency.BRL, Currency.USD, "0.200"),
        (Currency.USD, Currency.BRL, "5.000"),
        (Currency.EUR, Currency.USD, "1.120"),
        (Currency.USD, Currency.EUR, "0.893"),
        (Currency.MXN, Currency.USD, "0.053"),
        (Currency.USD, Currency.MXN, "18.870"),
        (Currency.COP, Currency.USD, "0.000245"),
        (Currency.USD, Currency.COP, "4081.63"),
        (Currency.THB, Currency.USD, "0.02941"),
        (Currency.USD, Currency.THB, "34.00"),
    ]

    rates: list[ExchangeRate] = []
    for source, target, value in pairs_60d:
        rates.append(
            ExchangeRate(
                source_currency=source,
                target_currency=target,
                rate=Decimal(value),
                timestamp=_SIXTY_DAYS_AGO,
            )
        )
    for source, target, value in pairs_today:
        rates.append(
            ExchangeRate(
                source_currency=source,
                target_currency=target,
                rate=Decimal(value),
                timestamp=_TODAY,
            )
        )
    return rates


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rate_provider() -> InMemoryRateProvider:
    """InMemoryRateProvider pre-loaded with test rates."""
    provider = InMemoryRateProvider()
    provider.load_rates(_build_test_rates())
    return provider


@pytest.fixture
def sample_transaction() -> Transaction:
    """A known BRL transaction created 60 days ago."""
    return Transaction(
        id="txn-001",
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


@pytest.fixture
def transaction_repo() -> TransactionRepository:
    """Fresh in-memory transaction repository."""
    return TransactionRepository()


@pytest.fixture
def refund_repo() -> RefundRepository:
    """Fresh in-memory refund repository."""
    return RefundRepository()


@pytest.fixture
def notifier() -> RefundNotifier:
    """A RefundNotifier that stores notifications in memory."""
    return RefundNotifier()


@pytest.fixture
def processor(
    rate_provider: InMemoryRateProvider,
    transaction_repo: TransactionRepository,
    refund_repo: RefundRepository,
    notifier: RefundNotifier,
) -> RefundProcessor:
    """RefundProcessor wired with in-memory dependencies."""
    return RefundProcessor(
        rate_provider=rate_provider,
        transaction_repo=transaction_repo,
        refund_repo=refund_repo,
        risk_config=RiskConfig(
            exchange_rate_drift_threshold=Decimal("0.10"),
            large_refund_threshold_usd=Decimal("2000"),
            max_refunds_per_transaction=3,
            old_transaction_days=30,
        ),
        notifier=notifier,
    )
