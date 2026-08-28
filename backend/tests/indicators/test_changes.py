"""Price changes over our own history, including gaps and closed markets."""

import datetime as dt
from decimal import Decimal

import pytest

from shared.indicators import (
    ChangeWindow,
    apply_changes,
    compute_changes,
    percentage_change,
    reference_snapshot,
)
from shared.models import DailySnapshot

AS_OF = dt.date(2026, 8, 28)


def build_snapshot(day: dt.date, price: str) -> DailySnapshot:
    return DailySnapshot(ticker="PETR4", date=day, price=Decimal(price))


def daily_history(days_back: int, price: str = "100") -> list[DailySnapshot]:
    """One snapshot per day, oldest first, as the repositories return them."""
    return [
        build_snapshot(AS_OF - dt.timedelta(days=offset), price)
        for offset in range(days_back, 0, -1)
    ]


def test_percentage_change_reports_a_fall_as_negative() -> None:
    assert percentage_change(previous=Decimal("40"), current=Decimal("38")) == Decimal("-5.00")


def test_percentage_change_reports_a_rise_as_positive() -> None:
    assert percentage_change(previous=Decimal("40"), current=Decimal("50")) == Decimal("25.00")


@pytest.mark.parametrize("previous", [Decimal("0"), Decimal("-10"), None])
def test_percentage_change_is_none_without_a_usable_base(previous: Decimal | None) -> None:
    assert percentage_change(previous=previous, current=Decimal("38")) is None


def test_the_reference_is_the_newest_snapshot_at_or_before_the_target() -> None:
    history = daily_history(days_back=30)

    found = reference_snapshot(history, AS_OF - dt.timedelta(days=7))

    assert found is not None
    assert found.date == dt.date(2026, 8, 21)


def test_a_closed_market_falls_back_to_the_previous_trading_day() -> None:
    """There is rarely a snapshot exactly N days back — weekends and holidays."""
    history = [
        build_snapshot(dt.date(2026, 8, 19), "100"),
        build_snapshot(dt.date(2026, 8, 24), "110"),
    ]

    found = reference_snapshot(history, dt.date(2026, 8, 21))

    assert found is not None
    assert found.date == dt.date(2026, 8, 19)


def test_a_reference_after_the_target_is_never_used() -> None:
    history = [build_snapshot(dt.date(2026, 8, 27), "100")]

    assert reference_snapshot(history, dt.date(2026, 8, 21)) is None


def test_a_stale_reference_is_rejected() -> None:
    """A month-old price must not be reported as last week's move."""
    history = [build_snapshot(dt.date(2026, 7, 1), "100")]

    assert reference_snapshot(history, AS_OF - dt.timedelta(days=7)) is None


def test_the_staleness_tolerance_is_tunable() -> None:
    history = [build_snapshot(dt.date(2026, 7, 1), "100")]

    found = reference_snapshot(
        history, AS_OF - dt.timedelta(days=7), max_staleness=dt.timedelta(days=90)
    )

    assert found is not None


def test_compute_changes_fills_every_window_it_can_cover() -> None:
    history = daily_history(days_back=400, price="100")

    changes = compute_changes(history, as_of=AS_OF, current_price=Decimal("125"))

    assert set(changes) == set(ChangeWindow)
    assert changes[ChangeWindow.ONE_YEAR] == Decimal("25.00")


def test_short_history_omits_the_windows_it_cannot_answer() -> None:
    """Two months in, we can speak to 1w and 1m and must say nothing about 1y."""
    changes = compute_changes(daily_history(days_back=60), as_of=AS_OF, current_price=Decimal("90"))

    assert set(changes) == {ChangeWindow.ONE_WEEK, ChangeWindow.ONE_MONTH}
    assert ChangeWindow.ONE_YEAR not in changes


def test_no_history_yields_no_changes() -> None:
    assert compute_changes([], as_of=AS_OF, current_price=Decimal("38")) == {}


def test_each_window_uses_its_own_reference_price() -> None:
    history = [
        build_snapshot(AS_OF - dt.timedelta(days=7), "100"),
        build_snapshot(AS_OF - dt.timedelta(days=30), "80"),
    ]

    changes = compute_changes(history, as_of=AS_OF, current_price=Decimal("120"))

    assert changes[ChangeWindow.ONE_WEEK] == Decimal("20.00")
    assert changes[ChangeWindow.ONE_MONTH] == Decimal("50.00")


def test_a_twenty_percent_drop_is_reported_as_negative() -> None:
    """This is the number the Phase 2 SES alert will fire on."""
    history = daily_history(days_back=40, price="50")

    changes = compute_changes(history, as_of=AS_OF, current_price=Decimal("40"))

    assert changes[ChangeWindow.ONE_MONTH] == Decimal("-20.00")


def test_windows_map_onto_the_snapshot_fields() -> None:
    assert [window.field_name for window in ChangeWindow] == [
        "change_1w",
        "change_1m",
        "change_6m",
        "change_1y",
    ]


def test_apply_changes_returns_a_new_snapshot(snapshot: DailySnapshot) -> None:
    updated = apply_changes(snapshot, {ChangeWindow.ONE_YEAR: Decimal("12.50")})

    assert updated.change_1y == Decimal("12.50")
    assert updated.price == snapshot.price


def test_apply_changes_leaves_the_original_untouched(snapshot: DailySnapshot) -> None:
    """The model is frozen, so `model_copy` is the only way to "modify" it."""
    apply_changes(snapshot, {ChangeWindow.ONE_YEAR: Decimal("12.50")})

    assert snapshot.change_1y is None


def test_applying_nothing_changes_nothing(snapshot: DailySnapshot) -> None:
    assert apply_changes(snapshot, {}) == snapshot


def test_applied_changes_survive_the_dynamodb_item_shape(snapshot: DailySnapshot) -> None:
    updated = apply_changes(snapshot, {ChangeWindow.ONE_WEEK: Decimal("-3.10")})

    item = updated.model_dump(by_alias=True, exclude_none=True)

    assert item["change1w"] == Decimal("-3.10")
