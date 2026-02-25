import json
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from src.enums import Currency
from src.exchange.external_rate_provider import ExternalRateProvider
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import ExchangeRate


@pytest.fixture
def today() -> datetime:
    return datetime(2026, 2, 25, 12, 0, 0)


@pytest.fixture
def fallback_provider(today: datetime) -> InMemoryRateProvider:
    provider = InMemoryRateProvider()
    provider.load_rates([
        ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.EUR,
            rate=Decimal("0.90"),
            timestamp=today,
        ),
        ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.COP,
            rate=Decimal("4200"),
            timestamp=today,
        ),
    ])
    return provider


def _mock_response(data: dict) -> MagicMock:
    """Create a mock urllib response with JSON data."""
    response = MagicMock()
    response.read.return_value = json.dumps(data).encode("utf-8")
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    return response


class TestSuccessfulRateFetch:
    @patch("src.exchange.external_rate_provider.urlopen")
    def test_get_current_rate_fetches_from_api(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.return_value = _mock_response({
            "base": "USD",
            "date": "2026-02-25",
            "rates": {"EUR": 0.92, "BRL": 5.2, "MXN": 17.5},
        })
        provider = ExternalRateProvider()
        result = provider.get_current_rate(Currency.USD, Currency.EUR)
        assert result == Decimal("0.92")
        mock_urlopen.assert_called_once()

    @patch("src.exchange.external_rate_provider.urlopen")
    def test_get_current_rate_reverse_pair(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.return_value = _mock_response({
            "base": "EUR",
            "date": "2026-02-25",
            "rates": {"USD": 1.087},
        })
        provider = ExternalRateProvider()
        result = provider.get_current_rate(Currency.EUR, Currency.USD)
        assert result == Decimal("1.087")


class TestCaching:
    @patch("src.exchange.external_rate_provider.urlopen")
    def test_cached_rate_avoids_second_api_call(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.return_value = _mock_response({
            "base": "USD",
            "date": "2026-02-25",
            "rates": {"EUR": 0.92},
        })
        provider = ExternalRateProvider()
        result1 = provider.get_current_rate(Currency.USD, Currency.EUR)
        result2 = provider.get_current_rate(Currency.USD, Currency.EUR)
        assert result1 == result2 == Decimal("0.92")
        assert mock_urlopen.call_count == 1


class TestFallbackBehavior:
    @patch("src.exchange.external_rate_provider.urlopen")
    def test_uses_fallback_on_api_failure(
        self,
        mock_urlopen: MagicMock,
        fallback_provider: InMemoryRateProvider,
    ) -> None:
        mock_urlopen.side_effect = URLError("Network error")
        provider = ExternalRateProvider(fallback=fallback_provider)
        result = provider.get_current_rate(Currency.USD, Currency.EUR)
        assert result == Decimal("0.90")

    @patch("src.exchange.external_rate_provider.urlopen")
    def test_raises_without_fallback_on_api_failure(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = URLError("Network error")
        provider = ExternalRateProvider()
        with pytest.raises(ValueError, match="Failed to fetch"):
            provider.get_current_rate(Currency.USD, Currency.EUR)

    def test_from_fallback_class_method(
        self, fallback_provider: InMemoryRateProvider
    ) -> None:
        provider = ExternalRateProvider.from_fallback(fallback_provider)
        assert provider._fallback is fallback_provider


class TestCOPHandling:
    @patch("src.exchange.external_rate_provider.urlopen")
    def test_cop_uses_static_fallback_rate(
        self, mock_urlopen: MagicMock
    ) -> None:
        """COP is not supported by frankfurter.app, so a static rate is used."""
        provider = ExternalRateProvider()
        result = provider.get_current_rate(Currency.USD, Currency.COP)
        assert result == ExternalRateProvider.STATIC_COP_RATE
        mock_urlopen.assert_not_called()

    @patch("src.exchange.external_rate_provider.urlopen")
    def test_cop_reverse_uses_inverse_static_rate(
        self, mock_urlopen: MagicMock
    ) -> None:
        provider = ExternalRateProvider()
        result = provider.get_current_rate(Currency.COP, Currency.USD)
        expected = Decimal("1") / ExternalRateProvider.STATIC_COP_RATE
        assert result == expected
        mock_urlopen.assert_not_called()


class TestGetRateAtDate:
    @patch("src.exchange.external_rate_provider.urlopen")
    def test_historical_rate_fetch(
        self, mock_urlopen: MagicMock, today: datetime
    ) -> None:
        mock_urlopen.return_value = _mock_response({
            "base": "USD",
            "date": "2025-01-15",
            "rates": {"EUR": 0.89},
        })
        provider = ExternalRateProvider()
        result = provider.get_rate_at_date(
            Currency.USD, Currency.EUR, datetime(2025, 1, 15)
        )
        assert isinstance(result, ExchangeRate)
        assert result.rate == Decimal("0.89")
        assert result.source_currency == Currency.USD
        assert result.target_currency == Currency.EUR

    @patch("src.exchange.external_rate_provider.urlopen")
    def test_historical_rate_cached(
        self, mock_urlopen: MagicMock, today: datetime
    ) -> None:
        mock_urlopen.return_value = _mock_response({
            "base": "USD",
            "date": "2025-01-15",
            "rates": {"EUR": 0.89},
        })
        provider = ExternalRateProvider()
        date = datetime(2025, 1, 15)
        provider.get_rate_at_date(Currency.USD, Currency.EUR, date)
        provider.get_rate_at_date(Currency.USD, Currency.EUR, date)
        assert mock_urlopen.call_count == 1

    @patch("src.exchange.external_rate_provider.urlopen")
    def test_historical_fallback_on_failure(
        self,
        mock_urlopen: MagicMock,
        fallback_provider: InMemoryRateProvider,
        today: datetime,
    ) -> None:
        mock_urlopen.side_effect = URLError("Timeout")
        provider = ExternalRateProvider(fallback=fallback_provider)
        result = provider.get_rate_at_date(Currency.USD, Currency.EUR, today)
        assert result.rate == Decimal("0.90")


class TestGetRate:
    @patch("src.exchange.external_rate_provider.urlopen")
    def test_get_rate_delegates_to_historical(
        self, mock_urlopen: MagicMock, today: datetime
    ) -> None:
        mock_urlopen.return_value = _mock_response({
            "base": "USD",
            "date": "2026-02-25",
            "rates": {"EUR": 0.92},
        })
        provider = ExternalRateProvider()
        result = provider.get_rate(Currency.USD, Currency.EUR, today)
        assert result == Decimal("0.92")
