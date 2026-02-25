"""
Multi-Currency Refund Engine -- Comprehensive Demo Script
=========================================================

Demonstrates all major capabilities of the refund engine:
  - Exchange rate generation and loading
  - Full and partial refunds across currencies
  - All four refund policies (ORIGINAL_RATE, CUSTOMER_FAVORABLE, CURRENT_RATE, TIME_WEIGHTED)
  - Fee application (percentage, fixed, and mixed)
  - Risk detection and flagging
  - Validation (duplicate detection, excessive amounts)
  - Batch processing with summary report
  - Audit trail output

Run:  python3 demo.py
"""

from __future__ import annotations

import io
import random
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from decimal import Decimal

from src.batch.batch_processor import BatchReportGenerator
from src.enums import (
    Currency,
    FeeType,
    PaymentMethod,
    RefundPolicy,
    RefundStatus,
    TransactionType,
)
from src.exchange.rate_generator import RateGenerator
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import (
    Fee,
    RefundRequest,
    RiskConfig,
    Transaction,
)
from src.notifications.notifier import RefundNotifier
from src.refund.processor import RefundProcessor
from src.storage.repository import RefundRepository, TransactionRepository

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BOX_WIDTH = 64
NOW = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)

CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "\u20ac",
    "BRL": "R$",
    "MXN": "MX$",
    "COP": "COL$",
    "THB": "\u0e3f",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_money(amount: Decimal, currency: str) -> str:
    """Format an amount with its currency symbol."""
    sym = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{sym}{amount:,.2f} {currency}"


def box_top() -> str:
    return "\u2554" + "\u2550" * BOX_WIDTH + "\u2557"


def box_mid() -> str:
    return "\u2560" + "\u2550" * BOX_WIDTH + "\u2563"


def box_bot() -> str:
    return "\u255a" + "\u2550" * BOX_WIDTH + "\u255d"


def box_line(text: str) -> str:
    padding = BOX_WIDTH - len(text)
    if padding < 0:
        text = text[: BOX_WIDTH]
        padding = 0
    return "\u2551" + " " + text + " " * (padding - 1) + "\u2551"


def print_scenario_header(num: int, title: str) -> None:
    print()
    print(box_top())
    print(box_line(f"Scenario {num}: {title}"))
    print(box_mid())


def print_scenario_footer() -> None:
    print(box_bot())


def print_section(label: str) -> None:
    print(box_line(f"{label}"))


def print_field(label: str, value: str) -> None:
    print(box_line(f"  {label}: {value}"))


def print_empty() -> None:
    print(box_line(""))


def print_audit_entries(entries: list, max_entries: int = 3) -> None:
    """Print a few key audit entries."""
    print_empty()
    print_section("Audit Trail (selected entries):")
    shown = 0
    # Pick interesting actions to show
    priority_actions = [
        "determine_refund_amount",
        "policy_applied",
        "fee_application",
        "conversion",
        "final_calculation",
        "risk_assessment",
        "status_determination",
        "rejected",
        "validation",
    ]
    for action in priority_actions:
        if shown >= max_entries:
            break
        for entry in entries:
            if entry.action == action:
                ts = entry.timestamp.strftime("%H:%M:%S")
                detail = entry.details
                if len(detail) > BOX_WIDTH - 14:
                    detail = detail[: BOX_WIDTH - 17] + "..."
                print_field(f"[{ts}]", f"{entry.action}: {detail}")
                shown += 1
                break
    if shown == 0:
        for entry in entries[:max_entries]:
            ts = entry.timestamp.strftime("%H:%M:%S")
            detail = entry.details
            if len(detail) > BOX_WIDTH - 14:
                detail = detail[: BOX_WIDTH - 17] + "..."
            print_field(f"[{ts}]", f"{entry.action}: {detail}")


# ---------------------------------------------------------------------------
# Scenario output
# ---------------------------------------------------------------------------

