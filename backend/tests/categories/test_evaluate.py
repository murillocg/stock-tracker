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


# --- financials --------------------------------------------------------------


def test_leverage_is_not_applicable_to_a_bank() -> None:
    """BBAS3 collected at 12.73 and BPAC11 at -6. Both are arithmetic noise."""
    stock = build_stock(LynchCategory.STALWART, uses_operating_leverage=False)
    snapshot = build_snapshot(
        pe=Decimal("9.38"), roe=Decimal("18"), net_debt_to_ebitda=Decimal("12.73")
    )

    evaluation = evaluate(stock, snapshot)

    assert signals_by_name(evaluation)["Net debt / EBITDA"] is Signal.NOT_APPLICABLE
    assert evaluation.signal is Signal.GREEN


def test_not_applicable_is_not_the_same_as_missing() -> None:
    """One says "go and find it", the other says "there is nothing to find"."""
    stock = build_stock(LynchCategory.STALWART, uses_operating_leverage=False)
    snapshot = build_snapshot(
        pe=Decimal("9"), roe=Decimal("18"), net_debt_to_ebitda=Decimal("12.73")
    )

    check = next(c for c in evaluate(stock, snapshot).checks if c.name == "Net debt / EBITDA")

    assert check.signal is Signal.NOT_APPLICABLE
    assert check.value == Decimal("12.73")
    assert evaluate(stock, snapshot).unresolved == []


def test_leverage_still_counts_for_an_ordinary_company() -> None:
    stock = build_stock(LynchCategory.STALWART, uses_operating_leverage=True)
    snapshot = build_snapshot(pe=Decimal("9"), roe=Decimal("18"), net_debt_to_ebitda=Decimal("4.5"))

    assert evaluate(stock, snapshot).signal is Signal.RED


def test_the_flag_defaults_to_applicable() -> None:
    """Most companies do have operating leverage; financials are the exception."""
    assert build_stock(LynchCategory.STALWART).uses_operating_leverage is True


# --- manual dividend figures -------------------------------------------------


def test_slow_grower_falls_back_to_the_manual_figures() -> None:
    """No free API supplies these, so BBSE3's real numbers come from you.

    96% payout on an 82% ROE is an asset-light broker distributing what it cannot
    usefully reinvest — a thin cushion worth knowing about, not a failure.
    """
    stock = build_stock(
        LynchCategory.SLOW_GROWER,
        manual_dividend_yield=Decimal("5.09"),
        manual_payout_ratio=Decimal("96.19"),
        manual_updated_on=dt.date(2026, 8, 29),
    )

    evaluation = evaluate(stock, build_snapshot())
    signals = signals_by_name(evaluation)

    assert signals["Dividend yield"] is Signal.GREEN
    assert signals["Payout ratio"] is Signal.YELLOW
    assert evaluation.signal is Signal.YELLOW


def test_a_well_covered_payout_is_green() -> None:
    """CPLE3: 7.29% yield on a 73% payout, comfortably covered."""
    stock = build_stock(
        LynchCategory.SLOW_GROWER,
        manual_dividend_yield=Decimal("7.29"),
        manual_payout_ratio=Decimal("73.21"),
    )

    assert evaluate(stock, build_snapshot()).signal is Signal.GREEN


def test_paying_out_more_than_it_earns_is_the_real_failure() -> None:
    """No business model sustains this: it comes from debt, reserves or sales."""
    stock = build_stock(
        LynchCategory.SLOW_GROWER,
        manual_dividend_yield=Decimal("8"),
        manual_payout_ratio=Decimal("124"),
    )

    evaluation = evaluate(stock, build_snapshot())

    assert signals_by_name(evaluation)["Payout ratio"] is Signal.RED
    assert "more than it earns" in evaluation.checks[1].explanation


def test_every_payout_verdict_explains_itself() -> None:
    """ "Why is this red?" is the only question the traffic light exists to answer."""
    for payout in (Decimal("5"), Decimal("50"), Decimal("90"), Decimal("150")):
        stock = build_stock(LynchCategory.SLOW_GROWER, manual_payout_ratio=payout)
        explanation = evaluate(stock, build_snapshot()).checks[1].explanation

        assert str(payout) in explanation


def test_a_provider_value_beats_the_manual_one() -> None:
    """The manual fields fill a gap; they must not override live data."""
    stock = build_stock(LynchCategory.SLOW_GROWER, manual_dividend_yield=Decimal("1"))
    snapshot = build_snapshot(dividend_yield=Decimal("8"), payout_ratio=Decimal("40"))

    signals = signals_by_name(evaluate(stock, snapshot))

    assert signals["Dividend yield"] is Signal.GREEN


