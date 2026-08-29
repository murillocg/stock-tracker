"""The vocabulary of a verdict: what the traffic light can say, and why."""

from decimal import Decimal
from enum import StrEnum

from shared.models import CamelModel, LynchCategory
from shared.models.types import Ticker


class Signal(StrEnum):
    """One traffic-light state.

    Note there are five, not three. The two extra ones are the honest answers,
    and leaving them out is what makes an app pretend to know things.
    """

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"

    NEEDS_REVIEW = "NEEDS_REVIEW"
    """The numbers are here but the call is yours.

    CYCLICAL and TURNAROUND land here by design: CLAUDE.md is explicit that the
    app flags and does not decide for them.
    """

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    """We cannot answer. Not a failure — a free-tier gap, or a stock too young.

    Distinct from RED on purpose: "I don't know" and "this looks bad" lead to
    completely different actions.
    """

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """The number exists but means nothing for this company.

    Net debt / EBITDA on a bank, for instance. Deliberately not the same as
    INSUFFICIENT_DATA: there is no missing data to go and find, and no amount of
    paying for a better provider would change the answer.
    """


# Worst-wins ordering when several checks disagree.
#
# NEEDS_REVIEW sits above YELLOW: "this needs your judgement" demands attention
# in a way "mixed" does not. RED still outranks it, because a clear red flag is
# more actionable than a request to go and look.
#
# INSUFFICIENT_DATA and NOT_APPLICABLE are deliberately absent from the scale.
# Neither is a degree of badness — one is the absence of an answer, the other the
# absence of a question — so they never drag a verdict down, and INSUFFICIENT_DATA
# only survives when nothing else was decidable.
_SEVERITY: dict[Signal, int] = {
    Signal.GREEN: 0,
    Signal.YELLOW: 1,
    Signal.NEEDS_REVIEW: 2,
    Signal.RED: 3,
}


class Check(CamelModel):
    """One indicator weighed against this category's limit."""

    name: str
    value: Decimal | None
    signal: Signal
    explanation: str
    """Written for a human reading the UI, not for a log."""


class Evaluation(CamelModel):
    """The verdict for one stock, plus every check that produced it."""

    ticker: Ticker
    category: LynchCategory | None
    signal: Signal
    checks: list[Check]

    @property
    def unresolved(self) -> list[Check]:
        """Checks we could not answer. Usually a missing free-tier field."""
        return [check for check in self.checks if check.signal is Signal.INSUFFICIENT_DATA]


def worst(signals: list[Signal]) -> Signal:
    """Combine several checks into one light: the worst decidable one wins.

    A single RED among greens means look at this. Averaging would let one bad
    metric hide behind three good ones, which is exactly the failure mode a
    traffic light exists to prevent.

    Returns INSUFFICIENT_DATA when nothing was decidable, so an all-gaps stock
    never appears green.
    """
    decidable = [signal for signal in signals if signal in _SEVERITY]
    if not decidable:
        return Signal.INSUFFICIENT_DATA
    return max(decidable, key=lambda signal: _SEVERITY[signal])
