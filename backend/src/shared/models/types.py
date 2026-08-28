"""Reusable constrained types, declared once and applied with `Annotated`."""

from typing import Annotated

from pydantic import BeforeValidator, Field


def _normalise_ticker(value: str) -> str:
    return value.strip().upper()


Ticker = Annotated[
    str,
    BeforeValidator(_normalise_ticker),
    Field(min_length=1, max_length=16, pattern=r"^[A-Z0-9.\-]+$"),
]
"""A ticker symbol, always stored upper-cased: `petr4` -> `PETR4`.

It is the partition key of both tables, so normalising here — at the boundary —
is what stops `PETR4` and `petr4` from becoming two different rows.
"""

Quarter = Annotated[str, Field(pattern=r"^\d{4}Q[1-4]$")]
"""Fiscal quarter the fundamentals refer to, e.g. `2026Q2`."""
