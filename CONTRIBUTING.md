# Contributing to Multi-Currency Refund Engine

## Getting Started

### Prerequisites
- Python 3.10+
- pip or pip3

### Setup
```bash
# Clone the repository
git clone <repository-url>
cd multicurrency-ms

# Install dependencies
pip3 install -r requirements.txt

# Verify everything works
python3 -m pytest tests/ -v
python3 demo.py
```

## Development Workflow

### Running Tests
```bash
python3 -m pytest tests/ -v              # Run all tests
python3 -m pytest tests/ --cov=src       # Run with coverage
python3 -m pytest tests/test_refund/ -v  # Run specific module
```

### Linting and Formatting
```bash
ruff check src/ tests/                   # Check for lint issues
ruff check src/ tests/ --fix             # Auto-fix lint issues
ruff format src/ tests/                  # Format code
mypy src/                                # Type checking
```

### Running the API
```bash
uvicorn src.api.app:app --reload         # Start dev server on :8000
```

## Architecture

See [README.md](README.md) for full architecture overview and Mermaid diagrams.

### Key Conventions
- **Imports**: Always import from `src.module.submodule`, not relative imports
- **Models**: All domain objects are Pydantic BaseModel in `src/models.py`
- **Enums**: All enums live in `src/enums.py`
- **Exceptions**: Domain exceptions in `src/exceptions.py`
- **Tests mirror source**: `src/refund/calculator.py` → `tests/test_refund/test_calculator.py`
- **Shared fixtures** in `tests/conftest.py`
- **All monetary values use `Decimal`** — never `float`

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

## Commit Message Format

```
<type>: <description>
```

Types: `feat`, `fix`, `refactor`, `perf`, `chore`, `ci`, `docs`, `test`
