from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from src.enums import Currency
from src.exceptions import RateNotFoundError
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
        self._latest_rates: dict[tuple[Currency, Currency], tuple[Decimal, datetime]] = {}

    def load_rates(self, rates: list[ExchangeRate]) -> None:
        for rate in rates:
            key = (rate.source_currency, rate.target_currency, rate.timestamp.strftime("%Y-%m-%d"))
            self._rates[key] = rate.rate
            self._all_rates.append(rate)

            pair = (rate.source_currency, rate.target_currency)
            existing = self._latest_rates.get(pair)
            if existing is None or rate.timestamp > existing[1]:
                self._latest_rates[pair] = (rate.rate, rate.timestamp)

        self._recompute_cross_rates()

    def get_rate(self, source: Currency, target: Currency, date: datetime) -> Decimal:
        if source == target:
            return Decimal("1")

        rate = self._find_closest_rate(source, target, date)
        if rate is not None:
            return rate

        rate = self._derive_cross_rate(source, target, date)
        if rate is not None:
            return rate

        raise RateNotFoundError(f"No rate found for {source.value} -> {target.value} near {date}")

    def get_current_rate(self, source: Currency, target: Currency) -> Decimal:
        if source == target:
            return Decimal("1")

        entry = self._latest_rates.get((source, target))
        if entry is not None:
            return entry[0]

        # Fallback to O(N) scan for any edge cases not in the index
        matching = [
            r
            for r in self._all_rates
            if r.source_currency == source and r.target_currency == target
        ]
        if not matching:
            raise RateNotFoundError(f"No rate found for {source.value} -> {target.value}")

        most_recent = max(matching, key=lambda r: r.timestamp)
        self._latest_rates[(source, target)] = (most_recent.rate, most_recent.timestamp)
        return most_recent.rate

    def get_rate_at_date(self, source: Currency, target: Currency, date: datetime) -> ExchangeRate:
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
                if candidate_key in self._rates and (best_delta is None or day_offset < best_delta):
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

    def _find_most_recent_cross_rate(self, source: Currency, target: Currency) -> Decimal | None:
        src_usd = self._latest_rates.get((source, Currency.USD))
        usd_tgt = self._latest_rates.get((Currency.USD, target))

        if src_usd is not None and usd_tgt is not None:
            return src_usd[0] * usd_tgt[0]

        return None

    def _recompute_cross_rates(self) -> None:
        """Pre-compute cross-rates via USD for pairs not directly in _latest_rates."""
        currencies = set()
        for src, tgt in self._latest_rates:
            currencies.add(src)
            currencies.add(tgt)

        for src in currencies:
            for tgt in currencies:
                if src == tgt:
                    continue
                if (src, tgt) in self._latest_rates:
                    continue
                src_usd = self._latest_rates.get((src, Currency.USD))
                usd_tgt = self._latest_rates.get((Currency.USD, tgt))
                if src_usd is not None and usd_tgt is not None:
                    cross_rate = src_usd[0] * usd_tgt[0]
                    self._latest_rates[(src, tgt)] = (cross_rate, min(src_usd[1], usd_tgt[1]))
