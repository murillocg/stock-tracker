"""Category rulesets, including the cases the real portfolio surfaced."""

import datetime as dt
from decimal import Decimal

import pytest

from shared.categories import Signal, evaluate, worst
from shared.models import (
    Currency,
    DailySnapshot,
    ListType,
    LynchCategory,
    Market,
    ProviderName,
    Stock,
)

AS_OF = dt.date(2026, 8, 28)


def build_snapshot(**values: object) -> DailySnapshot:
    return DailySnapshot.model_validate(
        {"ticker": "TEST3", "date": AS_OF, "price": Decimal("10"), **values}
    )


def build_stock(category: LynchCategory | None, **values: object) -> Stock:
    return Stock.model_validate(
        {
            "ticker": "TEST3",
            "name": "Test SA",
            "market": Market.B3,
            "currency": Currency.BRL,
            "quote_provider": ProviderName.BRAPI,
            "list_type": ListType.PORTFOLIO,
            "category": category,
            **values,
        }
    )


def signals_by_name(evaluation: object) -> dict[str, Signal]:
    return {check.name: check.signal for check in evaluation.checks}  # type: ignore[attr-defined]


# --- worst() -----------------------------------------------------------------


def test_one_red_outranks_any_number_of_greens() -> None:
    """Averaging would let a bad metric hide behind good ones."""
    assert worst([Signal.GREEN, Signal.GREEN, Signal.RED]) is Signal.RED


def test_gaps_are_ignored_when_something_is_decidable() -> None:
    assert worst([Signal.INSUFFICIENT_DATA, Signal.GREEN]) is Signal.GREEN


def test_all_gaps_never_reads_as_green() -> None:
    assert worst([Signal.INSUFFICIENT_DATA] * 3) is Signal.INSUFFICIENT_DATA


def test_no_checks_at_all_is_insufficient() -> None:
    assert worst([]) is Signal.INSUFFICIENT_DATA


# --- dispatch ----------------------------------------------------------------


def test_an_unclassified_stock_is_never_judged() -> None:
    """The Lynch tag is manual; no ruleset applies until it is set."""
    evaluation = evaluate(build_stock(None), build_snapshot(pe=Decimal("8")))

    assert evaluation.signal is Signal.NEEDS_REVIEW
    assert evaluation.checks[0].name == "Category"


def test_a_stock_with_no_snapshot_is_insufficient() -> None:
    evaluation = evaluate(build_stock(LynchCategory.STALWART))

    assert evaluation.signal is Signal.INSUFFICIENT_DATA
    assert evaluation.checks == []


def test_the_denormalised_current_snapshot_is_used_by_default() -> None:
    stock = build_stock(LynchCategory.ASSET_PLAY, current=build_snapshot(pb=Decimal("0.6")))

    assert evaluate(stock).signal is Signal.GREEN


# --- per-category ------------------------------------------------------------


def test_fast_grower_is_green_when_peg_is_below_one() -> None:
    snapshot = build_snapshot(pe=Decimal("12"), earnings_cagr_5y=Decimal("30"))

    evaluation = evaluate(build_stock(LynchCategory.FAST_GROWER), snapshot)

    assert signals_by_name(evaluation)["PEG"] is Signal.GREEN
    assert evaluation.signal is Signal.GREEN


def test_fast_grower_is_red_when_growth_does_not_justify_the_price() -> None:
    snapshot = build_snapshot(pe=Decimal("40"), earnings_cagr_5y=Decimal("5"))

    evaluation = evaluate(build_stock(LynchCategory.FAST_GROWER), snapshot)

    assert evaluation.signal is Signal.RED


def test_stalwart_weighs_price_returns_and_debt() -> None:
    snapshot = build_snapshot(
        pe=Decimal("12"), roe=Decimal("18"), net_debt_to_ebitda=Decimal("1.5")
    )

    evaluation = evaluate(build_stock(LynchCategory.STALWART), snapshot)

    assert set(signals_by_name(evaluation)) == {"P/E", "ROE", "Net debt / EBITDA"}
    assert evaluation.signal is Signal.GREEN


def test_stalwart_turns_red_on_leverage_alone() -> None:
    snapshot = build_snapshot(
        pe=Decimal("12"), roe=Decimal("18"), net_debt_to_ebitda=Decimal("4.5")
    )

    assert evaluate(build_stock(LynchCategory.STALWART), snapshot).signal is Signal.RED


def test_a_cyclical_is_never_decided_by_the_app() -> None:
    """CLAUDE.md: the app flags, it does not decide. Checks still computed."""
    snapshot = build_snapshot(pb=Decimal("0.7"))

    evaluation = evaluate(build_stock(LynchCategory.CYCLICAL), snapshot)

    assert evaluation.signal is Signal.NEEDS_REVIEW
    assert signals_by_name(evaluation)["P/B"] is Signal.GREEN


def test_a_cyclical_is_not_judged_on_pe() -> None:
    """At the bottom of a cycle P/E looks expensive exactly when it is cheapest."""
    evaluation = evaluate(build_stock(LynchCategory.CYCLICAL), build_snapshot(pe=Decimal("45")))

    assert "P/E" not in signals_by_name(evaluation)


def test_a_turnaround_is_never_decided_by_the_app() -> None:
    snapshot = build_snapshot(net_debt_to_ebitda=Decimal("1"), ebitda_margin=Decimal("25"))

    assert evaluate(build_stock(LynchCategory.TURNAROUND), snapshot).signal is Signal.NEEDS_REVIEW


def test_asset_play_is_green_below_book() -> None:
    evaluation = evaluate(build_stock(LynchCategory.ASSET_PLAY), build_snapshot(pb=Decimal("0.8")))

    assert evaluation.signal is Signal.GREEN


def test_slow_grower_reports_the_free_tier_gap_honestly() -> None:
    """No free source supplies dividend yield or payout, so we say so."""
    evaluation = evaluate(build_stock(LynchCategory.SLOW_GROWER), build_snapshot())

    assert evaluation.signal is Signal.INSUFFICIENT_DATA
    assert len(evaluation.unresolved) == 2
    assert "not available" in evaluation.unresolved[0].explanation


# --- the cases the live portfolio produced -----------------------------------


def test_a_loss_making_stock_is_not_read_as_cheap() -> None:
    """MRVE3 collected at pe -3.59. A negative multiple is not a bargain."""
    snapshot = build_snapshot(pe=Decimal("-3.59"), roe=Decimal("-18.72"))

    evaluation = evaluate(build_stock(LynchCategory.STALWART), snapshot)

    assert evaluation.signal is Signal.NEEDS_REVIEW
    assert evaluation.checks[0].name == "Earnings"


@pytest.mark.parametrize("category", [LynchCategory.FAST_GROWER, LynchCategory.STALWART])
def test_every_earnings_ruleset_gates_on_profitability(category: LynchCategory) -> None:
    snapshot = build_snapshot(pe=Decimal("-2"), earnings_cagr_5y=Decimal("50"))

    assert evaluate(build_stock(category), snapshot).signal is Signal.NEEDS_REVIEW


def test_a_missing_indicator_never_becomes_a_red() -> None:
    """A free-tier gap and a bad number lead to different actions."""
    snapshot = build_snapshot(pe=Decimal("12"), roe=Decimal("18"))

    evaluation = evaluate(build_stock(LynchCategory.STALWART), snapshot)

    assert signals_by_name(evaluation)["Net debt / EBITDA"] is Signal.INSUFFICIENT_DATA
    assert evaluation.signal is Signal.GREEN
