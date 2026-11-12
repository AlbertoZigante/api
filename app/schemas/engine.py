"""Response contracts of the rules chain (joints -> hardware -> assembly).

Frozen from the modeller's JS output (fixtures/golden). Models forbid extra
fields on purpose: if the Python port emits a field the contract doesn't know
(or misses one), the golden tests fail instead of drifting silently.

NOTE (migration): AssemblyStep still carries the legacy prose fields
(instruction, description, warnings, ...). The target design replaces them with
structured data (verb + warningCodes) rendered by the client's i18n layer;
that change is a later phase and will bump CONTRACT_VERSION.
"""
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from .base import CamelModel


class _Out(CamelModel):
    model_config = CamelModel.model_config | ConfigDict(extra="forbid")


class Point3(_Out):
    x: float
    y: float
    z: float


# ---------------------------------------------------------------- joints
JointType = Literal["face_to_face", "corner_butt", "t_butt", "edge_to_edge", "near_contact"]


Interval = Annotated[list[float], Field(min_length=2, max_length=2)]  # [min, max] along an axis


class Joint(_Out):
    id: str
    type: JointType
    panel_a: str
    panel_b: str
    face_a: str
    face_b: str
    contact_axis: str
    contact_position: float
    gap: float
    overlap: dict[str, Interval]  # per-axis shared interval
    same_group: bool
    status: str


class Collision(_Out):
    panel_a: str
    panel_b: str
    overlap_mm: dict[str, float]


class FeatureJoint(_Out):
    id: str
    kind: Literal["door_hinge", "drawer_slide"]
    panel_a: str
    panel_b: str
    side: str
    axis: str
    length_mm: float
    clearance_mm: float | None = None
    p1: Point3
    p2: Point3


class JointsResponse(_Out):
    joints: list[Joint]
    collisions: list[Collision]
    feature_joints: list[FeatureJoint]


# ---------------------------------------------------------------- hardware
class _HardwareItem(_Out):
    display_id: str
    panel_a: str
    panel_b: str
    panel_a_name: str
    panel_b_name: str
    panel_a_code: str
    panel_b_code: str
    hardware: dict[str, Any]  # catalog entry (brand, id, ranges...) — catalog schema comes with the catalog port


class Hinge(_HardwareItem):
    kind: Literal["hinge"]
    side: str
    count: int
    positions: list[Point3]


class Runner(_HardwareItem):
    kind: Literal["runner"]
    side: str
    nominal_length_mm: float


class Fastener(_HardwareItem):
    kind: Literal["fastener"]
    joint_id: str
    joint_type: JointType
    positions: list[Point3]


class Unmatched(_Out):
    kind: Literal["hinge", "runner", "fastener"]
    panel_a: str
    panel_b: str
    panel_a_name: str
    panel_b_name: str
    panel_a_code: str
    panel_b_code: str
    joint_id: str | None = None
    joint_type: JointType | None = None


class HardwareSummary(_Out):
    hinge_count: int
    total_hinge_units: int
    runner_count: int
    fastener_joint_count: int
    total_fastener_count: int
    unmatched_count: int


class HardwarePlanResponse(_Out):
    summary: HardwareSummary
    hinges: list[Hinge]
    runners: list[Runner]
    fasteners: list[Fastener]
    unmatched: list[Unmatched]


# ---------------------------------------------------------------- assembly
class AssemblyCluster(_Out):
    id: str
    name: str
    role: str
    panel_ids: list[str]


class AssemblyStep(_Out):
    index: int
    step_id: str
    key: str | None = None
    stage: Literal["doors", "drawers", "guides", "plinth", "carcass", "integration"]
    kind: Literal["pre_install", "fit_handle", "join", "integrate", "unattached"]
    phase: Literal["prepare", "subassembly", "internal", "closure", "integration", "unattached"]
    action: str
    role: str
    orientation: str
    requires_reposition: bool
    reposition_cost: float
    panel_ids: list[str]
    other_panel_ids: list[str]
    panel_names: list[str]
    panel_codes: list[str]
    unit_panel_ids: list[str] | None = None
    joint_ids: list[str]
    joint_objects: list[dict[str, Any]] | None = None
    prerequisite_step_ids: list[str]
    subassembly_id: str
    subassembly_name: str
    subassembly_complete: bool
    integration_subassembly_ids: list[str] | None = None
    cluster_kind: str
    component_kind: str
    component_title: str
    component_subtitle: str | None = None
    repeat_count: int
    repeat_labels: list[str] | None = None
    repeat_hardware: list[dict[str, Any]] | None = None
    hardware: list[dict[str, Any]]
    tools: list[str]
    tool_notes: list[str]
    ergonomic: dict[str, float]
    ergonomics: dict[str, Any]
    # --- legacy prose (to be replaced by verb + warningCodes, see module note)
    description: str
    instruction: str
    orientation_instruction: str
    completion_instruction: str | None = None
    warnings: list[str]


class AssemblyResponse(_Out):
    steps: list[AssemblyStep]
    clusters: list[AssemblyCluster]
    tools_summary: list[str]
