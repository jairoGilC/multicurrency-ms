from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.enums import Currency
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import ExchangeRate


@pytest.fixture
def provider() -> InMemoryRateProvider:
    return InMemoryRateProvider()


@pytest.fixture
def today() -> datetime:
    return datetime(2026, 2, 25, 12, 0, 0)


@pytest.fixture
def sample_rates(today: datetime) -> list[ExchangeRate]:
    return [
        ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.EUR,
            rate=Decimal("0.92"),
            timestamp=today,
        ),
        ExchangeRate(
            source_currency=Currency.EUR,
            target_currency=Currency.USD,
            rate=Decimal("1.087"),
            timestamp=today,
        ),
        ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.BRL,
            rate=Decimal("5.20"),
            timestamp=today,
        ),
        ExchangeRate(
            source_currency=Currency.BRL,
            target_currency=Currency.USD,
            rate=Decimal("0.1923"),
            timestamp=today,
        ),
        ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.THB,
            rate=Decimal("35.0"),
            timestamp=today,
        ),
        ExchangeRate(
            source_currency=Currency.THB,
            target_currency=Currency.USD,
            rate=Decimal("0.02857"),
            timestamp=today,
        ),
    ]


class TestSameCurrency:
    def test_same_currency_returns_one(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        result = provider.get_rate(Currency.USD, Currency.USD, today)
        assert result == Decimal("1")

    def test_same_currency_no_rates_loaded(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        result = provider.get_rate(Currency.EUR, Currency.EUR, today)
        assert result == Decimal("1")


class TestDirectRate:
    def test_exact_date_match(
        self,
        provider: InMemoryRateProvider,
        sample_rates: list[ExchangeRate],
        today: datetime,
    ) -> None:
        provider.load_rates(sample_rates)
        result = provider.get_rate(Currency.USD, Currency.EUR, today)
        assert result == Decimal("0.92")

    def test_closest_date_within_7_days(
        self,
        provider: InMemoryRateProvider,
        sample_rates: list[ExchangeRate],
        today: datetime,
    ) -> None:
        provider.load_rates(sample_rates)
        query_date = today + timedelta(days=3)
        result = provider.get_rate(Currency.USD, Currency.EUR, query_date)
        assert result == Decimal("0.92")

    def test_no_rate_beyond_7_days_raises(
        self,
        provider: InMemoryRateProvider,
        sample_rates: list[ExchangeRate],
        today: datetime,
    ) -> None:
        provider.load_rates(sample_rates)
        query_date = today + timedelta(days=10)
        with pytest.raises(ValueError, match="No rate"):
            provider.get_rate(Currency.USD, Currency.EUR, query_date)

    def test_prefers_closest_date(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.90"),
                timestamp=today - timedelta(days=5),
            ),
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.92"),
                timestamp=today - timedelta(days=1),
            ),
        ]
        provider.load_rates(rates)
        result = provider.get_rate(Currency.USD, Currency.EUR, today)
        assert result == Decimal("0.92")


class TestCrossRate:
    def test_cross_rate_via_usd(
        self,
        provider: InMemoryRateProvider,
        sample_rates: list[ExchangeRate],
        today: datetime,
    ) -> None:
        provider.load_rates(sample_rates)
        result = provider.get_rate(Currency.BRL, Currency.THB, today)
        expected = Decimal("0.1923") * Decimal("35.0")
        assert result == expected

    def test_cross_rate_no_intermediary_raises(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.92"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)
        with pytest.raises(ValueError, match="No rate"):
            provider.get_rate(Currency.BRL, Currency.THB, today)


class TestGetCurrentRate:
    def test_returns_most_recent_rate(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.90"),
                timestamp=today - timedelta(days=5),
            ),
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.93"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)
        result = provider.get_current_rate(Currency.USD, Currency.EUR)
        assert result == Decimal("0.93")

    def test_no_rate_available_raises(
        self, provider: InMemoryRateProvider
    ) -> None:
        with pytest.raises(ValueError, match="No rate"):
            provider.get_current_rate(Currency.USD, Currency.EUR)

    def test_same_currency_returns_one(
        self, provider: InMemoryRateProvider
    ) -> None:
        result = provider.get_current_rate(Currency.USD, Currency.USD)
        assert result == Decimal("1")


class TestGetRateAtDate:
    def test_returns_exchange_rate_model(
        self,
        provider: InMemoryRateProvider,
        sample_rates: list[ExchangeRate],
        today: datetime,
    ) -> None:
        provider.load_rates(sample_rates)
        result = provider.get_rate_at_date(Currency.USD, Currency.EUR, today)
        assert isinstance(result, ExchangeRate)
        assert result.source_currency == Currency.USD
        assert result.target_currency == Currency.EUR
        assert result.rate == Decimal("0.92")
        assert result.timestamp == today


class TestLoadRates:
    def test_bulk_load(self, provider: InMemoryRateProvider, today: datetime) -> None:
        rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.92"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)
        assert provider.get_rate(Currency.USD, Currency.EUR, today) == Decimal("0.92")

    def test_load_appends_to_existing(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        rates_1 = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.92"),
                timestamp=today,
            ),
        ]
        rates_2 = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.BRL,
                rate=Decimal("5.20"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates_1)
        provider.load_rates(rates_2)
        assert provider.get_rate(Currency.USD, Currency.EUR, today) == Decimal("0.92")
        assert provider.get_rate(Currency.USD, Currency.BRL, today) == Decimal("5.20")


