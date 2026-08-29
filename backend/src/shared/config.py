"""Environment-backed configuration, read once at Lambda cold start."""

import os
from collections.abc import Mapping
from dataclasses import dataclass


class MissingConfigError(RuntimeError):
    """A required environment variable is absent. Fail loudly at cold start."""


@dataclass(frozen=True, slots=True)
class Config:
    """Everything the Lambdas need from the outside world.

    A plain frozen dataclass, not Pydantic: this never crosses a boundary, it is
    only read. Pydantic is reserved for data we do not control.
    """

    stocks_table: str
    snapshots_table: str
    brapi_token: str
    bolsai_api_key: str
    alpha_vantage_api_key: str
    alert_sender: str
    alert_recipient: str
    transactions_table: str = "stock-tracker-Transactions"
    """Defaulted rather than required: the collector never touches the ledger,
    so demanding it would fail a Lambda that has no use for it."""

    aws_region: str = "us-east-1"
    market_timezone: str = "America/Sao_Paulo"
    """Timezone that decides which trading day a run belongs to.

    Lambda's clock is UTC, and the collector runs after the B3 close — 20:00 in
    São Paulo is 23:00 UTC, so `date.today()` would stamp every snapshot with
    *tomorrow*. The snapshot date is the sort key of the whole time series, so
    that is not cosmetic.
    """
    provider_delay_seconds: float = 1.5
    """Pause before every upstream call. Collection is sequential to respect free-tier
    rate limits — see CLAUDE.md, "no parallelism"."""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """Build from the process environment, or from an injected mapping in tests."""
        source = os.environ if env is None else env

        def required(key: str) -> str:
            value = source.get(key)
            if not value:
                raise MissingConfigError(f"Missing required environment variable: {key}")
            return value

        return cls(
            stocks_table=required("STOCKS_TABLE"),
            snapshots_table=required("SNAPSHOTS_TABLE"),
            transactions_table=source.get("TRANSACTIONS_TABLE", "stock-tracker-Transactions"),
            brapi_token=required("BRAPI_TOKEN"),
            bolsai_api_key=required("BOLSAI_API_KEY"),
            alpha_vantage_api_key=required("ALPHA_VANTAGE_API_KEY"),
            alert_sender=required("ALERT_SENDER"),
            alert_recipient=required("ALERT_RECIPIENT"),
            aws_region=source.get("AWS_REGION", "us-east-1"),
            market_timezone=source.get("MARKET_TIMEZONE", "America/Sao_Paulo"),
            provider_delay_seconds=float(source.get("PROVIDER_DELAY_SECONDS", "1.5")),
        )
