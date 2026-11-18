from fastapi import Request

from .schemas.catalog import Material


def get_catalog(request: Request) -> list[Material]:
    return request.app.state.catalog