def print_scenario_result(
    num: int,
    title: str,
    tx: Transaction,
    request: RefundRequest,
    result,
    fees_desc: str = "None",
) -> None:
    """Print a single scenario with the box format."""
    print_scenario_header(num, title)

    # Original Transaction
    print_section("Original Transaction:")
    print_field("Amount", f"{fmt_money(tx.amount, tx.currency.value)} | Type: {tx.transaction_type.value} | Date: {tx.timestamp.strftime('%Y-%m-%d')}")
    print_field("Supplier", f"{fmt_money(tx.supplier_amount, tx.supplier_currency.value)} | Rate: {tx.exchange_rate_used}")
    print_empty()

    # Refund Request
    print_section("Refund Request:")
    print_field("Policy", f"{request.policy.value} | Fees: {fees_desc}")
    if request.requested_amount is not None:
        print_field("Requested Amount", fmt_money(request.requested_amount, tx.currency.value))
    else:
        print_field("Requested Amount", "Full refund")
    print_empty()

    # Result
    print_section("Result:")
    print_field("Status", result.status.value)
    if result.status == RefundStatus.REJECTED:
        print_field("Rejection Reason", result.rejection_reason or "N/A")
    else:
        print_field("Refund Before Fees", fmt_money(result.refund_amount_before_fees, result.original_currency.value))
        print_field("Fees Deducted", fmt_money(result.total_fees, result.original_currency.value))
        print_field("Refund After Fees", fmt_money(result.refund_amount_after_fees, result.original_currency.value))
        print_field("Destination Amount", fmt_money(result.destination_amount, result.destination_currency.value))
        print_field("Original Rate", f"{result.original_rate} | Current Rate: {result.current_rate}")
        print_field("Rate Used", f"{result.rate_used} | Policy: {result.policy_applied.value}")

    # Risk flags
    if result.risk_flags:
        flags_str = "; ".join(f"{f.reason} [{f.level.value}]" for f in result.risk_flags)
        if len(flags_str) > BOX_WIDTH - 18:
            for f in result.risk_flags:
                flag_line = f"{f.reason} [{f.level.value}]"
                print_field("Risk Flag", flag_line)
        else:
            print_field("Risk Flags", flags_str)
    else:
        print_field("Risk Flags", "None")

    # Audit
    print_audit_entries(result.audit_entries, max_entries=3)
    print_scenario_footer()


# ---------------------------------------------------------------------------
# Helper: suppress notifier stdout during processing
# ---------------------------------------------------------------------------

def process_quiet(processor: RefundProcessor, request: RefundRequest):
    """Process a refund while suppressing notifier print output."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = processor.process_refund(request)
    return result


def process_batch_quiet(processor: RefundProcessor, requests: list[RefundRequest]):
    """Process a batch while suppressing notifier print output."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        batch_result = processor.process_batch(requests)
    return batch_result


# ===================================================================
# MAIN
# ===================================================================

