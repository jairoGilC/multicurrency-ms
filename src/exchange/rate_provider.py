from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.enums import Currency
from src.models import ExchangeRate


class RateProvider(Protocol):
    def get_rate(self, source: Currency, target: Currency, date: datetime) -> Decimal: ...

    def get_current_rate(self, source: Currency, target: Currency) -> Decimal: ...

    def get_rate_at_date(
        self, source: Currency, target: Currency, date: datetime
    ) -> ExchangeRate: ...


class InMemoryRateProvider:
    def __init__(self) -> None:
        self._rates: dict[tuple[Currency, Currency, str], Decimal] = {}
        self._all_rates: list[ExchangeRate] = []

    def load_rates(self, rates: list[ExchangeRate]) -> None:
        for rate in rates:
            key = (rate.source_currency, rate.target_currency, rate.timestamp.strftime("%Y-%m-%d"))
            self._rates[key] = rate.rate
            self._all_rates.append(rate)

    def get_rate(self, source: Currency, target: Currency, date: datetime) -> Decimal:
        if source == target:
            return Decimal("1")

        rate = self._find_closest_rate(source, target, date)
        if rate is not None:
            return rate

        rate = self._derive_cross_rate(source, target, date)
        if rate is not None:
            return rate

        raise ValueError(f"No rate found for {source.value} -> {target.value} near {date}")

    def get_current_rate(self, source: Currency, target: Currency) -> Decimal:
        if source == target:
            return Decimal("1")

        matching = [
            r for r in self._all_rates
            if r.source_currency == source and r.target_currency == target
        ]
        if not matching:
            matching_cross = self._find_most_recent_cross_rate(source, target)
            if matching_cross is not None:
                return matching_cross
            raise ValueError(f"No rate found for {source.value} -> {target.value}")

        most_recent = max(matching, key=lambda r: r.timestamp)
        return most_recent.rate

    def get_rate_at_date(
        self, source: Currency, target: Currency, date: datetime
    ) -> ExchangeRate:
        rate = self.get_rate(source, target, date)
        return ExchangeRate(
            source_currency=source,
            target_currency=target,
            rate=rate,
            timestamp=date,
        )

    def _find_closest_rate(
        self, source: Currency, target: Currency, date: datetime
    ) -> Decimal | None:
        date_str = date.strftime("%Y-%m-%d")
        key = (source, target, date_str)
        if key in self._rates:
            return self._rates[key]

        best_rate: Decimal | None = None
        best_delta: int | None = None

        for day_offset in range(1, 8):
            for direction in (-1, 1):
                candidate = date + timedelta(days=day_offset * direction)
                candidate_str = candidate.strftime("%Y-%m-%d")
                candidate_key = (source, target, candidate_str)
                if candidate_key in self._rates:
                    if best_delta is None or day_offset < best_delta:
                        best_delta = day_offset
                        best_rate = self._rates[candidate_key]

        return best_rate

    def _derive_cross_rate(
        self, source: Currency, target: Currency, date: datetime
    ) -> Decimal | None:
        source_to_usd = self._find_closest_rate(source, Currency.USD, date)
        usd_to_target = self._find_closest_rate(Currency.USD, target, date)

        if source_to_usd is not None and usd_to_target is not None:
            return source_to_usd * usd_to_target

        return None

    def _find_most_recent_cross_rate(
        self, source: Currency, target: Currency
    ) -> Decimal | None:
        source_to_usd = [
            r for r in self._all_rates
            if r.source_currency == source and r.target_currency == Currency.USD
        ]
        usd_to_target = [
            r for r in self._all_rates
            if r.source_currency == Currency.USD and r.target_currency == target
        ]

        if not source_to_usd or not usd_to_target:
            return None

        latest_source = max(source_to_usd, key=lambda r: r.timestamp)
        latest_target = max(usd_to_target, key=lambda r: r.timestamp)
        return latest_source.rate * latest_target.rate
