"""Common Pydantic configuration for every model that crosses a boundary."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for models that are persisted to DynamoDB or serialised to JSON.

    Inside Python we write `net_debt_to_ebitda`; on the wire and in DynamoDB the
    attribute is `netDebtToEbitda`. `alias_generator` derives that automatically
    instead of us repeating an `alias=` on every field.

    - `populate_by_name=True` lets us build models in tests with the Python name
      (`DailySnapshot(net_debt_to_ebitda=...)`) as well as with the alias.
    - `extra="ignore"` means a provider adding a new JSON field never breaks us.
    - `frozen=True` makes instances immutable (and hashable). Models are values;
      transformations return new instances.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
        use_enum_values=False,
    )
