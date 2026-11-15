"""One error envelope for the whole API: {"code": <stable machine code>, "detail": ...}.

The modeller's client reads `code` (e.g. 'invalid_api_key') and translates it;
`detail` is for humans/logs and is never echoed back with client input.
"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .schemas.base import CamelModel


class ErrorBody(CamelModel):
    """Error envelope documented in the OpenAPI contract (what clients actually receive)."""

    code: str
    detail: Any


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorBody, "description": "code=invalid_api_key"},
    413: {"model": ErrorBody, "description": "code=payload_too_large"},
    422: {"model": ErrorBody, "description": "code=validation_error"},
}

# Documented on the endpoints that can be overloaded / expensive (nesting).
OVERLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorBody, "description": "code=busy (retry shortly, see Retry-After) | code=nesting_timeout"},
}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, detail: str = "", headers: dict[str, str] | None = None) -> None:
        super().__init__(detail or code)
        self.status_code = status_code
        self.code = code
        self.detail = detail or code
        self.headers = headers


def error_body(code: str, detail: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _clean_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Drop `input`/`ctx`: they can echo large or hostile client data.
    return [
        {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in errors[:50]
    ]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.detail), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = _clean_validation_errors(jsonable_encoder(exc.errors()))
        return JSONResponse(error_body("validation_error", detail), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, exc.detail), status_code=exc.status_code, headers=exc.headers)
