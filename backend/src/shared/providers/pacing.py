"""Keeping our call rate inside what the free tiers allow.

Lives in `shared` rather than in the collector because the seeding script needs
the same discipline: Alpha Vantage rejects a second request in the same second
whatever is making it, and a rule enforced in only one of two callers is not a
rule.
"""

from collections.abc import Callable


class Pacer:
    """Spaces out upstream calls. One per run, shared by every provider.

    The delay used to sit between *tickers*, which was wrong the moment a single
    provider served both capabilities: brapi and bolsai are separate services, so
    a quote and a fundamentals call could fire together harmlessly, but Alpha
    Vantage answers both and rejects anything faster than one request a second.

    Pacing every call rather than every ticker is correct for all of them, and
    costs one extra second per stock on the Brazilian path.
    """

    def __init__(self, delay_seconds: float, sleep: Callable[[float], None]) -> None:
        self._delay = delay_seconds
        self._sleep = sleep
        self._called = False

    def wait(self) -> None:
        """Pause before every call except the first of the run."""
        if self._called:
            self._sleep(self._delay)
        self._called = True
