"""Year-over-year growth."""

from decimal import Decimal

import pytest

from shared.indicators import year_over_year


def test_growth_is_a_percentage_of_the_base_year() -> None:
    assert year_over_year(current=Decimal("1150"), previous=Decimal("1000")) == Decimal("15.00")


def test_a_contraction_is_negative() -> None:
    assert year_over_year(current=Decimal("900"), previous=Decimal("1000")) == Decimal("-10.00")


def test_a_flat_year_is_zero() -> None:
    assert year_over_year(current=Decimal("1000"), previous=Decimal("1000")) == Decimal("0.00")


def test_growth_is_rounded_to_two_places() -> None:
    assert year_over_year(current=Decimal("1000"), previous=Decimal("300")) == Decimal("233.33")


@pytest.mark.parametrize("previous", [Decimal("0"), Decimal("-400")])
def test_growth_from_a_loss_or_zero_base_is_none(previous: Decimal) -> None:
    """-100 -> +50 is not "150% growth"; that is a TURNAROUND, and a human call."""
    assert year_over_year(current=Decimal("50"), previous=previous) is None


@pytest.mark.parametrize(
    ("current", "previous"),
    [(None, Decimal("100")), (Decimal("100"), None), (None, None)],
)
def test_growth_is_none_when_a_figure_is_missing(
    current: Decimal | None, previous: Decimal | None
) -> None:
    assert year_over_year(current=current, previous=previous) is None