def test_the_manual_date_is_surfaced_so_staleness_is_visible() -> None:
    """Hand-maintained numbers go stale silently. Showing the date is the warning."""
    stock = build_stock(
        LynchCategory.SLOW_GROWER,
        manual_dividend_yield=Decimal("5.09"),
        manual_payout_ratio=Decimal("40"),
        manual_updated_on=dt.date(2026, 8, 29),
    )

    check = evaluate(stock, build_snapshot()).checks[0]

    assert "2026-08-29" in check.explanation


def test_without_manual_figures_slow_grower_still_says_it_does_not_know() -> None:
    evaluation = evaluate(build_stock(LynchCategory.SLOW_GROWER), build_snapshot())

    assert evaluation.signal is Signal.INSUFFICIENT_DATA


def test_a_zero_payout_fails_the_slow_grower_thesis() -> None:
    """AXIA3 reports 0. The monotonic band would have scored that GREEN.

    "Maximally sustainable" is technically true and useless: a stock held for
    income that pays none belongs in a different category.
    """
    stock = build_stock(
        LynchCategory.SLOW_GROWER,
        manual_payout_ratio=Decimal("0"),
        manual_dividend_yield=Decimal("0"),
    )

    signals = signals_by_name(evaluate(stock, build_snapshot()))

    assert signals["Payout ratio"] is Signal.RED
    assert signals["Dividend yield"] is Signal.RED


def test_a_healthy_payout_is_still_green() -> None:
    stock = build_stock(
        LynchCategory.SLOW_GROWER,
        manual_payout_ratio=Decimal("45"),
        manual_dividend_yield=Decimal("6"),
    )

    assert evaluate(stock, build_snapshot()).signal is Signal.GREEN


def test_a_missing_pe_is_not_reported_as_a_loss() -> None:
    """SPCX has no P/E because its provider supplies none. Telling the user the
    company is loss-making on that basis asserts a fact we do not have."""
    snapshot = build_snapshot(pb=Decimal("14.6"), roe=Decimal("0"))

    evaluation = evaluate(build_stock(LynchCategory.FAST_GROWER), snapshot)

    assert evaluation.signal is Signal.INSUFFICIENT_DATA
    assert "do not know" in evaluation.checks[0].explanation


def test_a_negative_pe_is_still_reported_as_a_loss() -> None:
    """MRVE3 at -3.59 — a real loss, and a different answer from 'unknown'."""
    evaluation = evaluate(build_stock(LynchCategory.STALWART), build_snapshot(pe=Decimal("-3.59")))

    assert evaluation.signal is Signal.NEEDS_REVIEW
    assert "loss-making" in evaluation.checks[0].explanation


# --- explanations ------------------------------------------------------------


def test_every_verdict_quotes_the_threshold_it_was_judged_by() -> None:
    """ "Return on equity." was a definition. A traffic light owes you a reason."""
    snapshot = build_snapshot(pe=Decimal("9.38"), roe=Decimal("7.15"))

    roe = next(
        c for c in evaluate(build_stock(LynchCategory.STALWART), snapshot).checks if c.name == "ROE"
    )

    assert "7.15%" in roe.explanation
    assert "15%" in roe.explanation
    assert "below" in roe.explanation


def test_a_green_verdict_explains_itself_too() -> None:
    snapshot = build_snapshot(pe=Decimal("9.38"), roe=Decimal("22"))

    roe = next(
        c for c in evaluate(build_stock(LynchCategory.STALWART), snapshot).checks if c.name == "ROE"
    )

    assert "22%" in roe.explanation
    assert "at or above" in roe.explanation


def test_the_threshold_text_follows_the_constant() -> None:
    """Generated from the band, so a constant and its prose cannot drift apart."""
    from shared.categories.rules import STALWART_ROE_BAND

    snapshot = build_snapshot(pe=Decimal("10"), roe=Decimal("1"))
    roe = next(
        c for c in evaluate(build_stock(LynchCategory.STALWART), snapshot).checks if c.name == "ROE"
    )

    assert f"{STALWART_ROE_BAND.yellow}%" in roe.explanation


def test_leverage_is_expressed_in_multiples() -> None:
    snapshot = build_snapshot(
        pe=Decimal("10"), roe=Decimal("20"), net_debt_to_ebitda=Decimal("4.5")
    )

    leverage = next(
        c
        for c in evaluate(build_stock(LynchCategory.STALWART), snapshot).checks
        if c.name == "Net debt / EBITDA"
    )

    assert "4.5x" in leverage.explanation
    assert "3x" in leverage.explanation
