from fastapi import APIRouter, Depends

from ..deps import get_catalog, require_api_key
from ..schemas.catalog import Material

router = APIRouter(prefix="/v1/catalog", tags=["catalog"], dependencies=[Depends(require_api_key)])


@router.get("/materials", response_model=list[Material])
def materials(catalog: list[Material] = Depends(get_catalog)):
    return catalog
