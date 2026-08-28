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
    alert_sender: str
    alert_recipient: str
    aws_region: str = "us-east-1"
    provider_delay_seconds: float = 1.0
    """Pause between upstream calls. Collection is sequential to respect free-tier
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
            brapi_token=required("BRAPI_TOKEN"),
            alert_sender=required("ALERT_SENDER"),
            alert_recipient=required("ALERT_RECIPIENT"),
            aws_region=source.get("AWS_REGION", "us-east-1"),
            provider_delay_seconds=float(source.get("PROVIDER_DELAY_SECONDS", "1.0")),
        )
