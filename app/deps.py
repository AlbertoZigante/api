from fastapi import Depends, Header, HTTPException, Request

from .config import Settings, get_settings
from .schemas.catalog import Material


def get_catalog(request: Request) -> list[Material]:
    return request.app.state.catalog


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    keys = settings.api_key_set
    if keys and x_api_key not in keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
