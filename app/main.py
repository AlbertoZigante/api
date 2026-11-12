from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .catalog.loader import load_materials
from .config import get_settings
from .errors import ERROR_RESPONSES, install_error_handlers
from .middleware import BodySizeLimitMiddleware, RulesVersionMiddleware
from .routers import bom, catalog, engine, health, meta, nesting

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.catalog = load_materials()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DIY Furnitures API", version=API_VERSION, lifespan=lifespan, responses=ERROR_RESPONSES)
    install_error_handlers(app)
    # Starlette: the LAST added middleware is the outermost (CORS must see every response).
    app.add_middleware(RulesVersionMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "If-None-Match"],
        expose_headers=["X-Rules-Version", "ETag"],
    )
    for r in (health.router, meta.router, catalog.router, bom.router, nesting.router, engine.router):
        app.include_router(r)
    return app


app = create_app()
