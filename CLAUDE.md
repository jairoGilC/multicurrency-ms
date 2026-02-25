# CLAUDE.md — Multi-Currency Refund Engine

## Project Overview

Falcon Travel's Multi-Currency Refund Processing Engine. Calculates, validates, and processes refunds across 6 currencies (USD, EUR, BRL, MXN, COP, THB) with configurable policies, fee handling, risk assessment, and audit trails.

## Quick Commands

```bash
python3 -m pytest tests/ -v              # Run all tests
python3 -m pytest tests/ --cov=src       # Run with coverage
python3 demo.py                          # Run 12-scenario demo
python3 data/generate_test_data.py       # Regenerate test data
```

## Tech Stack

- **Python 3.10+** — use `python3`, not `python`
- **Pydantic v2** — all domain models
- **pytest** — testing framework
- **No external APIs** — exchange rates are synthetic (RateGenerator with random walk + mean reversion)
- **No database** — in-memory repositories (dict-based)

## Architecture

```
src/
├── enums.py              # All enums: Currency, RefundPolicy, FeeType, etc.
├── models.py             # All Pydantic models: Transaction, RefundRequest, RefundResult, etc.
├── exchange/             # Exchange rate management
│   ├── rate_provider.py  # RateProvider Protocol + InMemoryRateProvider
│   ├── rate_generator.py # Synthetic 90-day rate generation (seed=42)
│   └── rate_comparator.py# Rate drift detection
├── refund/               # Core refund logic
│   ├── policies.py       # Strategy pattern: 4 policies (CustomerFavorable, OriginalRate, CurrentRate, TimeWeighted)
│   ├── fee_calculator.py # Percentage + fixed fee application
│   ├── calculator.py     # RefundCalculator — the core calculation engine
│   └── processor.py      # RefundProcessor — full pipeline orchestrator + batch
├── validation/           # Validation and risk
│   ├── validator.py      # RefundValidator — 6 validation rules
│   └── risk_detector.py  # RiskDetector — 4 risk checks
├── audit/
│   └── audit_trail.py    # AuditTrail — append-only audit log
├── batch/
│   └── batch_processor.py# BatchReportGenerator — formatted batch summaries
├── notifications/
│   └── notifier.py       # RefundNotifier — webhook simulation
└── storage/
    └── repository.py     # TransactionRepository + RefundRepository (in-memory)
```

## Key Design Patterns

- **Strategy Pattern** for refund policies — add new policy by implementing `calculate_rate()` and adding to `_POLICY_MAP` in `policies.py`
- **Protocol (duck typing)** for `RateProvider` — swap InMemoryRateProvider for a real API without changing consumers
- **Repository Pattern** for storage — swap in-memory for database by implementing same interface
- **All monetary values use `Decimal`** — never `float`. Serialize as strings in JSON.

## Processing Pipeline (RefundProcessor.process_refund)

1. Look up transaction → 2. Get previous refunds → 3. Validate (RefundValidator) → 4. Reject if invalid → 5. Calculate (RefundCalculator) → 6. Assess risk (RiskDetector) → 7. Set status (APPROVED/FLAGGED) → 8. Save to repo → 9. Update transaction → 10. Notify → 11. Return result

## Conventions

- **Imports**: Always import from `src.module.submodule`, not relative imports
- **Models**: All domain objects are Pydantic BaseModel in `src/models.py`
- **Enums**: All enums live in `src/enums.py`
- **Tests mirror source**: `src/refund/calculator.py` → `tests/test_refund/test_calculator.py`
- **Shared fixtures** in `tests/conftest.py` — use `rate_provider`, `sample_transaction`, `processor` fixtures
- **Test data**: `data/` contains JSON files; `data/generate_test_data.py` regenerates them

## Adding New Features

### New Refund Policy
1. Create class in `src/refund/policies.py` implementing `calculate_rate(original_rate, current_rate, days_elapsed) -> Decimal`
2. Add `name` property returning the policy identifier
3. Add entry to `_POLICY_MAP` dict
4. Add enum value to `RefundPolicy` in `src/enums.py`
5. Add tests in `tests/test_refund/test_policies.py`

### New Currency
1. Add to `Currency` enum in `src/enums.py`
2. Add base rate in `RateGenerator.BASE_RATES` in `src/exchange/rate_generator.py`
3. Add USD conversion factor in `RiskDetector._USD_CONVERSION` in `src/validation/risk_detector.py`
4. Add symbol in `_CURRENCY_SYMBOLS` in `src/batch/batch_processor.py`
5. Regenerate test data: `python3 data/generate_test_data.py`

### New Validation Rule
1. Add check method in `RefundValidator.validate()` in `src/validation/validator.py`
2. Use error code pattern: `UPPER_SNAKE_CASE`
3. Add tests in `tests/test_validation/test_validator.py`

### New Risk Check
1. Add check in `RiskDetector.assess()` in `src/validation/risk_detector.py`
2. Return `RiskFlag` with appropriate `RiskLevel` (LOW/MEDIUM/HIGH)
3. Add configurable threshold to `RiskConfig` in `src/models.py` if needed
4. Add tests in `tests/test_validation/test_risk_detector.py`

### Real Exchange Rate Provider
1. Create new class implementing `RateProvider` protocol (see `src/exchange/rate_provider.py`)
2. Must implement: `get_rate(source, target, date)`, `get_current_rate(source, target)`, `get_rate_at_date(source, target, date)`
3. Inject into `RefundProcessor` and `RefundCalculator` — no other changes needed

## Testing Rules

- **TDD**: Write failing test first, then implement
- **Every public method** must have tests
- **Use fixtures** from `conftest.py` — don't duplicate setup
- **Use `Decimal`** for all monetary assertions
- **Parametrize** when testing multiple inputs for the same logic
- Run full suite before committing: `python3 -m pytest tests/ -v`

## Files NOT to Edit Carelessly

- `src/models.py` — changing model fields can break serialization and many tests
- `src/enums.py` — removing enum values breaks data files and tests
- `tests/conftest.py` — shared fixtures used across all test modules
- `data/exchange_rates.json` — 2,700 entries, regenerate with script instead of editing manually
