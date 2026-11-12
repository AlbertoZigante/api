from fastapi import APIRouter

from ..rules import CONTRACT_VERSION, RULES_VERSION
from ..schemas.base import CamelModel

router = APIRouter(prefix="/v1", tags=["meta"])


class VersionInfo(CamelModel):
    api_version: str
    rules_version: str
    contract_version: str


@router.get("/version", response_model=VersionInfo)
def version() -> VersionInfo:
    from ..main import API_VERSION  # late import: main imports this router

    return VersionInfo(api_version=API_VERSION, rules_version=RULES_VERSION, contract_version=CONTRACT_VERSION)
