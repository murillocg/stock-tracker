"""Converting between currencies, and weighting a portfolio that spans two."""

import datetime as dt
from decimal import Decimal

import pytest

from shared.models import Currency, Transaction, TransactionType
from shared.positions import ExchangeRates, current_position, value, with_weights

USDBRL = Decimal("5.2005")


def rates() -> ExchangeRates:
    return ExchangeRates(base=Currency.BRL, rates={Currency.USD: USDBRL})


def buy(ticker: str, quantity: str, price: str, currency: Currency) -> Transaction:
    return Transaction(
        ticker=ticker,
        date=dt.date(2026, 1, 5),
        type=TransactionType.BUY,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        currency=currency,
        id=f"{ticker}-1",
    )


class TestExchangeRates:
    def test_the_base_currency_converts_to_itself(self) -> None:
        assert rates().rate_for(Currency.BRL) == Decimal(1)

    def test_a_known_currency_returns_its_rate(self) -> None:
        assert rates().rate_for(Currency.USD) == USDBRL

    def test_an_uncollected_rate_is_none_not_one(self) -> None:
        """The distinction the whole module exists for: a missing rate must never
        silently become 1:1, which would book $1,800 as R$1,800."""
        assert ExchangeRates(base=Currency.BRL).rate_for(Currency.USD) is None
        assert ExchangeRates(base=Currency.BRL).convert(Decimal("1800"), Currency.USD) is None

    def test_conversion_rounds_to_cents(self) -> None:
        assert rates().convert(Decimal("1800.00"), Currency.USD) == Decimal("9360.90")


class TestValueWithARate:
    def test_a_usd_holding_keeps_its_own_currency_on_the_row(self) -> None:
        position = current_position("MSFT", [buy("MSFT", "4", "443.02", Currency.USD)])
        assert position is not None

        valuation = value(position, Decimal("450.00"), USDBRL)

        # The row stays in dollars — it has to match what Avenue shows.
        assert valuation.market_value == Decimal("1800.00")
        # ...and only the base figures are in reais.
        assert valuation.base_market_value == Decimal("9360.90")
        assert valuation.base_invested == Decimal("9215.70")  # 4 x 443.02 x 5.2005

    def test_a_missing_rate_leaves_the_base_figures_empty(self) -> None:
        position = current_position("MSFT", [buy("MSFT", "4", "443.02", Currency.USD)])
        assert position is not None

        valuation = value(position, Decimal("450.00"), None)

        assert valuation.market_value == Decimal("1800.00")
        assert valuation.base_market_value is None
        assert valuation.base_invested is None


class TestWeightsAcrossCurrencies:
    def test_a_dollar_holding_is_weighed_against_a_real_one(self) -> None:
        """A $1,800 position is worth more than an R$5,000 one, and the weights
        have to say so. Comparing the raw numbers would rank them backwards."""
        brl = current_position("VALE3", [buy("VALE3", "100", "50.00", Currency.BRL)])
        usd = current_position("MSFT", [buy("MSFT", "4", "443.02", Currency.USD)])
        assert brl is not None and usd is not None

        weighted = with_weights(
            {
                "VALE3": value(brl, Decimal("50.00"), Decimal(1)),
                "MSFT": value(usd, Decimal("450.00"), USDBRL),
            }
        )

        assert weighted["MSFT"].weight == Decimal("65.18")  # R$9,360.90 of R$14,360.90
        assert weighted["VALE3"].weight == Decimal("34.82")
        assert weighted["MSFT"].weight + weighted["VALE3"].weight == Decimal("100.00")

    def test_an_unconvertible_holding_is_left_out_of_the_denominator(self) -> None:
        """It gets no weight, and the ones that remain still sum to 100 — they
        describe the part of the portfolio we can actually measure."""
        brl = current_position("VALE3", [buy("VALE3", "100", "50.00", Currency.BRL)])
        usd = current_position("MSFT", [buy("MSFT", "4", "443.02", Currency.USD)])
        assert brl is not None and usd is not None

        weighted = with_weights(
            {
                "VALE3": value(brl, Decimal("50.00"), Decimal(1)),
                "MSFT": value(usd, Decimal("450.00"), None),
            }
        )

        assert weighted["MSFT"].weight is None
        assert weighted["VALE3"].weight == Decimal("100.00")


@pytest.mark.parametrize("rate", [Decimal("5.2005"), Decimal(1)])
def test_weights_do_not_depend_on_the_rate_in_a_single_currency_book(rate: Decimal) -> None:
    """Sanity check on the conversion: scaling every holding by the same rate
    cannot change anybody's share of the total."""
    one = current_position("A", [buy("A", "10", "10.00", Currency.USD)])
    two = current_position("B", [buy("B", "30", "10.00", Currency.USD)])
    assert one is not None and two is not None

    weighted = with_weights(
        {"A": value(one, Decimal("10.00"), rate), "B": value(two, Decimal("10.00"), rate)}
    )

    assert weighted["A"].weight == Decimal("25.00")
    assert weighted["B"].weight == Decimal("75.00")
