"""Dependency injection for the FastAPI application."""

from functools import lru_cache
from pathlib import Path

from src.exchange.rate_generator import RateGenerator
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import RiskConfig
from src.notifications.notifier import RefundNotifier
from src.refund.processor import RefundProcessor
from src.storage.repository import RefundRepository, TransactionRepository


@lru_cache
def get_rate_provider() -> InMemoryRateProvider:
    provider = InMemoryRateProvider()
    generator = RateGenerator()
    rates = generator.generate_rates()
    provider.load_rates(rates)
    return provider


@lru_cache
def get_transaction_repo() -> TransactionRepository:
    repo = TransactionRepository()
    # Pre-load transactions from test data if available
    data_path = Path("data/transactions.json")
    if data_path.exists():
        import json as _json
        from datetime import datetime
        from decimal import Decimal

        from src.enums import Currency, PaymentMethod, TransactionStatus, TransactionType
        from src.models import Transaction

        with open(data_path) as f:
            transactions = _json.load(f)
        for t in transactions:
            txn = Transaction(
                id=t["id"],
                customer_id=t["customer_id"],
                amount=Decimal(str(t["amount"])),
                currency=Currency(t["currency"]),
                supplier_currency=Currency(t["supplier_currency"]),
                supplier_amount=Decimal(str(t["supplier_amount"])),
                exchange_rate_used=Decimal(str(t["exchange_rate_used"])),
                transaction_type=TransactionType(t["transaction_type"]),
                payment_method=PaymentMethod(t["payment_method"]),
                timestamp=datetime.fromisoformat(t["timestamp"]),
                status=TransactionStatus(t.get("status", "SUCCESS")),
            )
            repo.save(txn)
    return repo


@lru_cache
def get_refund_repo() -> RefundRepository:
    return RefundRepository()


@lru_cache
def get_notifier() -> RefundNotifier:
    return RefundNotifier()


@lru_cache
def get_processor() -> RefundProcessor:
    return RefundProcessor(
        rate_provider=get_rate_provider(),
        transaction_repo=get_transaction_repo(),
        refund_repo=get_refund_repo(),
        risk_config=RiskConfig(),
        notifier=get_notifier(),
    )
