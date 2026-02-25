"""
Test data generation script for the Multi-Currency Refund Engine.

Generates exchange rates, transactions, and refund requests as JSON files.
Run from project root: python3 data/generate_test_data.py
"""

import json
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# Allow imports from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.enums import (
    Currency,
    FeeType,
    PaymentMethod,
    RefundPolicy,
    TransactionStatus,
    TransactionType,
)
from src.exchange.rate_generator import RateGenerator

DATA_DIR = Path(__file__).resolve().parent

EXCHANGE_RATES_PATH = DATA_DIR / "exchange_rates.json"
TRANSACTIONS_PATH = DATA_DIR / "transactions.json"
REFUND_REQUESTS_PATH = DATA_DIR / "refund_requests.json"

# Rough USD equivalent multipliers for generating realistic amounts per currency
USD_EQUIVALENT_MULTIPLIERS = {
    Currency.USD: Decimal("1"),
    Currency.EUR: Decimal("0.92"),
    Currency.BRL: Decimal("5.20"),
    Currency.MXN: Decimal("19.50"),
    Currency.COP: Decimal("4200"),
    Currency.THB: Decimal("35.0"),
}


class DecimalEncoder(json.JSONEncoder):
    """Serialize Decimal as string in JSON."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# ---------------------------------------------------------------------------
# Rate helpers
# ---------------------------------------------------------------------------

def _build_rate_lookup(
    rates: list,
) -> dict[tuple[str, str, str], Decimal]:
    """Build a lookup dict: (source, target, date_str) -> rate."""
    lookup: dict[tuple[str, str, str], Decimal] = {}
    for r in rates:
        date_str = r.timestamp.strftime("%Y-%m-%d")
        lookup[(r.source_currency.value, r.target_currency.value, date_str)] = r.rate
    return lookup


def _get_rate(
    lookup: dict[tuple[str, str, str], Decimal],
    source: Currency,
    target: Currency,
    date: datetime,
) -> Decimal:
    """Get exchange rate for a given pair and date.

    Falls back to nearest available date within +-5 days if exact match missing.
    """
    if source == target:
        return Decimal("1.000000")

    date_str = date.strftime("%Y-%m-%d")
    key = (source.value, target.value, date_str)
    if key in lookup:
        return lookup[key]

    # Fallback: search nearby dates
    for offset in range(1, 6):
        for delta in (timedelta(days=offset), timedelta(days=-offset)):
            alt_date = (date + delta).strftime("%Y-%m-%d")
            alt_key = (source.value, target.value, alt_date)
            if alt_key in lookup:
                return lookup[alt_key]

    raise ValueError(
        f"No rate found for {source.value}->{target.value} near {date_str}"
    )


# ---------------------------------------------------------------------------
# Transaction generation
# ---------------------------------------------------------------------------

# Currency distribution
CURRENCY_DISTRIBUTION: list[tuple[Currency, int]] = [
    (Currency.USD, 15),
    (Currency.EUR, 10),
    (Currency.BRL, 10),
    (Currency.MXN, 8),
    (Currency.COP, 4),
    (Currency.THB, 3),
]

# Transaction type distribution
TYPE_DISTRIBUTION: list[tuple[TransactionType, int]] = [
    (TransactionType.FLIGHT, 20),
    (TransactionType.HOTEL, 20),
    (TransactionType.TOUR_PACKAGE, 10),
]

# Payment method distribution
PAYMENT_DISTRIBUTION: list[tuple[PaymentMethod, int]] = [
    (PaymentMethod.CREDIT_CARD, 25),
    (PaymentMethod.BANK_TRANSFER, 15),
    (PaymentMethod.DIGITAL_WALLET, 10),
]

# Possible supplier currencies for cross-currency scenarios
SUPPLIER_CURRENCIES: dict[Currency, list[Currency]] = {
    Currency.USD: [Currency.USD],
    Currency.EUR: [Currency.USD, Currency.EUR],
    Currency.BRL: [Currency.USD, Currency.EUR],
    Currency.MXN: [Currency.USD],
    Currency.COP: [Currency.USD],
    Currency.THB: [Currency.USD],
}


def _build_weighted_list(distribution: list[tuple]) -> list:
    """Expand (item, count) pairs into a flat list for random.choice."""
    result = []
    for item, count in distribution:
        result.extend([item] * count)
    return result


def generate_transactions(
    rate_lookup: dict[tuple[str, str, str], Decimal],
    now: datetime,
) -> list[dict]:
    """Generate 50 transactions with deterministic IDs."""
    random.seed(42)

    # Build exact-count lists and shuffle for deterministic but mixed ordering
    currency_list = _build_weighted_list(CURRENCY_DISTRIBUTION)
    random.shuffle(currency_list)

    type_list = _build_weighted_list(TYPE_DISTRIBUTION)
    random.shuffle(type_list)

    method_list = _build_weighted_list(PAYMENT_DISTRIBUTION)
    random.shuffle(method_list)

    customer_ids = [f"CUST-{i:03d}" for i in range(1, 31)]
    transactions: list[dict] = []

    for idx in range(1, 51):
        tx_id = f"TXN-{idx:03d}"
        customer_id = random.choice(customer_ids)
        currency = currency_list[idx - 1]
        tx_type = type_list[idx - 1]
        pay_method = method_list[idx - 1]

        days_ago = random.randint(1, 90)
        tx_date = now - timedelta(days=days_ago)
        tx_date = tx_date.replace(
            hour=random.randint(8, 20),
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
            microsecond=0,
        )

        # Generate USD-equivalent amount between 20 and 5000
        usd_amount = Decimal(str(random.randint(20, 5000)))
        multiplier = USD_EQUIVALENT_MULTIPLIERS[currency]
        amount = (usd_amount * multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Pick supplier currency
        possible_suppliers = SUPPLIER_CURRENCIES[currency]
        supplier_currency = random.choice(possible_suppliers)

        # Compute exchange rate and supplier amount
        if currency == supplier_currency:
            exchange_rate_used = Decimal("1.000000")
            supplier_amount = amount
        else:
            exchange_rate_used = _get_rate(
                rate_lookup, currency, supplier_currency, tx_date
            )
            supplier_amount = (amount * exchange_rate_used).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        transactions.append(
            {
                "id": tx_id,
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency.value,
                "supplier_currency": supplier_currency.value,
                "supplier_amount": supplier_amount,
                "exchange_rate_used": exchange_rate_used,
                "transaction_type": tx_type.value,
                "payment_method": pay_method.value,
                "timestamp": tx_date.isoformat(),
                "status": TransactionStatus.SUCCESS.value,
                "total_refunded": Decimal("0"),
            }
        )

    return transactions


# ---------------------------------------------------------------------------
# Refund request generation
# ---------------------------------------------------------------------------


def _find_tx_by_currency(
    transactions: list[dict], currency_value: str
) -> dict | None:
    """Find a transaction with a given customer currency."""
    for tx in transactions:
        if tx["currency"] == currency_value:
            return tx
    return None


def _find_cross_currency_tx(
    transactions: list[dict], customer_currency: str | None = None
) -> dict | None:
    """Find a transaction where customer currency != supplier currency."""
    for tx in transactions:
        if tx["currency"] != tx["supplier_currency"]:
            if customer_currency is None or tx["currency"] == customer_currency:
                return tx
    return None


def _find_large_tx(transactions: list[dict], min_usd: int = 3000) -> dict | None:
    """Find a transaction with amount >= min_usd equivalent."""
    for tx in transactions:
        multiplier = USD_EQUIVALENT_MULTIPLIERS[Currency(tx["currency"])]
        usd_equiv = Decimal(str(tx["amount"])) / multiplier
        if usd_equiv >= min_usd:
            return tx
    return None


def _find_old_tx(
    transactions: list[dict], now: datetime, min_days: int = 60
) -> dict | None:
    """Find a transaction that is at least min_days old."""
    for tx in transactions:
        tx_date = datetime.fromisoformat(tx["timestamp"])
        if (now - tx_date).days >= min_days:
            return tx
    return None


def _make_refund(
    ref_id: str,
    tx: dict,
    policy: RefundPolicy,
    requested_amount: Decimal | None = None,
    fees: list[dict] | None = None,
    destination_currency: str | None = None,
    timestamp: datetime | None = None,
) -> dict:
    """Build a refund request dict."""
    result: dict = {
        "id": ref_id,
        "transaction_id": tx["id"],
        "requested_amount": requested_amount,
        "destination_currency": destination_currency or tx["currency"],
        "policy": policy.value,
        "fees": fees or [],
    }
    if timestamp:
        result["timestamp"] = timestamp.isoformat()
    else:
        result["timestamp"] = datetime.utcnow().isoformat()
    return result


def generate_refund_requests(
    transactions: list[dict],
    rate_lookup: dict[tuple[str, str, str], Decimal],
    now: datetime,
) -> list[dict]:
    """Generate 20 refund requests covering specified scenarios."""
    refunds: list[dict] = []

    # Helper to get transaction by ID
    tx_by_id = {tx["id"]: tx for tx in transactions}

    # Collect transactions by currency for easy lookup
    usd_txs = [t for t in transactions if t["currency"] == "USD"]
    eur_txs = [t for t in transactions if t["currency"] == "EUR"]
    brl_txs = [t for t in transactions if t["currency"] == "BRL"]
    mxn_txs = [t for t in transactions if t["currency"] == "MXN"]
    cop_txs = [t for t in transactions if t["currency"] == "COP"]
    thb_txs = [t for t in transactions if t["currency"] == "THB"]

    cross_currency_txs = [
        t for t in transactions if t["currency"] != t["supplier_currency"]
    ]

    # ---- REF-001: Full refund, same currency (USD->USD), ORIGINAL_RATE ----
    tx1 = usd_txs[0]
    refunds.append(
        _make_refund("REF-001", tx1, RefundPolicy.ORIGINAL_RATE)
    )

    # ---- REF-002: Full refund, cross-currency (BRL customer, USD supplier), CUSTOMER_FAVORABLE ----
    tx2 = _find_cross_currency_tx(transactions, "BRL")
    if tx2 is None:
        # Fallback to first BRL if no cross-currency BRL exists
        tx2 = brl_txs[0]
    refunds.append(
        _make_refund("REF-002", tx2, RefundPolicy.CUSTOMER_FAVORABLE)
    )

    # ---- REF-003: Partial refund with 15% cancellation fee, EUR, ORIGINAL_RATE ----
    tx3 = eur_txs[0]
    partial_amount_3 = (Decimal(str(tx3["amount"])) * Decimal("0.70")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-003",
            tx3,
            RefundPolicy.ORIGINAL_RATE,
            requested_amount=partial_amount_3,
            fees=[
                {
                    "type": FeeType.PERCENTAGE.value,
                    "value": "15",
                    "currency": None,
                    "description": "Cancellation fee (15%)",
                }
            ],
        )
    )

    # ---- REF-004: Partial refund with fixed $25 USD fee, MXN transaction, CURRENT_RATE ----
    tx4 = mxn_txs[0]
    partial_amount_4 = (Decimal(str(tx4["amount"])) * Decimal("0.50")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-004",
            tx4,
            RefundPolicy.CURRENT_RATE,
            requested_amount=partial_amount_4,
            fees=[
                {
                    "type": FeeType.FIXED.value,
                    "value": "25",
                    "currency": Currency.USD.value,
                    "description": "Processing fee ($25 USD)",
                }
            ],
        )
    )

    # ---- REF-005: Partial refund with both 10% and fixed $15 fees, COP, TIME_WEIGHTED ----
    tx5 = cop_txs[0]
    partial_amount_5 = (Decimal(str(tx5["amount"])) * Decimal("0.80")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-005",
            tx5,
            RefundPolicy.TIME_WEIGHTED,
            requested_amount=partial_amount_5,
            fees=[
                {
                    "type": FeeType.PERCENTAGE.value,
                    "value": "10",
                    "currency": None,
                    "description": "Cancellation fee (10%)",
                },
                {
                    "type": FeeType.FIXED.value,
                    "value": "15",
                    "currency": Currency.USD.value,
                    "description": "Admin fee ($15 USD)",
                },
            ],
        )
    )

    # ---- REF-006: Time-weighted policy on 60+ day old transaction, THB ----
    tx6 = _find_old_tx(thb_txs, now, min_days=60) or thb_txs[0]
    refunds.append(
        _make_refund("REF-006", tx6, RefundPolicy.TIME_WEIGHTED)
    )

    # ---- REF-007: Current-rate with significant rate movement ----
    # Pick a cross-currency tx and verify rate drift > 5%
    tx7 = cross_currency_txs[0]
    refunds.append(
        _make_refund("REF-007", tx7, RefundPolicy.CURRENT_RATE)
    )

    # ---- REF-008: Full refund, CUSTOMER_FAVORABLE, large amount (>$3000 equiv) ----
    tx8 = _find_large_tx(transactions, min_usd=3000)
    if tx8 is None:
        tx8 = usd_txs[-1]
    refunds.append(
        _make_refund("REF-008", tx8, RefundPolicy.CUSTOMER_FAVORABLE)
    )

    # ---- REF-009: Full refund after partial (tx has some total_refunded) ----
    tx9 = usd_txs[2]
    partial_already = (Decimal(str(tx9["amount"])) * Decimal("0.30")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    tx9["total_refunded"] = partial_already
    tx9["status"] = TransactionStatus.PARTIALLY_REFUNDED.value
    remaining_9 = Decimal(str(tx9["amount"])) - partial_already
    refunds.append(
        _make_refund(
            "REF-009",
            tx9,
            RefundPolicy.ORIGINAL_RATE,
            requested_amount=remaining_9,
        )
    )

    # ---- REF-010: Small refund ($50 equiv), various currencies ----
    tx10 = eur_txs[1]
    small_amount = (Decimal("50") * USD_EQUIVALENT_MULTIPLIERS[Currency.EUR]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-010",
            tx10,
            RefundPolicy.ORIGINAL_RATE,
            requested_amount=small_amount,
        )
    )

    # ---- REF-011: Full refund, BRL, CURRENT_RATE ----
    tx11 = brl_txs[1] if len(brl_txs) > 1 else brl_txs[0]
    refunds.append(
        _make_refund("REF-011", tx11, RefundPolicy.CURRENT_RATE)
    )

    # ---- REF-012: Partial refund with 20% fee, MXN, CUSTOMER_FAVORABLE ----
    tx12 = mxn_txs[1] if len(mxn_txs) > 1 else mxn_txs[0]
    partial_amount_12 = (Decimal(str(tx12["amount"])) * Decimal("0.60")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-012",
            tx12,
            RefundPolicy.CUSTOMER_FAVORABLE,
            requested_amount=partial_amount_12,
            fees=[
                {
                    "type": FeeType.PERCENTAGE.value,
                    "value": "20",
                    "currency": None,
                    "description": "Late cancellation fee (20%)",
                }
            ],
        )
    )

    # ---- REF-013: Cross-currency EUR->USD, TIME_WEIGHTED, with fixed fee ----
    tx13 = _find_cross_currency_tx(transactions, "EUR")
    if tx13 is None:
        tx13 = eur_txs[2] if len(eur_txs) > 2 else eur_txs[0]
    refunds.append(
        _make_refund(
            "REF-013",
            tx13,
            RefundPolicy.TIME_WEIGHTED,
            fees=[
                {
                    "type": FeeType.FIXED.value,
                    "value": "10",
                    "currency": Currency.EUR.value,
                    "description": "Service fee (10 EUR)",
                }
            ],
        )
    )

    # ---- REF-014: Full refund, COP, ORIGINAL_RATE ----
    tx14 = cop_txs[1] if len(cop_txs) > 1 else cop_txs[0]
    refunds.append(
        _make_refund("REF-014", tx14, RefundPolicy.ORIGINAL_RATE)
    )

    # ---- REF-015: Partial THB refund, CUSTOMER_FAVORABLE, with percentage fee ----
    tx15 = thb_txs[1] if len(thb_txs) > 1 else thb_txs[0]
    partial_amount_15 = (Decimal(str(tx15["amount"])) * Decimal("0.40")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-015",
            tx15,
            RefundPolicy.CUSTOMER_FAVORABLE,
            requested_amount=partial_amount_15,
            fees=[
                {
                    "type": FeeType.PERCENTAGE.value,
                    "value": "5",
                    "currency": None,
                    "description": "Processing fee (5%)",
                }
            ],
        )
    )

    # ---- REF-016: Duplicate refund attempt (same tx and amount as REF-001) ----
    refunds.append(
        _make_refund("REF-016", tx1, RefundPolicy.ORIGINAL_RATE)
    )

    # ---- REF-017: Excessive refund (amount > transaction remaining) ----
    tx17 = usd_txs[3]
    excessive_amount = (Decimal(str(tx17["amount"])) * Decimal("1.50")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-017",
            tx17,
            RefundPolicy.ORIGINAL_RATE,
            requested_amount=excessive_amount,
        )
    )

    # ---- REF-018: Refund for non-existent transaction ----
    refunds.append(
        {
            "id": "REF-018",
            "transaction_id": "TXN-NONEXISTENT",
            "requested_amount": None,
            "destination_currency": Currency.USD.value,
            "policy": RefundPolicy.ORIGINAL_RATE.value,
            "fees": [],
            "timestamp": now.isoformat(),
        }
    )

    # ---- REF-019: Refund on already-fully-refunded transaction ----
    tx19 = usd_txs[4]
    tx19["total_refunded"] = tx19["amount"]
    tx19["status"] = TransactionStatus.REFUNDED.value
    refunds.append(
        _make_refund("REF-019", tx19, RefundPolicy.ORIGINAL_RATE)
    )

    # ---- REF-020: Cross-currency refund, large amount + high rate drift ----
    # Pick a cross-currency tx with a large amount
    tx20 = None
    for t in cross_currency_txs:
        multiplier = USD_EQUIVALENT_MULTIPLIERS[Currency(t["currency"])]
        usd_equiv = Decimal(str(t["amount"])) / multiplier
        if usd_equiv >= 1000:
            tx20 = t
            break
    if tx20 is None:
        tx20 = cross_currency_txs[-1]

    large_amount_20 = (Decimal(str(tx20["amount"])) * Decimal("0.95")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    refunds.append(
        _make_refund(
            "REF-020",
            tx20,
            RefundPolicy.CUSTOMER_FAVORABLE,
            requested_amount=large_amount_20,
            fees=[
                {
                    "type": FeeType.PERCENTAGE.value,
                    "value": "5",
                    "currency": None,
                    "description": "Processing fee (5%)",
                },
                {
                    "type": FeeType.FIXED.value,
                    "value": "50",
                    "currency": Currency.USD.value,
                    "description": "Cross-border fee ($50 USD)",
                },
            ],
        )
    )

    return refunds


# ---------------------------------------------------------------------------
# Convenience loaders
# ---------------------------------------------------------------------------


def load_exchange_rates() -> list[dict]:
    """Load exchange rates from the JSON file."""
    with open(EXCHANGE_RATES_PATH) as f:
        return json.load(f)


def load_transactions() -> list[dict]:
    """Load transactions from the JSON file."""
    with open(TRANSACTIONS_PATH) as f:
        return json.load(f)


def load_refund_requests() -> list[dict]:
    """Load refund requests from the JSON file."""
    with open(REFUND_REQUESTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    now = datetime.utcnow()

    print("Generating exchange rates (90 days)...")
    generator = RateGenerator()
    rates = generator.generate_rates(days=90)
    generator.save_rates(rates, str(EXCHANGE_RATES_PATH))
    print(f"  Saved {len(rates)} rates to {EXCHANGE_RATES_PATH}")

    # Build rate lookup for transaction generation
    rate_lookup = _build_rate_lookup(rates)

    print("Generating transactions...")
    transactions = generate_transactions(rate_lookup, now)
    with open(TRANSACTIONS_PATH, "w") as f:
        json.dump(transactions, f, indent=2, cls=DecimalEncoder)
    print(f"  Saved {len(transactions)} transactions to {TRANSACTIONS_PATH}")

    print("Generating refund requests...")
    refund_requests = generate_refund_requests(transactions, rate_lookup, now)
    with open(REFUND_REQUESTS_PATH, "w") as f:
        json.dump(refund_requests, f, indent=2, cls=DecimalEncoder)
    print(f"  Saved {len(refund_requests)} refund requests to {REFUND_REQUESTS_PATH}")

    # Re-save transactions (some were mutated for REF-009 and REF-019)
    with open(TRANSACTIONS_PATH, "w") as f:
        json.dump(transactions, f, indent=2, cls=DecimalEncoder)
    print("  Re-saved transactions with updated total_refunded fields.")

    # Summary
    print("\n--- Summary ---")
    currency_counts: dict[str, int] = {}
    for tx in transactions:
        c = tx["currency"]
        currency_counts[c] = currency_counts.get(c, 0) + 1
    print(f"  Transactions by currency: {currency_counts}")

    type_counts: dict[str, int] = {}
    for tx in transactions:
        t = tx["transaction_type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  Transactions by type: {type_counts}")

    method_counts: dict[str, int] = {}
    for tx in transactions:
        m = tx["payment_method"]
        method_counts[m] = method_counts.get(m, 0) + 1
    print(f"  Transactions by payment method: {method_counts}")

    policy_counts: dict[str, int] = {}
    for ref in refund_requests:
        p = ref["policy"]
        policy_counts[p] = policy_counts.get(p, 0) + 1
    print(f"  Refund requests by policy: {policy_counts}")

    print("\nDone!")


if __name__ == "__main__":
    main()
