"""Rules-chain endpoints: /v1/joints (phase 8b), /v1/hardware-plan (9a), /v1/assembly (9b)."""
from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..errors import ApiError
from ..ratelimit import rate_limit
from ..rules.assembly import build_assembly_plan
from ..schemas.engine import AssemblyResponse, HardwarePlanResponse, JointsResponse
from ..schemas.panels import PanelSet
from ..services.hardware import build_hardware_plan
from ..services.joints import detect_feature_joints, detect_joints
from ..services.resolve import resolve_constraints

router = APIRouter(
    prefix="/v1",
    tags=["rules-chain"],
    dependencies=[Depends(require_auth), Depends(rate_limit)],
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


# exclude_unset: only fastener `unmatched` entries carry jointId/jointType (absent on hinge/runner entries).
@router.post("/hardware-plan", response_model=HardwarePlanResponse, response_model_exclude_unset=True)
def hardware_plan(req: PanelSet) -> HardwarePlanResponse:
    """RAW graph -> server-side resolve -> joints (server-computed) -> hinges, runners, fasteners + unmatched."""
    return HardwarePlanResponse.model_validate(build_hardware_plan(req.panels, resolve_constraints(req.panels)))


# exclude_unset: optional step fields (jointObjects, repeatHardware, completionInstruction...) are absent, not null.
@router.post("/assembly", response_model=AssemblyResponse, response_model_exclude_unset=True)
def assembly(req: PanelSet) -> AssemblyResponse:
    """RAW graph -> server-side resolve -> joints -> hardware -> ordered steps + clusters + tools."""
    return AssemblyResponse.model_validate(build_assembly_plan(req.panels, resolve_constraints(req.panels)))
