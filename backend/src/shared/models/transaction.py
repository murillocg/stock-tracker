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

from pydantic import Field, field_serializer

from shared.models.base import CamelModel
from shared.models.enums import Currency
from shared.models.types import Ticker


class TransactionType(StrEnum):
    """What the row records.

    Only trades for now. SPLIT and BONUS belong here too — Brazilian companies
    split and issue bonificações often, and both change quantity and average
    price without a trade — but they are not modelled yet. Adding them later is
    an enum member and a branch in the fold, not a migration.
    """

    BUY = "BUY"
    SELL = "SELL"


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

    unit_price: Decimal = Field(gt=0)
    currency: Currency

    fees: Decimal | None = None
    """Brokerage and exchange fees. Unused today, and deliberately present:
    Brazilian cost basis includes them, so Phase 4 will need it and adding the
    field now costs nothing."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Distinguishes trades made on the same day in the same ticker."""

    note: str | None = None

    @property
    def sort_key(self) -> str:
        """The DynamoDB sort key. ISO date first, so a range query on a period
        works lexicographically."""
        return f"{self.date.isoformat()}#{self.id}"

    @field_serializer("date")
    def _serialise_date(self, value: dt.date) -> str:
        return value.isoformat()
