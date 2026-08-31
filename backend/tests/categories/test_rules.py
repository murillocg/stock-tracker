"""The thresholds themselves, independent of how a stock is evaluated."""

from shared.categories.rules import (
    BRAZILIAN_PE_BAND,
    INTERNATIONAL_PE_BAND,
    stalwart_pe_band,
)


def test_a_bdr_is_judged_against_the_country_its_earnings_come_from() -> None:
    """MSFT34 is a B3-listed receipt for Microsoft. Judged by its listing it
    scored RED at a P/E of 28.04 while MSFT scored YELLOW at 28.64 — the same
    company, opposite verdicts, decided by which exchange the paper trades on."""
    assert stalwart_pe_band(is_foreign=True) == INTERNATIONAL_PE_BAND
    assert stalwart_pe_band(is_foreign=False) == BRAZILIAN_PE_BAND


def test_the_brazilian_band_is_the_stricter_one() -> None:
    """Not a preference: a P/E is roughly 1 / (discount rate - growth), and the
    Selic sets a far higher discount rate than US Treasuries do."""
    assert BRAZILIAN_PE_BAND.green < INTERNATIONAL_PE_BAND.green
    assert BRAZILIAN_PE_BAND.yellow < INTERNATIONAL_PE_BAND.yellow
