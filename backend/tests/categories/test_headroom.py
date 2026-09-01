"""Room against a category's own targets, and how it aggregates."""

from decimal import Decimal

from shared.categories.aggregate import overall_headroom
from shared.categories.rules import (
    HEADROOM_CEILING,
    HEADROOM_FLOOR,
    Band,
    headroom,
)
from shared.categories.signals import Check, Signal


def measured(name: str, room: Decimal | None) -> Check:
    return Check(name=name, value=Decimal(1), signal=Signal.GREEN, explanation="", headroom=room)


class TestOneCheck:
    def test_at_target_is_one(self) -> None:
        lower = Band(green=Decimal("15"), yellow=Decimal("25"))
        higher = Band(green=Decimal("15"), yellow=Decimal("10"), lower_is_better=False)

        assert headroom(Decimal("15"), lower) == Decimal("1.00")
        assert headroom(Decimal("15"), higher) == Decimal("1.00")

    def test_directions_are_normalised_so_ratios_compare(self) -> None:
        """A P/E of 8 against a limit of 15 and an ROE of 30 against a floor of 15
        are the same amount of room. Without this they could not be averaged."""
        cheap = headroom(Decimal("8"), Band(green=Decimal("15"), yellow=Decimal("25")))
        profitable = headroom(
            Decimal("30"), Band(green=Decimal("15"), yellow=Decimal("10"), lower_is_better=False)
        )

        assert cheap == Decimal("1.88")
        assert profitable == Decimal("2.00")

    def test_net_cash_lands_at_the_top_not_the_bottom(self) -> None:
        """BPAC11's net debt / EBITDA is -6: it holds more cash than debt. A raw
        division would make that hugely negative and sort it below a company
        drowning in debt."""
        assert headroom(Decimal("-6"), Band(green=Decimal("2"), yellow=Decimal("3"))) == (
            HEADROOM_CEILING
        )

    def test_extremes_are_clamped(self) -> None:
        """MU's P/B of 10.49 against a limit of 1 is a headroom of 0.095. True,
        and not something one check should be allowed to decide alone."""
        assert headroom(Decimal("10.49"), Band(green=Decimal("1"), yellow=Decimal("2"))) == (
            HEADROOM_FLOOR
        )
        assert headroom(Decimal("0.1"), Band(green=Decimal("1"), yellow=Decimal("2"))) == (
            HEADROOM_CEILING
        )

    def test_a_range_rule_has_no_headroom(self) -> None:
        """Payout is unhealthy at both ends — 15% is hoarding, 110% is borrowing
        to pay you — so there is no single direction to measure from."""
        assert headroom(Decimal("73"), Band(green=Decimal(0), yellow=Decimal(0))) is None

    def test_a_missing_value_has_no_headroom(self) -> None:
        assert headroom(None, Band(green=Decimal("15"), yellow=Decimal("25"))) is None


class TestAggregate:
    def test_it_is_geometric_not_arithmetic(self) -> None:
        """Twice the room on one measure and half on another is at target overall.
        The arithmetic mean would call that 1.25."""
        both = overall_headroom([measured("a", Decimal("2")), measured("b", Decimal("0.5"))])
        assert both == Decimal("1.00")

    def test_thin_evidence_is_pulled_toward_neutral(self) -> None:
        """The flaw this exists to fix: CPLE3 scored 1.46 on dividend yield alone
        while ITSA4 scored 1.26 across three checks, and the raw mean ranked the
        thinner evidence first."""
        alone = overall_headroom([measured("Dividend yield", Decimal("1.46"))])
        assert alone is not None
        assert alone < Decimal("1.46")
        assert alone == Decimal("1.21")

    def test_more_checks_are_shrunk_less(self) -> None:
        """Confidence rises with evidence: the same mean survives more intact the
        more checks produced it."""
        one = overall_headroom([measured("a", Decimal("2"))])
        four = overall_headroom([measured(str(i), Decimal("2")) for i in range(4)])

        assert one is not None and four is not None
        assert one < four < Decimal("2")

    def test_checks_without_headroom_are_skipped_not_counted(self) -> None:
        """A payout rule contributes nothing, and must not count as evidence
        either — otherwise it would reduce the shrink without earning it."""
        with_payout = overall_headroom(
            [measured("Dividend yield", Decimal("1.46")), measured("Payout ratio", None)]
        )
        assert with_payout == overall_headroom([measured("Dividend yield", Decimal("1.46"))])

    def test_nothing_measurable_gives_nothing(self) -> None:
        assert overall_headroom([]) is None
        assert overall_headroom([measured("Payout ratio", None)]) is None
