"""RAW panel graph — the request contract for joints / hardware-plan / assembly.

Why RAW and not resolved: hardware selection and assembly read feature data
that only exists on the raw nodes (door hinge side, drawer links, plinth/leg
roles, constraints). The server resolves the graph itself, so the client can
never feed it tampered joints or positions.

Deliberately NOT accepted (dropped by extra="ignore"): `relations` /
declared joints, resolved positions, UI state. Everything is validated and
bounded: this model is the trust boundary.

All lengths are millimetres.
"""
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from .base import CamelModel
from .limits import (
    MAX_COORD_MM,
    MAX_DIM_MM,
    MAX_LIST,
    MAX_PANELS,
    MAX_QUANTITY,
    MAX_ROTATION,
    MAX_STR,
    MAX_THICKNESS_MM,
)

ShortStr = Annotated[str, Field(max_length=MAX_STR)]
Coord = Annotated[float, Field(ge=-MAX_COORD_MM, le=MAX_COORD_MM)]
Angle = Annotated[float, Field(ge=-MAX_ROTATION, le=MAX_ROTATION)]
Dim = Annotated[float, Field(gt=0, le=MAX_DIM_MM)]
Thickness = Annotated[float, Field(gt=0, le=MAX_THICKNESS_MM)]
Margin = Annotated[float, Field(ge=0, le=MAX_DIM_MM)]
Axis = Literal["x", "y", "z"]
Names = Annotated[list[ShortStr], Field(max_length=MAX_LIST)]


class _Model(CamelModel):
    model_config = CamelModel.model_config | ConfigDict(extra="ignore")


class Vec3(_Model):
    x: Coord = 0
    y: Coord = 0
    z: Coord = 0


class Rotation3(_Model):
    x: Angle = 0
    y: Angle = 0
    z: Angle = 0


class ConstraintEnd(_Model):
    node: ShortStr
    face: ShortStr | None = None
    offset: Coord = 0


class Constraint(_Model):
    id: ShortStr | None = None
    type: ShortStr
    field: ShortStr | None = None
    overridden: bool = False
    from_: ConstraintEnd | None = Field(default=None, alias="from")
    to: ConstraintEnd | None = None


class DrawerBoxSpec(_Model):
    bottom_margin_mm: Margin | None = None
    depth_margin_mm: Margin | None = None
    top_margin_mm: Margin | None = None
    width_margin_mm: Margin | None = None
    thickness_mm: Thickness | None = None
    material: ShortStr | None = None


class PlinthEdge(_Model):
    fit: ShortStr
    inset_mm: Margin = 0


class RawPanelNode(_Model):
    id: ShortStr
    name: ShortStr
    type: Literal["panel"] = "panel"
    piece_code: ShortStr | None = None
    material: ShortStr
    width: Dim
    height: Dim
    thickness: Thickness
    quantity: Annotated[int, Field(ge=1, le=MAX_QUANTITY)] = 1
    thickness_axis: Axis = "z"
    rotation: Rotation3 = Rotation3()
    base_position: Vec3 = Vec3()
    offset: Vec3 = Vec3()
    hidden: bool = False
    banded_edges: Names = []
    group_id: ShortStr | None = None
    box_group_id: ShortStr | None = None
    constraints: Annotated[list[Constraint], Field(max_length=MAX_LIST)] = []

    # UI-owned but harmless; kept so round-trips of the modeller's nodes are lossless
    ownership: ShortStr | None = None
    ownership_reason: ShortStr | None = None
    display_color: Annotated[int, Field(ge=0, le=0xFFFFFF)] | None = None
    locked_fields: Annotated[dict[ShortStr, bool], Field(max_length=MAX_LIST)] = {}
    locked_move_axes: Names = []
    locked_resize_axes: Names = []

    # role flags
    is_box_panel: bool = False
    is_box_wall: bool = False
    is_door: bool = False
    is_leg: bool = False
    is_plinth_panel: bool = False
    is_plinth_rib: bool = False
    is_drawer_front: bool = False
    is_drawer_box_panel: bool = False

    # door
    hinge: Literal["left", "right"] | None = None
    normal_axis: Axis | None = None
    door_sign: Literal[-1, 1] | None = None
    door_open: bool | None = None

    # drawer
    drawer_stack_id: ShortStr | None = None
    drawer_count: Annotated[int, Field(ge=1, le=MAX_LIST)] | None = None
    drawer_index: Annotated[int, Field(ge=0, le=MAX_LIST)] | None = None
    drawer_heights: Annotated[list[Dim], Field(max_length=MAX_LIST)] | None = None
    drawer_layout_mode: ShortStr | None = None
    drawer_box_front_id: ShortStr | None = None
    drawer_box_role: ShortStr | None = None
    drawer_box_spec: DrawerBoxSpec | None = None
    axis_a: Axis | None = None
    axis_b: Axis | None = None
    sign: Literal[-1, 1] | None = None

    # plinth / legs / box
    plinth_role: ShortStr | None = None
    plinth_edge_fit: Annotated[dict[ShortStr, PlinthEdge], Field(max_length=MAX_LIST)] | None = None
    leg_role: ShortStr | None = None
    boundary_ids: Annotated[dict[ShortStr, ShortStr], Field(max_length=MAX_LIST)] | None = None
    edge_fit: Annotated[dict[ShortStr, ShortStr], Field(max_length=MAX_LIST)] | None = None


class PanelSet(_Model):
    """Request body of POST /v1/joints, /v1/hardware-plan and /v1/assembly."""

    panels: Annotated[list[RawPanelNode], Field(max_length=MAX_PANELS)]

    @model_validator(mode="after")
    def _graph_is_consistent(self) -> Self:
        ids = [p.id for p in self.panels]
        if len(set(ids)) != len(ids):
            raise ValueError("panel ids must be unique")
        known = set(ids)
        for p in self.panels:
            for c in p.constraints:
                for end in (c.from_, c.to):
                    if end is not None and end.node not in known:
                        raise ValueError(f"constraint on {p.id} references unknown panel")
        return self


class ResolvedPanel(_Model):
    """Output shape of the modeller's resolveConstraints (kept for the future
    server-side port and its golden tests; not a request body)."""

    id: ShortStr
    name: ShortStr
    material: ShortStr
    width: Dim
    height: Dim
    thickness: Thickness
    quantity: int = 1
    thickness_axis: Axis = "z"
    hidden: bool = False
    group_id: ShortStr | None = None
    position: Vec3
    base_position: Vec3
    rotation: Rotation3
    locked_fields: dict[str, bool] = {}
    warnings: list[str] = []
    resize_proxy: None = None
