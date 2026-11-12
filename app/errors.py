"""Locale-neutral errors.

Every error body carries a stable machine `code` next to the English `detail`.
Clients (site, modeller) translate by `code`; the API itself never localises.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        # `detail` keeps FastAPI's default shape (list of problems).
        return JSONResponse(status_code=422, content={"detail": jsonable(exc.errors()), "code": "validation_error"})

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc), "code": "invalid_input"})


def jsonable(errors):
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(errors)
