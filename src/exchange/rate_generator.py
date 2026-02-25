import json
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from itertools import product

from src.enums import Currency
from src.models import ExchangeRate


class RateGenerator:
    BASE_RATES: dict[tuple[Currency, Currency], Decimal] = {
        (Currency.USD, Currency.EUR): Decimal("0.92"),
        (Currency.USD, Currency.BRL): Decimal("5.20"),
        (Currency.USD, Currency.MXN): Decimal("19.50"),
        (Currency.USD, Currency.COP): Decimal("4200"),
        (Currency.USD, Currency.THB): Decimal("35.0"),
    }

    DAILY_VOLATILITY: Decimal = Decimal("0.003")
    MEAN_REVERSION_STRENGTH: Decimal = Decimal("0.02")

    def generate_rates(self, days: int = 90) -> list[ExchangeRate]:
        random.seed(42)
        today = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
        start_date = today - timedelta(days=days - 1)

        usd_rates = self._generate_usd_based_rates(days, start_date)
        return self._derive_all_cross_rates(usd_rates, days, start_date)

    def save_rates(self, rates: list[ExchangeRate], filepath: str) -> None:
        data = [
            {
                "source_currency": r.source_currency.value,
                "target_currency": r.target_currency.value,
                "rate": str(r.rate),
                "timestamp": r.timestamp.isoformat(),
            }
            for r in rates
        ]
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def load_rates(self, filepath: str) -> list[ExchangeRate]:
        with open(filepath) as f:
            data = json.load(f)
        return [
            ExchangeRate(
                source_currency=Currency(item["source_currency"]),
                target_currency=Currency(item["target_currency"]),
                rate=Decimal(item["rate"]),
                timestamp=datetime.fromisoformat(item["timestamp"]),
            )
            for item in data
        ]

    def _generate_usd_based_rates(
        self, days: int, start_date: datetime
    ) -> dict[tuple[Currency, datetime], Decimal]:
        usd_rates: dict[tuple[Currency, datetime], Decimal] = {}
        currencies = [c for c in Currency if c != Currency.USD]

        for currency in currencies:
            base_rate = self.BASE_RATES[(Currency.USD, currency)]
            current_rate = float(base_rate)

            for day in range(days):
                date = start_date + timedelta(days=day)
                drift = random.gauss(0, float(self.DAILY_VOLATILITY))
                mean_reversion = float(self.MEAN_REVERSION_STRENGTH) * (
                    float(base_rate) - current_rate
                ) / float(base_rate)
                current_rate = current_rate * (1 + drift + mean_reversion)
                current_rate = max(current_rate, float(base_rate) * 0.5)

                quantized = Decimal(str(current_rate)).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
                usd_rates[(currency, date)] = quantized

        return usd_rates

    def _derive_all_cross_rates(
        self,
        usd_rates: dict[tuple[Currency, datetime], Decimal],
        days: int,
        start_date: datetime,
    ) -> list[ExchangeRate]:
        all_rates: list[ExchangeRate] = []
        currencies = list(Currency)

        for day in range(days):
            date = start_date + timedelta(days=day)

            for source, target in product(currencies, repeat=2):
                if source == target:
                    continue

                rate = self._compute_pair_rate(source, target, date, usd_rates)
                all_rates.append(
                    ExchangeRate(
                        source_currency=source,
                        target_currency=target,
                        rate=rate,
                        timestamp=date,
                    )
                )

        return all_rates

    def _compute_pair_rate(
        self,
        source: Currency,
        target: Currency,
        date: datetime,
        usd_rates: dict[tuple[Currency, datetime], Decimal],
    ) -> Decimal:
        if source == Currency.USD:
            return usd_rates[(target, date)]

        if target == Currency.USD:
            rate_source_per_usd = usd_rates[(source, date)]
            return (Decimal("1") / rate_source_per_usd).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )

        source_per_usd = usd_rates[(source, date)]
        target_per_usd = usd_rates[(target, date)]
        return (target_per_usd / source_per_usd).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
