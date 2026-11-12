"""Rules-chain endpoints. CONTRACT ONLY for now: the request is fully validated
(so clients and tests can exercise the trust boundary) and the logic answers
501 until the Python port lands (migration phases 8-9)."""
from fastapi import APIRouter, Depends

from ..deps import require_api_key
from ..errors import ApiError
from ..schemas.engine import AssemblyResponse, HardwarePlanResponse, JointsResponse
from ..schemas.panels import PanelSet

router = APIRouter(
    prefix="/v1",
    tags=["rules-chain"],
    dependencies=[Depends(require_api_key)],
    responses={501: {"description": "Not implemented yet (contract only)"}},
)


def _not_implemented() -> ApiError:
    return ApiError(501, "not_implemented", "Endpoint contract is defined; logic not ported yet")


@router.post("/joints", response_model=JointsResponse)
def joints(req: PanelSet) -> JointsResponse:
    raise _not_implemented()


@router.post("/hardware-plan", response_model=HardwarePlanResponse)
def hardware_plan(req: PanelSet) -> HardwarePlanResponse:
    raise _not_implemented()


@router.post("/assembly", response_model=AssemblyResponse)
def assembly(req: PanelSet) -> AssemblyResponse:
    raise _not_implemented()
