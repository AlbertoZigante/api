from fastapi import APIRouter, Depends

from ..deps import get_catalog, require_api_key
from ..schemas.bom import BomResponse
from ..schemas.catalog import Material
from ..schemas.nesting import NestingRequest, NestingResponse
from ..services.bom import compute_bom, compute_material_summary
from ..services.nesting import nest_cut_list, summarize

router = APIRouter(prefix="/v1", tags=["nesting"], dependencies=[Depends(require_api_key)])


@router.post("/nesting", response_model=NestingResponse)
def nesting(req: NestingRequest, catalog: list[Material] = Depends(get_catalog)):
    rows = compute_bom(req.panels, catalog)
    results = nest_cut_list(
        rows, catalog, kerf_mm=req.options.kerf_mm, edge_banding_margin_mm=req.options.edge_banding_margin_mm
    )
    return NestingResponse(
        bom=BomResponse(rows=rows, material_summary=compute_material_summary(req.panels)),
        results=results,
        summary=summarize(results, catalog),
    )
