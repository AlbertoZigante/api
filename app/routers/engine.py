"""Rules-chain endpoints. /v1/joints is live (migration phase 8b); /v1/hardware-plan and /v1/assembly validate
the request fully but answer 501 until their port lands (phase 9)."""
from fastapi import APIRouter, Depends

from ..deps import require_api_key
from ..errors import ApiError
from ..schemas.engine import AssemblyResponse, HardwarePlanResponse, JointsResponse
from ..schemas.panels import PanelSet
from ..services.joints import detect_feature_joints, detect_joints
from ..services.resolve import resolve_constraints

router = APIRouter(
    prefix="/v1",
    tags=["rules-chain"],
    dependencies=[Depends(require_api_key)],
    responses={501: {"description": "Not implemented yet (contract only)"}},
)


def _not_implemented() -> ApiError:
    return ApiError(501, "not_implemented", "Endpoint contract is defined; logic not ported yet")


# exclude_unset: a door hinge has no `clearanceMm` at all (only drawer slides do) — the key is absent, not null.
@router.post("/joints", response_model=JointsResponse, response_model_exclude_unset=True)
def joints(req: PanelSet) -> JointsResponse:
    """RAW graph -> server-side resolve -> contact joints + collisions + door-hinge / drawer-slide joints."""
    resolved = resolve_constraints(req.panels)
    found = detect_joints(resolved)
    return JointsResponse.model_validate(
        {**found, "featureJoints": detect_feature_joints(req.panels, resolved)}
    )


@router.post("/hardware-plan", response_model=HardwarePlanResponse)
def hardware_plan(req: PanelSet) -> HardwarePlanResponse:
    raise _not_implemented()


@router.post("/assembly", response_model=AssemblyResponse)
def assembly(req: PanelSet) -> AssemblyResponse:
    raise _not_implemented()
