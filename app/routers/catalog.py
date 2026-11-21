import hashlib
import json

from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..deps import get_catalog
from ..ratelimit import rate_limit
from ..schemas.catalog import Material

router = APIRouter(prefix="/v1/catalog", tags=["catalog"], dependencies=[Depends(require_auth), Depends(rate_limit)])

# `no-cache` = the browser may store it but MUST revalidate (If-None-Match -> 304) every time:
# cheap for a ~1 kB catalog, and a catalog change shows up on the very next request.
CACHE_CONTROL = "no-cache"


def catalog_etag(body: list[dict]) -> str:
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f'"{digest[:32]}"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = [c.strip() for c in if_none_match.split(",")]
    return "*" in candidates or any(c.removeprefix("W/") == etag for c in candidates)


@router.get(
    "/materials",
    response_model=list[Material],
    responses={304: {"description": "Not modified (If-None-Match matched the ETag)"}},
)
def materials(request: Request, catalog: list[Material] = Depends(get_catalog)):
    body = jsonable_encoder(catalog, by_alias=True)
    headers = {"ETag": catalog_etag(body), "Cache-Control": CACHE_CONTROL}
    if _matches(request.headers.get("if-none-match"), headers["ETag"]):
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)
