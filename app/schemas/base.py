from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """camelCase on the wire (matches the JS modeller), snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
