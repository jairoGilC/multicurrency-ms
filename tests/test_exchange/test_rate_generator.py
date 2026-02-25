import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from src.enums import Currency
from src.exchange.rate_generator import RateGenerator


@pytest.fixture
def generator() -> RateGenerator:
    return RateGenerator()


class TestGenerateRates:
    def test_generates_rates_for_all_currency_pairs(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates(days=10)
        pairs = {(r.source_currency, r.target_currency) for r in rates}
        currencies = list(Currency)
        for source in currencies:
            for target in currencies:
                if source != target:
                    assert (source, target) in pairs

    def test_generates_correct_number_of_days(self, generator: RateGenerator) -> None:
        days = 10
        rates = generator.generate_rates(days=days)
        currencies = list(Currency)
        num_pairs = len(currencies) * (len(currencies) - 1)
        assert len(rates) == days * num_pairs

    def test_rates_are_positive(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates(days=30)
        for rate in rates:
            assert rate.rate > 0

    def test_rates_are_reproducible(self) -> None:
        gen1 = RateGenerator()
        gen2 = RateGenerator()
        rates1 = gen1.generate_rates(days=10)
        rates2 = gen2.generate_rates(days=10)
        for r1, r2 in zip(rates1, rates2, strict=True):
            assert r1.rate == r2.rate

    def test_rates_span_correct_date_range(self, generator: RateGenerator) -> None:
        days = 30
        rates = generator.generate_rates(days=days)
        timestamps = sorted({r.timestamp for r in rates})
        assert len(timestamps) == days
        newest = max(timestamps)
        oldest = min(timestamps)
        assert (newest - oldest).days == days - 1

    def test_default_90_days(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates()
        timestamps = {r.timestamp for r in rates}
        assert len(timestamps) == 90

    def test_uses_decimal_precision(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates(days=5)
        for rate in rates:
            assert isinstance(rate.rate, Decimal)

    def test_same_currency_pairs_not_generated(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates(days=5)
        for rate in rates:
            assert rate.source_currency != rate.target_currency


class TestSaveAndLoadRates:
    def test_save_and_load_roundtrip(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates(days=5)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            filepath = f.name

        generator.save_rates(rates, filepath)
        loaded = generator.load_rates(filepath)

        assert len(loaded) == len(rates)
        for original, loaded_rate in zip(rates, loaded, strict=True):
            assert original.source_currency == loaded_rate.source_currency
            assert original.target_currency == loaded_rate.target_currency
            assert original.rate == loaded_rate.rate

        Path(filepath).unlink()

    def test_save_creates_valid_json(self, generator: RateGenerator) -> None:
        rates = generator.generate_rates(days=3)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            filepath = f.name

        generator.save_rates(rates, filepath)

        with open(filepath) as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == len(rates)

        Path(filepath).unlink()
