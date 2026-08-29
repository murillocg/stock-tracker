"""The `Transactions` table: one row per trade, never edited.

An append-only ledger rather than a mutable position. The position is *derived*
by folding the ledger, which is what makes the average price reproducible and
gives Phase 4's tax reporting something to work from — a current position alone
cannot tell you what a sale gained.
"""

import datetime as dt
import uuid
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_serializer, model_validator

from shared.models.base import CamelModel
from shared.models.enums import Currency
from shared.models.types import Ticker


class TransactionType(StrEnum):
    """What the row records."""

    BUY = "BUY"
    SELL = "SELL"

    BONUS = "BONUS"
    """Shares received without paying for them.

    Covers a desdobramento (split), a bonificação, and the share side of a
    conversion — mechanically the same event. A 2:1 split on 200 shares is 200
    free shares: quantity doubles while the amount invested stays put, so the
    average halves by itself. Modelling it as a zero-price receipt means the fold
    needs no special arithmetic for it.

    BBAS3 split 2-for-1 in 2024; ITSA4 issues bonificações regularly.
    """

    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    """Shares moving between custodians, carrying their cost with them.

    Not a trade: nothing is bought or sold, no gain is realised, and the total
    holding does not change — only which broker holds it. They matter because
    per-broker positions are what each broker's app shows and what goes in the
    fiscal declaration, and B3's Negociação export has no record of them (they
    are in Movimentação instead).

    Without these, Inter still appears to hold 150 BBAS3 and 80 BPAC11 that moved
    to BTG in July 2020.
    """


_PRICELESS = frozenset({TransactionType.BONUS, TransactionType.TRANSFER_OUT})
"""Types with no price of their own: free shares, and shares leaving at cost."""


class Transaction(CamelModel):
    """One trade. PK=`ticker`, SK=`<date>#<id>`.

    The sort key pairs the date with an id because several trades in one ticker
    can share a day, and a date alone would silently overwrite them.
    """

    ticker: Ticker
    date: dt.date
    type: TransactionType
    quantity: Decimal = Field(gt=0)
    """Always positive. Direction is carried by `type`, not by the sign — a
    negative quantity would make every guard in the fold conditional on which
    convention the row happened to use."""

    unit_price: Decimal = Field(ge=0)
    """Zero only where no price exists: free shares, or shares leaving at cost.

    A TRANSFER_IN still needs one — it is the average the sending broker held,
    and demanding it here stops a transfer from silently re-basing the cost to
    nothing.
    """

    currency: Currency

    broker: str | None = None
    """Which custodian executed it, from B3's `Instituição` column.

    Recorded but never used to split a position. Brazilian IRPF computes average
    cost per *security* aggregated across custodians — holding PRIO3 at two
    brokers is one position with one average, not two. Keeping the broker on each
    row means a per-broker breakdown is always derivable without making it the
    unit of accounting.
    """

    fees: Decimal | None = None
    """Brokerage and exchange fees. Unused today, and deliberately present:
    Brazilian cost basis includes them, so Phase 4 will need it and adding the
    field now costs nothing."""

    sequence: int = 0
    """Order within the day, taken from the source file's own row order.

    Without it the fold is non-deterministic: several trades can share a date,
    and their order changes the running average. Sorting by a random id gave
    VALE3 an average of 68.06 on some runs and 68.29 on others, from identical
    input — a difference that would have been invisible until the numbers were
    compared across two runs.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Distinguishes trades made on the same day in the same ticker.

    Importers should derive this from the row's content rather than take the
    random default, so that re-running an import overwrites rather than
    duplicating — the sort key is `<date>#<id>`, and a fresh id every run means a
    fresh row every run.
    """

    note: str | None = None

    @model_validator(mode="after")
    def _price_matches_type(self) -> "Transaction":
        if self.type in _PRICELESS:
            return self
        if self.unit_price <= 0:
            raise ValueError(f"a {self.type.value} needs a positive price, got {self.unit_price}")
        return self

    @property
    def sort_key(self) -> str:
        """The DynamoDB sort key. ISO date first, so a range query on a period
        works lexicographically."""
        return f"{self.date.isoformat()}#{self.id}"

    @field_serializer("date")
    def _serialise_date(self, value: dt.date) -> str:
        return value.isoformat()
