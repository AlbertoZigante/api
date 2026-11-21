from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import validate_settings
from .catalog.loader import load_materials
from .concurrency import SlotLimiter
from .config import get_settings
from .errors import ERROR_RESPONSES, install_error_handlers
from .logs import configure_logging
from .middleware import AccessLogMiddleware, BodySizeLimitMiddleware, RulesVersionMiddleware
from .nesting_runner import NestingRunner
from .routers import bom, catalog, engine, health, meta, nesting

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_settings(get_settings())  # unsafe / missing auth configuration stops the process here
    app.state.catalog = load_materials()
    settings = get_settings()
    app.state.nesting_slots = SlotLimiter(settings.max_concurrent_nestings)
    app.state.nesting_runner = NestingRunner(settings.nesting_executor, settings.max_concurrent_nestings,
                                             settings.nesting_worker_nice)
    await app.state.nesting_runner.warm_up()
    try:
        yield
    finally:
        app.state.nesting_runner.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    docs_url, redoc_url, openapi_url = ("/docs", "/redoc", "/openapi.json") if settings.docs_on else (None, None, None)
    app = FastAPI(title="DIY Furnitures API", version=API_VERSION, lifespan=lifespan, responses=ERROR_RESPONSES,
                  docs_url=docs_url, redoc_url=redoc_url, openapi_url=openapi_url)
    install_error_handlers(app)
    # Starlette: the LAST added middleware is the outermost (CORS must see every response).
    app.add_middleware(RulesVersionMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization", "If-None-Match", "X-Request-ID"],
        expose_headers=["X-Rules-Version", "ETag", "Retry-After", "X-Request-ID"],
    )
    app.add_middleware(AccessLogMiddleware)  # outermost: logs every response, CORS preflights included
    for r in (health.router, meta.router, catalog.router, bom.router, nesting.router, engine.router):
        app.include_router(r)
    return app


app = create_app()
