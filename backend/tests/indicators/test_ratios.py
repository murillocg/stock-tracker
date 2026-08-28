"""ROIC, payout and PEG — including every case that must return None."""

from decimal import Decimal

import pytest

from shared.indicators import payout_ratio, peg, roic


def test_roic_is_nopat_over_invested_capital() -> None:
    # EBIT 1000, taxed at 34% -> NOPAT 660. Capital 600 + 400 = 1000. 66%.
    value = roic(
        ebit=Decimal("1000"),
        tax_rate=Decimal("0.34"),
        equity=Decimal("600"),
        net_debt=Decimal("400"),
    )

    assert value == Decimal("66.00")


def test_roic_counts_net_cash_against_invested_capital() -> None:
    """Net debt is negative for a cash-rich company, shrinking the capital base."""
    value = roic(
        ebit=Decimal("100"),
        tax_rate=Decimal("0"),
        equity=Decimal("500"),
        net_debt=Decimal("-300"),
    )

    assert value == Decimal("50.00")


def test_roic_is_rounded_to_two_places() -> None:
    value = roic(
        ebit=Decimal("100"),
        tax_rate=Decimal("0"),
        equity=Decimal("300"),
        net_debt=Decimal("0"),
    )

    assert value == Decimal("33.33")


@pytest.mark.parametrize(
    ("equity", "net_debt"),
    [(Decimal("0"), Decimal("0")), (Decimal("100"), Decimal("-400"))],
)
def test_roic_is_none_without_positive_invested_capital(equity: Decimal, net_debt: Decimal) -> None:
    assert (
        roic(ebit=Decimal("100"), tax_rate=Decimal("0"), equity=equity, net_debt=net_debt) is None
    )


@pytest.mark.parametrize("tax_rate", [Decimal("-0.1"), Decimal("1"), Decimal("1.5")])
def test_roic_rejects_an_impossible_tax_rate(tax_rate: Decimal) -> None:
    """The rate is a fraction; someone passing 34 instead of 0.34 must not get a number."""
    assert (
        roic(
            ebit=Decimal("100"),
            tax_rate=tax_rate,
            equity=Decimal("100"),
            net_debt=Decimal("0"),
        )
        is None
    )


def test_roic_is_none_when_any_input_is_missing() -> None:
    assert (
        roic(ebit=None, tax_rate=Decimal("0.34"), equity=Decimal("1"), net_debt=Decimal("0"))
        is None
    )


def test_payout_ratio_is_a_percentage_of_earnings() -> None:
    value = payout_ratio(dividends_paid=Decimal("250"), net_income=Decimal("1000"))

    assert value == Decimal("25.00")


def test_a_payout_above_one_hundred_is_kept() -> None:
    """Paying out more than you earn is a signal, not an error to clamp away."""
    value = payout_ratio(dividends_paid=Decimal("1200"), net_income=Decimal("1000"))

    assert value == Decimal("120.00")


@pytest.mark.parametrize("net_income", [Decimal("0"), Decimal("-500")])
def test_payout_ratio_is_none_on_a_loss(net_income: Decimal) -> None:
    assert payout_ratio(dividends_paid=Decimal("100"), net_income=net_income) is None


def test_peg_pairs_pe_against_growth() -> None:
    """A P/E of 15 on 15% growth is exactly the FAST_GROWER boundary."""
    assert peg(pe=Decimal("15"), earnings_growth=Decimal("15")) == Decimal("1.0000")


def test_peg_below_one_is_the_fast_grower_signal() -> None:
    value = peg(pe=Decimal("12"), earnings_growth=Decimal("30"))

    assert value == Decimal("0.4000")
    assert value < 1


@pytest.mark.parametrize("growth", [Decimal("0"), Decimal("-8")])
def test_peg_is_none_without_growth(growth: Decimal) -> None:
    assert peg(pe=Decimal("15"), earnings_growth=growth) is None


@pytest.mark.parametrize("pe", [Decimal("0"), Decimal("-4")])
def test_peg_is_none_for_a_loss_making_company(pe: Decimal) -> None:
    assert peg(pe=pe, earnings_growth=Decimal("20")) is None
