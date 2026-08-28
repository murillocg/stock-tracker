"""COMPUTE step: the indicators we derive ourselves.

Every function here is pure — data in, data out, no I/O and no hidden state — and
every one returns `None` rather than raising when its inputs cannot support an
honest answer. Missing data is the normal case with free-tier APIs.
"""

from shared.indicators.arithmetic import as_percentage, as_ratio, safe_divide
from shared.indicators.changes import (
    DEFAULT_MAX_STALENESS,
    ChangeWindow,
    apply_changes,
    compute_changes,
    percentage_change,
    reference_snapshot,
)
from shared.indicators.growth import year_over_year
from shared.indicators.ratios import payout_ratio, peg, roic

__all__ = [
    "DEFAULT_MAX_STALENESS",
    "ChangeWindow",
    "apply_changes",
    "as_percentage",
    "as_ratio",
    "compute_changes",
    "payout_ratio",
    "peg",
    "percentage_change",
    "reference_snapshot",
    "roic",
    "safe_divide",
    "year_over_year",
]