def main() -> None:
    random.seed(42)

    print("=" * 68)
    print("   MULTI-CURRENCY REFUND ENGINE -- COMPREHENSIVE DEMO")
    print("=" * 68)

    # ------------------------------------------------------------------
    # 1. Generate and load exchange rates
    # ------------------------------------------------------------------
    print("\n[Setup] Generating exchange rates (90 days)...")
    generator = RateGenerator()
    rates = generator.generate_rates(days=90)
    print(f"  Generated {len(rates)} exchange rate entries.")

    rate_provider = InMemoryRateProvider()
    rate_provider.load_rates(rates)
    print("  Loaded rates into InMemoryRateProvider.")

    # ------------------------------------------------------------------
    # 2. Repositories and processor
    # ------------------------------------------------------------------
    tx_repo = TransactionRepository()
    refund_repo = RefundRepository()
    notifier = RefundNotifier()
    risk_config = RiskConfig(
        large_refund_threshold_usd=Decimal("2000"),
        exchange_rate_drift_threshold=Decimal("0.05"),
    )

    processor = RefundProcessor(
        rate_provider=rate_provider,
        transaction_repo=tx_repo,
        refund_repo=refund_repo,
        risk_config=risk_config,
        notifier=notifier,
    )

    # ------------------------------------------------------------------
    # 3. Create 12 demo transactions
    # ------------------------------------------------------------------
    print("[Setup] Creating demo transactions...\n")

    # Compute some reference dates
    days_ago = lambda d: NOW - timedelta(days=d)

    # Get some actual rates from the provider for realistic supplier amounts
    def get_rate_safe(src: Currency, tgt: Currency, date: datetime) -> Decimal:
        try:
            return rate_provider.get_rate(src, tgt, date)
        except ValueError:
            return Decimal("1")

    # TX-1: USD -> USD (same currency flight)
    tx1 = Transaction(
        id="TX-001",
        customer_id="CUST-001",
        amount=Decimal("500.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("500.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(10),
    )

    # TX-2: BRL -> USD cross-currency
    brl_usd_rate_tx2 = get_rate_safe(Currency.BRL, Currency.USD, days_ago(15))
    tx2 = Transaction(
        id="TX-002",
        customer_id="CUST-002",
        amount=Decimal("2600.00"),
        currency=Currency.BRL,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("2600.00") * brl_usd_rate_tx2).quantize(Decimal("0.01")),
        exchange_rate_used=brl_usd_rate_tx2,
        transaction_type=TransactionType.HOTEL,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(15),
    )

    # TX-3: EUR hotel with cancellation fee (refund back to EUR, same currency)
    eur_usd_rate_tx3 = get_rate_safe(Currency.EUR, Currency.USD, days_ago(20))
    tx3 = Transaction(
        id="TX-003",
        customer_id="CUST-003",
        amount=Decimal("1200.00"),
        currency=Currency.EUR,
        supplier_currency=Currency.EUR,
        supplier_amount=Decimal("1200.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.HOTEL,
        payment_method=PaymentMethod.BANK_TRANSFER,
        timestamp=days_ago(20),
    )

    # TX-4: MXN tour with fixed USD fee (refund to USD cross-currency)
    mxn_usd_rate_tx4 = get_rate_safe(Currency.MXN, Currency.USD, days_ago(12))
    tx4 = Transaction(
        id="TX-004",
        customer_id="CUST-004",
        amount=Decimal("8500.00"),
        currency=Currency.MXN,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("8500.00") * mxn_usd_rate_tx4).quantize(Decimal("0.01")),
        exchange_rate_used=mxn_usd_rate_tx4,
        transaction_type=TransactionType.TOUR_PACKAGE,
        payment_method=PaymentMethod.DIGITAL_WALLET,
        timestamp=days_ago(12),
    )
    # Destination will be USD to show cross-currency with fee

    # TX-5: COP flight with mixed fees
    cop_usd_rate_tx5 = get_rate_safe(Currency.COP, Currency.USD, days_ago(25))
    tx5 = Transaction(
        id="TX-005",
        customer_id="CUST-005",
        amount=Decimal("1500000.00"),
        currency=Currency.COP,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("1500000.00") * cop_usd_rate_tx5).quantize(Decimal("0.01")),
        exchange_rate_used=cop_usd_rate_tx5,
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(25),
    )

    # TX-6: THB old transaction (75 days old)
    thb_usd_rate_tx6 = get_rate_safe(Currency.THB, Currency.USD, days_ago(75))
    tx6 = Transaction(
        id="TX-006",
        customer_id="CUST-006",
        amount=Decimal("45000.00"),
        currency=Currency.THB,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("45000.00") * thb_usd_rate_tx6).quantize(Decimal("0.01")),
        exchange_rate_used=thb_usd_rate_tx6,
        transaction_type=TransactionType.HOTEL,
        payment_method=PaymentMethod.BANK_TRANSFER,
        timestamp=days_ago(75),
    )

    # TX-7: BRL -> USD with significant rate drift (~8% manipulated)
    brl_usd_rate_tx7_orig = get_rate_safe(Currency.BRL, Currency.USD, days_ago(60))
    # We'll use a rate that's ~8% different from current to trigger drift
    manipulated_rate = (brl_usd_rate_tx7_orig * Decimal("0.92")).quantize(Decimal("0.000001"))
    tx7 = Transaction(
        id="TX-007",
        customer_id="CUST-007",
        amount=Decimal("3500.00"),
        currency=Currency.BRL,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("3500.00") * manipulated_rate).quantize(Decimal("0.01")),
        exchange_rate_used=manipulated_rate,
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(60),
    )

    # TX-8: Large USD refund (>$4500 to trigger large amount flag)
    tx8 = Transaction(
        id="TX-008",
        customer_id="CUST-008",
        amount=Decimal("4500.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("4500.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.TOUR_PACKAGE,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(5),
    )

    # TX-9: Transaction for double partial refund
    tx9 = Transaction(
        id="TX-009",
        customer_id="CUST-009",
        amount=Decimal("1000.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("1000.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(8),
    )

    # TX-10: Transaction for duplicate refund attempt
    tx10 = Transaction(
        id="TX-010",
        customer_id="CUST-010",
        amount=Decimal("750.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("750.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.HOTEL,
        payment_method=PaymentMethod.DIGITAL_WALLET,
        timestamp=days_ago(7),
    )

    # TX-11: Transaction for excessive amount rejection
    tx11 = Transaction(
        id="TX-011",
        customer_id="CUST-011",
        amount=Decimal("600.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("600.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.BANK_TRANSFER,
        timestamp=days_ago(6),
    )

    # TX-12a through TX-12e: Batch transactions (various currencies)
    tx12a = Transaction(
        id="TX-012A",
        customer_id="CUST-012",
        amount=Decimal("300.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("300.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(3),
    )
    tx12b = Transaction(
        id="TX-012B",
        customer_id="CUST-013",
        amount=Decimal("1500.00"),
        currency=Currency.BRL,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("1500.00") * get_rate_safe(Currency.BRL, Currency.USD, days_ago(4))).quantize(Decimal("0.01")),
        exchange_rate_used=get_rate_safe(Currency.BRL, Currency.USD, days_ago(4)),
        transaction_type=TransactionType.HOTEL,
        payment_method=PaymentMethod.BANK_TRANSFER,
        timestamp=days_ago(4),
    )
    tx12c = Transaction(
        id="TX-012C",
        customer_id="CUST-014",
        amount=Decimal("850.00"),
        currency=Currency.EUR,
        supplier_currency=Currency.EUR,
        supplier_amount=Decimal("850.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.TOUR_PACKAGE,
        payment_method=PaymentMethod.DIGITAL_WALLET,
        timestamp=days_ago(6),
    )
    mxn_usd_rate_tx12d = get_rate_safe(Currency.MXN, Currency.USD, days_ago(2))
    tx12d = Transaction(
        id="TX-012D",
        customer_id="CUST-015",
        amount=Decimal("5000.00"),
        currency=Currency.MXN,
        supplier_currency=Currency.USD,
        supplier_amount=(Decimal("5000.00") * mxn_usd_rate_tx12d).quantize(Decimal("0.01")),
        exchange_rate_used=mxn_usd_rate_tx12d,
        transaction_type=TransactionType.FLIGHT,
        payment_method=PaymentMethod.CREDIT_CARD,
        timestamp=days_ago(2),
    )
    tx12e = Transaction(
        id="TX-012E",
        customer_id="CUST-016",
        amount=Decimal("200.00"),
        currency=Currency.USD,
        supplier_currency=Currency.USD,
        supplier_amount=Decimal("200.00"),
        exchange_rate_used=Decimal("1.000000"),
        transaction_type=TransactionType.HOTEL,
        payment_method=PaymentMethod.BANK_TRANSFER,
        timestamp=days_ago(1),
    )

    # Save all transactions to the repository
    all_transactions = [
        tx1, tx2, tx3, tx4, tx5, tx6, tx7, tx8, tx9, tx10, tx11,
        tx12a, tx12b, tx12c, tx12d, tx12e,
    ]
    for tx in all_transactions:
        tx_repo.save(tx)

    print(f"  Created and saved {len(all_transactions)} transactions.\n")

    # ------------------------------------------------------------------
    # Summary collector
    # ------------------------------------------------------------------
    summary_rows: list[dict] = []

    def record_summary(
        scenario: int,
        status: str,
        original: str,
        final_refund: str,
        policy: str,
    ) -> None:
        summary_rows.append({
            "scenario": scenario,
            "status": status,
            "original": original,
            "final_refund": final_refund,
            "policy": policy,
        })

    # ==================================================================
    # SCENARIO 1: Full Refund - Same Currency (USD -> USD)
    # ==================================================================
    req1 = RefundRequest(
        id="REQ-001",
        transaction_id="TX-001",
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result1 = process_quiet(processor, req1)
    print_scenario_result(1, "Full Refund - Same Currency (USD->USD)", tx1, req1, result1)
    record_summary(1, result1.status.value, fmt_money(tx1.amount, tx1.currency.value),
                   fmt_money(result1.destination_amount, result1.destination_currency.value),
                   result1.policy_applied.value)

    # ==================================================================
    # SCENARIO 2: Full Refund - Cross Currency (BRL -> USD)
    # ==================================================================
    req2 = RefundRequest(
        id="REQ-002",
        transaction_id="TX-002",
        destination_currency=Currency.USD,
        policy=RefundPolicy.CUSTOMER_FAVORABLE,
    )
    result2 = process_quiet(processor, req2)
    print_scenario_result(2, "Full Refund - Cross Currency (BRL->USD)", tx2, req2, result2)
    record_summary(2, result2.status.value, fmt_money(tx2.amount, tx2.currency.value),
                   fmt_money(result2.destination_amount, result2.destination_currency.value),
                   result2.policy_applied.value)

    # ==================================================================
    # SCENARIO 3: Partial Refund - 15% Cancellation Fee (EUR hotel)
    # ==================================================================
    req3 = RefundRequest(
        id="REQ-003",
        transaction_id="TX-003",
        fees=[
            Fee(type=FeeType.PERCENTAGE, value=Decimal("15"), description="Cancellation fee (15%)"),
        ],
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result3 = process_quiet(processor, req3)
    print_scenario_result(3, "Partial Refund - 15% Cancellation Fee", tx3, req3, result3,
                          fees_desc="15% cancellation")
    record_summary(3, result3.status.value, fmt_money(tx3.amount, tx3.currency.value),
                   fmt_money(result3.destination_amount, result3.destination_currency.value),
                   result3.policy_applied.value)

    # ==================================================================
    # SCENARIO 4: Partial Refund - Fixed $25 USD Fee (MXN tour)
    # ==================================================================
    req4 = RefundRequest(
        id="REQ-004",
        transaction_id="TX-004",
        destination_currency=Currency.USD,
        fees=[
            Fee(type=FeeType.FIXED, value=Decimal("25.00"), currency=Currency.USD,
                description="Processing fee ($25 USD)"),
        ],
        policy=RefundPolicy.CURRENT_RATE,
    )
    result4 = process_quiet(processor, req4)
    print_scenario_result(4, "Partial Refund - Fixed $25 USD Fee", tx4, req4, result4,
                          fees_desc="$25 USD fixed")
    record_summary(4, result4.status.value, fmt_money(tx4.amount, tx4.currency.value),
                   fmt_money(result4.destination_amount, result4.destination_currency.value),
                   result4.policy_applied.value)

    # ==================================================================
    # SCENARIO 5: Partial Refund - Mixed Fees (10% + $15 fixed) COP flight
    # ==================================================================
    req5 = RefundRequest(
        id="REQ-005",
        transaction_id="TX-005",
        destination_currency=Currency.USD,
        fees=[
            Fee(type=FeeType.PERCENTAGE, value=Decimal("10"), description="Airline penalty (10%)"),
            Fee(type=FeeType.FIXED, value=Decimal("15.00"), currency=Currency.USD,
                description="Admin fee ($15 USD)"),
        ],
        policy=RefundPolicy.TIME_WEIGHTED,
    )
    result5 = process_quiet(processor, req5)
    print_scenario_result(5, "Partial Refund - Mixed Fees (10% + $15)", tx5, req5, result5,
                          fees_desc="10% + $15 USD fixed")
    record_summary(5, result5.status.value, fmt_money(tx5.amount, tx5.currency.value),
                   fmt_money(result5.destination_amount, result5.destination_currency.value),
                   result5.policy_applied.value)

    # ==================================================================
    # SCENARIO 6: Time-Weighted Policy - Old Transaction (75 days)
    # ==================================================================
    req6 = RefundRequest(
        id="REQ-006",
        transaction_id="TX-006",
        destination_currency=Currency.USD,
        policy=RefundPolicy.TIME_WEIGHTED,
    )
    result6 = process_quiet(processor, req6)
    print_scenario_result(6, "Time-Weighted Policy - Old Transaction (75d)", tx6, req6, result6)
    record_summary(6, result6.status.value, fmt_money(tx6.amount, tx6.currency.value),
                   fmt_money(result6.destination_amount, result6.destination_currency.value),
                   result6.policy_applied.value)

    # ==================================================================
    # SCENARIO 7: Current Rate - Rate Drifted Significantly (~8%)
    # ==================================================================
    req7 = RefundRequest(
        id="REQ-007",
        transaction_id="TX-007",
        destination_currency=Currency.USD,
        policy=RefundPolicy.CURRENT_RATE,
    )
    result7 = process_quiet(processor, req7)
    print_scenario_result(7, "Current Rate - Rate Drifted ~8%", tx7, req7, result7)
    record_summary(7, result7.status.value, fmt_money(tx7.amount, tx7.currency.value),
                   fmt_money(result7.destination_amount, result7.destination_currency.value),
                   result7.policy_applied.value)

    # ==================================================================
    # SCENARIO 8: Large Refund - Customer Favorable ($4,500)
    # ==================================================================
    req8 = RefundRequest(
        id="REQ-008",
        transaction_id="TX-008",
        policy=RefundPolicy.CUSTOMER_FAVORABLE,
    )
    result8 = process_quiet(processor, req8)
    print_scenario_result(8, "Large Refund - Customer Favorable ($4,500)", tx8, req8, result8)
    record_summary(8, result8.status.value, fmt_money(tx8.amount, tx8.currency.value),
                   fmt_money(result8.destination_amount, result8.destination_currency.value),
                   result8.policy_applied.value)

    # ==================================================================
    # SCENARIO 9: Second Partial Refund on Same Transaction
    # ==================================================================
    # First partial: $400
    req9a = RefundRequest(
        id="REQ-009A",
        transaction_id="TX-009",
        requested_amount=Decimal("400.00"),
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result9a = process_quiet(processor, req9a)

    # Second partial: $350
    req9b = RefundRequest(
        id="REQ-009B",
        transaction_id="TX-009",
        requested_amount=Decimal("350.00"),
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result9b = process_quiet(processor, req9b)

    # Show first partial briefly
    print_scenario_header(9, "Second Partial Refund on Same Transaction")
    print_section("First Partial Refund (TX-009):")
    print_field("Requested", fmt_money(Decimal("400.00"), "USD"))
    print_field("Status", result9a.status.value)
    print_field("Refunded", fmt_money(result9a.destination_amount, result9a.destination_currency.value))
    print_empty()
    print_section("Second Partial Refund (TX-009):")
    print_field("Requested", fmt_money(Decimal("350.00"), "USD"))
    print_field("Status", result9b.status.value)
    print_field("Refunded", fmt_money(result9b.destination_amount, result9b.destination_currency.value))
    # Show remaining
    updated_tx9 = tx_repo.get("TX-009")
    if updated_tx9:
        print_field("Total Refunded", fmt_money(updated_tx9.total_refunded, "USD"))
        print_field("Remaining", fmt_money(updated_tx9.refundable_amount, "USD"))
    if result9b.risk_flags:
        for f in result9b.risk_flags:
            print_field("Risk Flag", f"{f.reason} [{f.level.value}]")
    else:
        print_field("Risk Flags", "None")
    print_audit_entries(result9b.audit_entries, max_entries=2)
    print_scenario_footer()
    record_summary(9, result9b.status.value, fmt_money(tx9.amount, tx9.currency.value),
                   fmt_money(result9b.destination_amount, result9b.destination_currency.value),
                   result9b.policy_applied.value)

    # ==================================================================
    # SCENARIO 10: REJECTED - Duplicate Refund Attempt
    # ==================================================================
    # First, process a refund on TX-010 and set its status to COMPLETED
    req10_first = RefundRequest(
        id="REQ-010-FIRST",
        transaction_id="TX-010",
        requested_amount=Decimal("300.00"),
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result10_first = process_quiet(processor, req10_first)
    # Mark the first refund as COMPLETED so duplicate detection triggers
    result10_first_completed = result10_first.model_copy(update={"status": RefundStatus.COMPLETED})
    refund_repo.update(result10_first_completed)

    # Now try the same amount again -- should be DUPLICATE
    req10 = RefundRequest(
        id="REQ-010",
        transaction_id="TX-010",
        requested_amount=Decimal("300.00"),
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result10 = process_quiet(processor, req10)
    print_scenario_result(10, "REJECTED: Duplicate Refund Attempt", tx10, req10, result10)
    record_summary(10, result10.status.value, fmt_money(tx10.amount, tx10.currency.value),
                   "$0.00 USD" if result10.status == RefundStatus.REJECTED else fmt_money(result10.destination_amount, result10.destination_currency.value),
                   result10.policy_applied.value)

    # ==================================================================
    # SCENARIO 11: REJECTED - Excessive Amount
    # ==================================================================
    req11 = RefundRequest(
        id="REQ-011",
        transaction_id="TX-011",
        requested_amount=Decimal("999.99"),
        policy=RefundPolicy.ORIGINAL_RATE,
    )
    result11 = process_quiet(processor, req11)
    print_scenario_result(11, "REJECTED: Excessive Amount", tx11, req11, result11)
    record_summary(11, result11.status.value, fmt_money(tx11.amount, tx11.currency.value),
                   "$0.00 USD" if result11.status == RefundStatus.REJECTED else fmt_money(result11.destination_amount, result11.destination_currency.value),
                   result11.policy_applied.value)

    # ==================================================================
    # SCENARIO 12: Batch Processing - 5 refunds at once
    # ==================================================================
    batch_requests = [
        RefundRequest(
            id="REQ-BATCH-1",
            transaction_id="TX-012A",
            policy=RefundPolicy.ORIGINAL_RATE,
        ),
        RefundRequest(
            id="REQ-BATCH-2",
            transaction_id="TX-012B",
            destination_currency=Currency.USD,
            policy=RefundPolicy.CUSTOMER_FAVORABLE,
        ),
        RefundRequest(
            id="REQ-BATCH-3",
            transaction_id="TX-012C",
            policy=RefundPolicy.ORIGINAL_RATE,
            fees=[
                Fee(type=FeeType.PERCENTAGE, value=Decimal("5"), description="Service fee (5%)"),
            ],
        ),
        RefundRequest(
            id="REQ-BATCH-4",
            transaction_id="TX-012D",
            destination_currency=Currency.USD,
            policy=RefundPolicy.CURRENT_RATE,
        ),
        RefundRequest(
            id="REQ-BATCH-5",
            transaction_id="TX-012E",
            policy=RefundPolicy.ORIGINAL_RATE,
        ),
    ]
    batch_result = process_batch_quiet(processor, batch_requests)

    print_scenario_header(12, "Batch Processing - 5 Refunds at Once")
    # Show brief per-refund summary
    for i, r in enumerate(batch_result.results, 1):
        tx_id = r.transaction_id
        print_field(f"  Batch #{i} ({tx_id})",
                    f"{r.status.value} | {fmt_money(r.destination_amount, r.destination_currency.value)}")
    print_empty()

    # Show the BatchReportGenerator output
    print_section("Batch Report (BatchReportGenerator):")
    report = BatchReportGenerator.generate_summary(batch_result)
    for line in report.split("\n"):
        if len(line) > BOX_WIDTH - 2:
            line = line[: BOX_WIDTH - 5] + "..."
        print(box_line(f"  {line}"))
    print_scenario_footer()

    record_summary(12, f"{batch_result.total_approved}A/{batch_result.total_flagged}F/{batch_result.total_rejected}R",
                   f"{batch_result.total_processed} txns",
                   " | ".join(f"{fmt_money(v, k)}" for k, v in sorted(batch_result.by_currency.items())),
                   "MIXED")

    # ==================================================================
    # FINAL SUMMARY TABLE
    # ==================================================================
    print("\n")
    print("=" * 90)
    print("  DEMO SUMMARY")
    print("=" * 90)
    header = f"{'Scenario':<10} {'Status':<12} {'Original':<20} {'Final Refund':<22} {'Policy'}"
    print(header)
    print("-" * 90)
    for row in summary_rows:
        line = f"{row['scenario']:<10} {row['status']:<12} {row['original']:<20} {row['final_refund']:<22} {row['policy']}"
        print(line)
    print("=" * 90)

    # Notification summary
    notifications = notifier.get_notifications()
    print(f"\nTotal notifications dispatched: {len(notifications)}")
    print("Done.\n")


if __name__ == "__main__":
    main()
