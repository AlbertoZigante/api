from fastapi import APIRouter, Depends

from ..deps import get_catalog, require_api_key
from ..schemas.bom import BomRequest, BomResponse
from ..schemas.catalog import Material
from ..services.bom import compute_bom, compute_material_summary

router = APIRouter(prefix="/v1", tags=["bom"], dependencies=[Depends(require_api_key)])


@router.post("/bom", response_model=BomResponse)
def bom(req: BomRequest, catalog: list[Material] = Depends(get_catalog)):
    return BomResponse(
        rows=compute_bom(req.panels, catalog),
        material_summary=compute_material_summary(req.panels),
    )
