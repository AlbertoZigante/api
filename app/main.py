from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .catalog.loader import load_materials
from .config import get_settings
from .routers import bom, catalog, health, nesting


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.catalog = load_materials()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DIY Furnitures API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )
    for r in (health.router, catalog.router, bom.router, nesting.router):
        app.include_router(r)
    return app


app = create_app()
