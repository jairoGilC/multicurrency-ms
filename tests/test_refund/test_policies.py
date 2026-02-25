"""Tests for refund policy strategies."""

from decimal import Decimal

import pytest

from src.enums import RefundPolicy
from src.exceptions import RefundEngineError
from src.refund.policies import (
    CurrentRatePolicy,
    CustomerFavorablePolicy,
    OriginalRatePolicy,
    TimeWeightedPolicy,
    get_policy,
)

# ---------------------------------------------------------------------------
# CustomerFavorablePolicy
# ---------------------------------------------------------------------------


class TestCustomerFavorablePolicy:
    """CustomerFavorablePolicy always returns the higher of the two rates."""

    @pytest.mark.parametrize(
        "original, current, expected",
        [
            (Decimal("0.192"), Decimal("0.200"), Decimal("0.200")),
            (Decimal("0.250"), Decimal("0.200"), Decimal("0.250")),
            (Decimal("0.192"), Decimal("0.192"), Decimal("0.192")),
        ],
        ids=["current-higher", "original-higher", "rates-equal"],
    )
    def test_picks_max_rate(
        self,
        original: Decimal,
        current: Decimal,
        expected: Decimal,
    ) -> None:
        policy = CustomerFavorablePolicy()
        assert policy.calculate_rate(original, current, days_elapsed=30) == expected

    def test_max_is_customer_favorable_for_source_to_dest_convention(
        self,
    ) -> None:
        """Document WHY max(original, current) is customer-favorable.

        Convention: rates represent source->destination conversion.
        Example: BRL->USD original=0.19 means 1 BRL buys 0.19 USD.

        If current=0.20, that means 1 BRL now buys 0.20 USD -- more
        destination currency per unit of source.  The customer is
        receiving the refund in the destination currency (USD), so the
        higher rate (0.20) yields more USD and is favorable to them.

        For a 1000 BRL refund:
          original rate 0.19 -> 190 USD
          current  rate 0.20 -> 200 USD  <-- customer gets more
        """
        policy = CustomerFavorablePolicy()
        original = Decimal("0.19")
        current = Decimal("0.20")
        refund_brl = Decimal("1000")

        rate = policy.calculate_rate(original, current, days_elapsed=30)

        assert rate == current  # max(0.19, 0.20) == 0.20
        # Verify this actually yields more destination currency
        assert refund_brl * rate > refund_brl * original

    def test_name(self) -> None:
        assert CustomerFavorablePolicy().name == "CUSTOMER_FAVORABLE"


# ---------------------------------------------------------------------------
# OriginalRatePolicy
# ---------------------------------------------------------------------------


class TestOriginalRatePolicy:
    """OriginalRatePolicy always returns the original rate."""

    @pytest.mark.parametrize(
        "original, current",
        [
            (Decimal("0.192"), Decimal("0.200")),
            (Decimal("0.250"), Decimal("0.100")),
        ],
        ids=["current-higher", "current-lower"],
    )
    def test_always_returns_original(self, original: Decimal, current: Decimal) -> None:
        policy = OriginalRatePolicy()
        assert policy.calculate_rate(original, current, days_elapsed=45) == original

    def test_name(self) -> None:
        assert OriginalRatePolicy().name == "ORIGINAL_RATE"


# ---------------------------------------------------------------------------
# CurrentRatePolicy
# ---------------------------------------------------------------------------


class TestCurrentRatePolicy:
    """CurrentRatePolicy always returns the current rate."""

    @pytest.mark.parametrize(
        "original, current",
        [
            (Decimal("0.192"), Decimal("0.200")),
            (Decimal("0.250"), Decimal("0.100")),
        ],
        ids=["current-higher", "current-lower"],
    )
    def test_always_returns_current(self, original: Decimal, current: Decimal) -> None:
        policy = CurrentRatePolicy()
        assert policy.calculate_rate(original, current, days_elapsed=45) == current

    def test_name(self) -> None:
        assert CurrentRatePolicy().name == "CURRENT_RATE"


# ---------------------------------------------------------------------------
# TimeWeightedPolicy
# ---------------------------------------------------------------------------


class TestTimeWeightedPolicy:
    """TimeWeightedPolicy blends rates linearly over a 90-day window."""

    def test_day_zero_returns_original(self) -> None:
        policy = TimeWeightedPolicy()
        original = Decimal("0.192")
        current = Decimal("0.200")
        result = policy.calculate_rate(original, current, days_elapsed=0)
        assert result == original

    def test_day_90_returns_current(self) -> None:
        policy = TimeWeightedPolicy()
        original = Decimal("0.192")
        current = Decimal("0.200")
        result = policy.calculate_rate(original, current, days_elapsed=90)
        assert result == current

    def test_day_45_returns_midpoint(self) -> None:
        policy = TimeWeightedPolicy()
        original = Decimal("0.192")
        current = Decimal("0.200")
        result = policy.calculate_rate(original, current, days_elapsed=45)
        expected = (original + current) / 2
        assert result == expected

    def test_beyond_90_days_caps_at_current(self) -> None:
        policy = TimeWeightedPolicy()
        original = Decimal("0.192")
        current = Decimal("0.200")
        result = policy.calculate_rate(original, current, days_elapsed=180)
        assert result == current

    def test_name(self) -> None:
        assert TimeWeightedPolicy().name == "TIME_WEIGHTED"


# ---------------------------------------------------------------------------
# get_policy factory
# ---------------------------------------------------------------------------


class TestGetPolicyFactory:
    """The get_policy factory returns the correct strategy for each enum."""

    @pytest.mark.parametrize(
        "policy_enum, expected_type",
        [
            (RefundPolicy.CUSTOMER_FAVORABLE, CustomerFavorablePolicy),
            (RefundPolicy.ORIGINAL_RATE, OriginalRatePolicy),
            (RefundPolicy.CURRENT_RATE, CurrentRatePolicy),
            (RefundPolicy.TIME_WEIGHTED, TimeWeightedPolicy),
        ],
        ids=[p.value for p in RefundPolicy],
    )
    def test_returns_correct_strategy(self, policy_enum: RefundPolicy, expected_type: type) -> None:
        strategy = get_policy(policy_enum)
        assert isinstance(strategy, expected_type)

    def test_raises_for_invalid_policy(self) -> None:
        with pytest.raises(RefundEngineError, match="Unknown refund policy"):
            get_policy("NOT_A_POLICY")  # type: ignore[arg-type]
