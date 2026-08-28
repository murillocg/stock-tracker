"""Per-stock alert configuration, stored denormalised on the Stock item."""

from decimal import Decimal

from pydantic import Field

from shared.models.base import CamelModel


class AlertRule(CamelModel):
    """One rule. Its meaning depends on the `AlertType` it is keyed by.

    - `PRICE_DROP`  -> `threshold` is a percentage (20 means "fell more than 20%").
    - `ENTRY_POINT` -> `threshold` is an absolute price in the stock's currency.
    """

    enabled: bool = True
    threshold: Decimal = Field(gt=0)
    window_days: int | None = Field(default=None, gt=0)
    """Look-back window for PRICE_DROP. `None` for point-in-time rules."""
