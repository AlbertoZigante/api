from fastapi import Depends, Header, Request

from .config import Settings, get_settings
from .errors import ApiError
from .schemas.catalog import Material


def get_catalog(request: Request) -> list[Material]:
    return request.app.state.catalog


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    keys = settings.api_key_set
    if keys and x_api_key not in keys:
        raise ApiError(401, "invalid_api_key", "Invalid or missing API key")
