from fastapi import APIRouter, Depends, Request

from ..config import Settings, get_settings
from ..deps import get_catalog, require_api_key
from ..errors import OVERLOAD_RESPONSES, ApiError
from ..schemas.bom import BomResponse
from ..schemas.catalog import Material
from ..schemas.nesting import NestingRequest, NestingResponse
from ..services.bom import compute_bom, compute_material_summary
from ..services.nesting import NestingTimeout, nest_cut_list, now, summarize

router = APIRouter(prefix="/v1", tags=["nesting"], dependencies=[Depends(require_api_key)])


@router.post("/nesting", response_model=NestingResponse, responses=OVERLOAD_RESPONSES)
def nesting(
    req: NestingRequest,
    request: Request,
    catalog: list[Material] = Depends(get_catalog),
    settings: Settings = Depends(get_settings),
):
    # Guard rails for CPU-heavy work: a concurrency cap (fail fast, never queue) and a cooperative deadline.
    slots = request.app.state.nesting_slots
    if not slots.acquire():
        raise ApiError(
            503, "busy", "Too many nesting requests in progress; retry shortly", headers={"Retry-After": "1"}
        )
    try:
        deadline = now() + settings.nesting_timeout_s
        rows = compute_bom(req.panels, catalog)
        try:
            results = nest_cut_list(
                rows,
                catalog,
                kerf_mm=req.options.kerf_mm,
                edge_banding_margin_mm=req.options.edge_banding_margin_mm,
                deadline=deadline,
            )
        except NestingTimeout:
            raise ApiError(503, "nesting_timeout", f"Nesting exceeded {settings.nesting_timeout_s:g}s") from None
        return NestingResponse(
            bom=BomResponse(rows=rows, material_summary=compute_material_summary(req.panels)),
            results=results,
            summary=summarize(results, catalog),
        )
    finally:
        slots.release()
