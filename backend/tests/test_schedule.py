"""Reading the collector's own cron to say when it next runs."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from shared.schedule import DEFAULT_SCHEDULE, next_run

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def at(year: int, month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=SAO_PAULO)


def test_later_the_same_day() -> None:
    found = next_run(DEFAULT_SCHEDULE, "America/Sao_Paulo", at(2026, 9, 1, 9))
    assert found == at(2026, 9, 1, 20)


def test_after_today_s_run_it_rolls_to_tomorrow() -> None:
    found = next_run(DEFAULT_SCHEDULE, "America/Sao_Paulo", at(2026, 9, 1, 20, 1))
    assert found == at(2026, 9, 2, 20)


def test_the_boundary_belongs_to_the_next_one() -> None:
    """Exactly 20:00 means this run is happening now, so the *next* is tomorrow."""
    found = next_run(DEFAULT_SCHEDULE, "America/Sao_Paulo", at(2026, 9, 1, 20, 0))
    assert found == at(2026, 9, 2, 20)


def test_friday_evening_skips_the_weekend() -> None:
    """MON-FRI, because B3 is shut and a weekend run would spend quota re-storing
    Friday's close."""
    friday = at(2026, 9, 4, 21)
    assert friday.weekday() == 4
    assert next_run(DEFAULT_SCHEDULE, "America/Sao_Paulo", friday) == at(2026, 9, 7, 20)


def test_saturday_waits_for_monday() -> None:
    assert next_run(DEFAULT_SCHEDULE, "America/Sao_Paulo", at(2026, 9, 5, 10)) == at(2026, 9, 7, 20)


def test_it_answers_in_the_schedule_s_timezone_not_the_caller_s() -> None:
    """The caller passes UTC — Lambda's clock — and must still get 20:00 local."""
    found = next_run(
        DEFAULT_SCHEDULE, "America/Sao_Paulo", dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC)
    )
    assert found is not None
    assert (found.hour, found.minute) == (20, 0)


def test_a_daily_schedule_does_not_skip_weekends() -> None:
    assert next_run("cron(30 6 * * * *)", "America/Sao_Paulo", at(2026, 9, 5, 10)) == at(
        2026, 9, 6, 6, 30
    )


def test_a_comma_separated_list_is_honoured() -> None:
    monday = at(2026, 9, 7, 21)
    assert monday.weekday() == 0
    assert next_run("cron(0 20 ? * MON,WED *)", "America/Sao_Paulo", monday) == at(2026, 9, 9, 20)


@pytest.mark.parametrize(
    "expression",
    [
        "cron(0/15 20 ? * MON-FRI *)",  # a step we do not model
        "cron(0 20 ? 3 MON-FRI *)",  # restricted to March
        "cron(0 20 ? * NOTADAY *)",
        "rate(1 day)",
        "",
    ],
)
def test_anything_it_cannot_read_is_silence_not_a_guess(expression: str) -> None:
    """A wrong time is worse than no time: the line exists to tell you whether a
    refresh is imminent, and a confident lie defeats it."""
    assert next_run(expression, "America/Sao_Paulo", at(2026, 9, 1, 9)) is None


def test_an_unknown_timezone_is_silence_too() -> None:
    assert next_run(DEFAULT_SCHEDULE, "Mars/Olympus_Mons", at(2026, 9, 1, 9)) is None
