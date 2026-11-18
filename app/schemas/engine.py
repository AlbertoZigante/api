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
# Structured wording (phase 10): the client renders `verb` + `params` (and the codes below) in the user's language
# instead of showing the legacy English prose. These Literals ARE the contract: the OpenAPI enums are scanned by the
# modeller's tests, which fail if a code has no translation in every locale.
StepVerb = Literal[
    "prepare_hardware", "fit_guide_box_left", "fit_guide_box_right", "mount_guide_shelf", "mount_guide_panel",
    "start_door", "start_drawer", "start_plinth", "start_subassembly", "set_aside", "place_loose",
    "attach_to", "attach_plain", "install_closure_back", "install_closure_top",
    "fit_handle_door", "fit_handle_drawer_front", "fit_plinth", "fit_plinth_to", "slide_drawer", "hang_door",
    "install_back", "install_top", "install_vertical", "install_horizontal",
    "drawer_attach_left", "drawer_attach_right", "drawer_attach_back", "drawer_attach_bottom",
    "identify_unattached",
]
WarningCode = Literal[
    "door_build_flat", "door_support_hinges", "drawer_complete_box", "vertical_before_top", "horizontal_before_back",
    "back_after_internals", "top_after_internals", "keep_panel_separate", "handle_fit_flat",
]
ToolCode = Literal["screwdriver_pz2", "drill_bit_pilot_4_5", "drill_bit_clearance_7", "bit_pozidriv_pz3"]
ToolNoteCode = Literal["concealed_hinge", "drawer_runner_wood_screw", "confirmat_screw"]
ComponentKind = Literal["door", "drawer", "drawers", "plinth", "guides", "carcass", "integration"]
ClusterRole = Literal["door", "drawer_box", "drawer_front", "plinth", "carcass"]


class StepComponent(_Out):
    """Structured twin of componentTitle / componentSubtitle."""
    kind: ComponentKind
    ordinal: int | None = None      # door / plinth: its number when there are several
    number: int | None = None       # a single drawer
    count: int | None = None        # identical drawers built together
    numbers: list[int] | None = None


class SubassemblyRef(_Out):
    """Structured twin of subassemblyName: a cluster (role + ordinal), drawer(s), or a generic fallback."""
    role: ClusterRole | None = None
    ordinal: int | None = None
    drawer: int | None = None
    drawers: list[int] | None = None
    count: int | None = None
    fallback: Literal["door", "drawer"] | None = None


class AssemblyCluster(_Out):
    id: str
    name: str
    role: ClusterRole
    ordinal: int
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
    subassembly_id: str | None = None  # null for a step whose panel belongs to no cluster (e.g. a hidden panel)
    subassembly_name: str | None = None
    subassembly_complete: bool
    integration_subassembly_ids: list[str] | None = None
    cluster_kind: str | None = None
    component_kind: str
    component_title: str | None = None
    component_subtitle: str | None = None
    repeat_count: int
    repeat_labels: list[str] | None = None
    repeat_hardware: list[dict[str, Any]] | None = None
    hardware: list[dict[str, Any]]
    tools: list[str]
    tool_notes: list[str]
    ergonomic: dict[str, float]
    ergonomics: dict[str, Any]
    # --- structured wording (render these in the user's language) ---
    order: int
    verb: StepVerb
    instruction_verb: StepVerb
    params: dict[str, Any]
    warning_codes: list[WarningCode]
    hardware_ids: list[str]
    tool_codes: list[ToolCode]
    tool_note_codes: list[ToolNoteCode]
    component: StepComponent | None = None
    subassembly_ref: SubassemblyRef | None = None
    completion_ref: SubassemblyRef | None = None
    # --- legacy English prose (kept for the JS path and as a fallback; same content as the codes above) ---
    description: str
    instruction: str
    orientation_instruction: str
    completion_instruction: str | None = None
    warnings: list[str]


class AssemblyResponse(_Out):
    steps: list[AssemblyStep]
    clusters: list[AssemblyCluster]
    tools_summary: list[str]
    tools_summary_codes: list[ToolCode]
