"""Peter Lynch rulesets: judge each stock by the standards of its own category.

The limits are PER category, never global. A P/E of 32 is alarming for a
STALWART and irrelevant for a CYCLICAL near the bottom of its cycle, so there is
no single set of thresholds that could be correct for both.

Pure functions throughout: a stock and a snapshot in, a verdict out, no I/O.
"""

from shared.categories.evaluate import HUMAN_JUDGEMENT, evaluate
from shared.categories.rules import Band, band_signal
from shared.categories.signals import Check, Evaluation, Signal, worst

__all__ = [
    "HUMAN_JUDGEMENT",
    "Band",
    "Check",
    "Evaluation",
    "Signal",
    "band_signal",
    "evaluate",
    "worst",
]
