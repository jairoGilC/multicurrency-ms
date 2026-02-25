from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from src.enums import Currency
from src.exchange.rate_provider import InMemoryRateProvider
from src.models import ExchangeRate

_BASE_URL = "https://api.frankfurter.app"

# Currencies supported by frankfurter.app (COP is NOT supported)
_SUPPORTED_CURRENCIES = {Currency.USD, Currency.EUR, Currency.BRL, Currency.MXN, Currency.THB}


class ExternalRateProvider:
    """Rate provider that fetches from the frankfurter.app API with optional fallback."""

    STATIC_COP_RATE = Decimal("4150")  # USD -> COP static fallback

    def __init__(self, fallback: InMemoryRateProvider | None = None) -> None:
        self._fallback = fallback
        self._cache: dict[tuple[Currency, Currency, str | None], Decimal] = {}

    @classmethod
    def from_fallback(cls, fallback: InMemoryRateProvider) -> ExternalRateProvider:
        return cls(fallback=fallback)

    def get_rate(self, source: Currency, target: Currency, date: datetime) -> Decimal:
        return self.get_rate_at_date(source, target, date).rate

    def get_current_rate(self, source: Currency, target: Currency) -> Decimal:
        if source == target:
            return Decimal("1")

        cop_rate = self._handle_cop(source, target)
        if cop_rate is not None:
            return cop_rate

        cache_key = (source, target, None)
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            rate = self._fetch_latest(source, target)
            self._cache[cache_key] = rate
            return rate
        except (URLError, OSError, json.JSONDecodeError, KeyError, ValueError) as err:
            if self._fallback is not None:
                return self._fallback.get_current_rate(source, target)
            raise ValueError(
                f"Failed to fetch rate for {source.value} -> {target.value} "
                "and no fallback available"
            ) from err

    def get_rate_at_date(self, source: Currency, target: Currency, date: datetime) -> ExchangeRate:
        if source == target:
            return ExchangeRate(
                source_currency=source,
                target_currency=target,
                rate=Decimal("1"),
                timestamp=date,
            )

        date_str = date.strftime("%Y-%m-%d")
        cache_key = (source, target, date_str)
        if cache_key in self._cache:
            rate = self._cache[cache_key]
        else:
            try:
                rate = self._fetch_historical(source, target, date_str)
                self._cache[cache_key] = rate
            except (URLError, OSError, json.JSONDecodeError, KeyError, ValueError) as err:
                if self._fallback is not None:
                    return self._fallback.get_rate_at_date(source, target, date)
                raise ValueError(
                    f"Failed to fetch historical rate for {source.value} -> {target.value} "
                    f"on {date_str} and no fallback available"
                ) from err

        return ExchangeRate(
            source_currency=source,
            target_currency=target,
            rate=rate,
            timestamp=date,
        )

    def _handle_cop(self, source: Currency, target: Currency) -> Decimal | None:
        """Handle COP pairs using static fallback rate since frankfurter doesn't support COP."""
        if source == Currency.USD and target == Currency.COP:
            return self.STATIC_COP_RATE
        if source == Currency.COP and target == Currency.USD:
            return Decimal("1") / self.STATIC_COP_RATE
        return None

    def _fetch_latest(self, source: Currency, target: Currency) -> Decimal:
        url = f"{_BASE_URL}/latest?from={source.value}&to={target.value}"
        data = self._api_call(url)
        return Decimal(str(data["rates"][target.value]))

    def _fetch_historical(self, source: Currency, target: Currency, date_str: str) -> Decimal:
        url = f"{_BASE_URL}/{date_str}?from={source.value}&to={target.value}"
        data = self._api_call(url)
        return Decimal(str(data["rates"][target.value]))

    @staticmethod
    def _api_call(url: str) -> dict[str, Any]:
        with urlopen(url) as response:
            result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            return result