class TestLatestRatesIndex:
    """Tests for the O(1) _latest_rates index in InMemoryRateProvider."""

    def test_get_current_rate_uses_index(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        """After loading rates, get_current_rate should return correct rate via index."""
        rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.90"),
                timestamp=today - timedelta(days=5),
            ),
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.93"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)
        result = provider.get_current_rate(Currency.USD, Currency.EUR)
        assert result == Decimal("0.93")

    def test_cross_rate_cache_returns_derived_rate(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        """Cross-rate via USD should be pre-computed in the index."""
        rates = [
            ExchangeRate(
                source_currency=Currency.BRL,
                target_currency=Currency.USD,
                rate=Decimal("0.20"),
                timestamp=today,
            ),
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.92"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)
        result = provider.get_current_rate(Currency.BRL, Currency.EUR)
        expected = Decimal("0.20") * Decimal("0.92")
        assert result == expected

    def test_loading_new_rates_updates_index(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        """Loading newer rates should update the _latest_rates index."""
        old_rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.90"),
                timestamp=today - timedelta(days=3),
            ),
        ]
        provider.load_rates(old_rates)
        assert provider.get_current_rate(Currency.USD, Currency.EUR) == Decimal("0.90")

        new_rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.95"),
                timestamp=today,
            ),
        ]
        provider.load_rates(new_rates)
        assert provider.get_current_rate(Currency.USD, Currency.EUR) == Decimal("0.95")

    def test_index_not_overwritten_by_older_rate(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        """Loading an older rate should NOT overwrite a newer one in the index."""
        rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.95"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)

        older_rates = [
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.80"),
                timestamp=today - timedelta(days=10),
            ),
        ]
        provider.load_rates(older_rates)
        assert provider.get_current_rate(Currency.USD, Currency.EUR) == Decimal("0.95")

    def test_direct_rate_preferred_over_cross_rate_in_index(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        """If a direct rate exists, it should be in the index and used over cross-rate."""
        rates = [
            ExchangeRate(
                source_currency=Currency.BRL,
                target_currency=Currency.EUR,
                rate=Decimal("0.18"),
                timestamp=today,
            ),
            ExchangeRate(
                source_currency=Currency.BRL,
                target_currency=Currency.USD,
                rate=Decimal("0.20"),
                timestamp=today,
            ),
            ExchangeRate(
                source_currency=Currency.USD,
                target_currency=Currency.EUR,
                rate=Decimal("0.92"),
                timestamp=today,
            ),
        ]
        provider.load_rates(rates)
        result = provider.get_current_rate(Currency.BRL, Currency.EUR)
        # Direct rate should be used, not cross-rate (0.20 * 0.92 = 0.184)
        assert result == Decimal("0.18")


class TestFallbackPopulatesIndex:
    """The O(N) fallback in get_current_rate should populate _latest_rates."""

    def test_fallback_populates_index(
        self, provider: InMemoryRateProvider, today: datetime
    ) -> None:
        """When fallback scan finds a rate, it should be stored in _latest_rates
        so the next call hits the index directly."""
        # Manually insert a rate into _all_rates without updating _latest_rates,
        # simulating a scenario where the index is missing the entry.
        rate = ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.THB,
            rate=Decimal("35.50"),
            timestamp=today,
        )
        provider._all_rates.append(rate)

        # Confirm the index does NOT have this pair yet
        assert (Currency.USD, Currency.THB) not in provider._latest_rates

        # First call: triggers the O(N) fallback scan
        result = provider.get_current_rate(Currency.USD, Currency.THB)
        assert result == Decimal("35.50")

        # After the fallback, _latest_rates should be populated
        assert (Currency.USD, Currency.THB) in provider._latest_rates
        assert provider._latest_rates[(Currency.USD, Currency.THB)][0] == Decimal("35.50")
        assert provider._latest_rates[(Currency.USD, Currency.THB)][1] == today

        # Second call: should hit the index (O(1)), returning the same result
        result2 = provider.get_current_rate(Currency.USD, Currency.THB)
        assert result2 == Decimal("35.50")
