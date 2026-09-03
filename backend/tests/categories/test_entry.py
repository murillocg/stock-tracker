"""Inverting a category's thresholds into the price that would satisfy them."""

from decimal import Decimal

from shared.categories.entry import SANITY_MULTIPLE, entry_price
from shared.categories.signals import Check, Elasticity, Signal


def priced(
    name: str,
    value: str | None,
    green: str,
    elasticity: Elasticity,
    signal: Signal = Signal.GREEN,
) -> Check:
    return Check(
        name=name,
        value=None if value is None else Decimal(value),
        signal=signal,
        explanation="",
        elasticity=elasticity,
        green=Decimal(green),
    )


class TestProportional:
    def test_a_ratio_above_its_limit_needs_a_fall(self) -> None:
        """A P/B of 2 against a limit of 1 halves: the price must halve too."""
        found = entry_price(
            [priced("P/B", "2", "1", Elasticity.PROPORTIONAL, Signal.YELLOW)],
            Decimal("100"),
        )
        assert found.price == Decimal("50.00")
        assert found.discount_needed == Decimal("-50.00")

    def test_a_ratio_already_inside_its_limit_reports_room_above(self) -> None:
        """CMIG4 at a P/E of 6.83 against 15 is already cheap; the entry price
        sits above today's, and the sign says so."""
        found = entry_price(
            [priced("P/E", "6.8294", "15", Elasticity.PROPORTIONAL)], Decimal("10.97")
        )
        assert found.price == Decimal("24.09")
        assert found.discount_needed is not None
        assert found.discount_needed > 0

    def test_the_most_demanding_check_sets_the_price(self) -> None:
        """Every check has to pass, so the lowest target wins — cheap on P/E but
        not on P/B is not cheap enough."""
        found = entry_price(
            [
                priced("P/E", "10", "15", Elasticity.PROPORTIONAL),
                priced("P/B", "4", "1", Elasticity.PROPORTIONAL, Signal.RED),
            ],
            Decimal("100"),
        )
        assert found.price == Decimal("25.00")


class TestInverse:
    def test_a_yield_below_its_floor_needs_a_fall(self) -> None:
        """HPQ yields 3.96% against a 5% floor: the price has to drop for the
        income on it to rise. The one check that moves the other way."""
        found = entry_price(
            [priced("Dividend yield", "3.96", "5", Elasticity.INVERSE, Signal.YELLOW)],
            Decimal("31.99"),
        )
        assert found.price == Decimal("25.34")
        assert found.discount_needed == Decimal("-20.79")


class TestWhatPriceCannotFix:
    def test_a_failing_quality_test_is_reported_as_blocking(self) -> None:
        """Quality does not go on sale: no price turns a low ROE into a high one."""
        found = entry_price(
            [
                priced("P/E", "10", "15", Elasticity.PROPORTIONAL),
                priced("ROE", "5", "15", Elasticity.INDEPENDENT, Signal.RED),
            ],
            Decimal("100"),
        )
        assert found.blocked_by == ["ROE"]
        # The price test is still a real fact and is still reported.
        assert found.price == Decimal("150.00")

    def test_a_merely_amber_quality_check_does_not_block(self) -> None:
        """YELLOW is a caveat, not a bar — listing it would make almost every
        stock look structurally broken."""
        found = entry_price(
            [priced("ROE", "12", "15", Elasticity.INDEPENDENT, Signal.YELLOW)],
            Decimal("100"),
        )
        assert found.blocked_by == []


class TestRefusals:
    def test_a_ratio_far_past_its_limit_is_not_inverted(self) -> None:
        """KLBN4's P/E of 133 against 15 inverts to R$ 0,43 — an artefact of one
        depressed quarter, not a target. Better to say nothing."""
        found = entry_price(
            [priced("P/E", "133.3333", "15", Elasticity.PROPORTIONAL, Signal.RED)],
            Decimal("3.84"),
        )
        assert found.price is None
        assert found.unbounded == ["P/E"]

    def test_the_sanity_bound_is_inclusive_of_reasonable_extremes(self) -> None:
        """Right at the bound it still inverts, so the rule is a cliff we chose
        rather than one that crept in."""
        at_bound = priced(
            "P/E", str(Decimal("15") * SANITY_MULTIPLE), "15", Elasticity.PROPORTIONAL, Signal.RED
        )
        assert entry_price([at_bound], Decimal("100")).price == Decimal("20.00")

    def test_a_missing_value_yields_no_entry_price(self) -> None:
        found = entry_price(
            [priced("P/E", None, "15", Elasticity.PROPORTIONAL, Signal.INSUFFICIENT_DATA)],
            Decimal("100"),
        )
        assert found.price is None
        assert found.unbounded == []

    def test_no_price_based_check_at_all_yields_nothing(self) -> None:
        """A turnaround is judged on debt and margins, neither of which price
        touches — so there is no entry price to compute, and that is not a bug."""
        found = entry_price(
            [priced("Net debt / EBITDA", "4", "2", Elasticity.INDEPENDENT, Signal.RED)],
            Decimal("100"),
        )
        assert found.price is None
        assert found.blocked_by == ["Net debt / EBITDA"]

    def test_a_zero_price_is_refused_rather_than_dividing_by_it(self) -> None:
        found = entry_price([priced("P/E", "10", "15", Elasticity.PROPORTIONAL)], Decimal("0"))
        assert found.price is None
