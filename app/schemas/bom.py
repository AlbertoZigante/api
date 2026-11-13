from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from .base import CamelModel
from .limits import MAX_DIM_MM, MAX_LIST, MAX_PANELS, MAX_STR, MAX_THICKNESS_MM

ShortStr = Annotated[str, Field(max_length=MAX_STR)]
Dim = Annotated[float, Field(gt=0, le=MAX_DIM_MM)]
Thickness = Annotated[float, Field(gt=0, le=MAX_THICKNESS_MM)]


class Panel(CamelModel):
    """A RESOLVED panel (output of the modeller's resolveConstraints)."""

    model_config = CamelModel.model_config | ConfigDict(extra="ignore")

    id: ShortStr
    name: ShortStr | None = None
    piece_code: ShortStr | None = None
    width: Dim
    height: Dim
    thickness: Thickness
    material: ShortStr
    banded_edges: Annotated[list[ShortStr], Field(max_length=MAX_LIST)] = []
    group_id: ShortStr | None = None
    box_group_id: ShortStr | None = None
    is_door: bool = False
    is_plinth_panel: bool = False
    is_leg: bool = False
    is_box_panel: bool = False
    is_drawer_front: bool = False
    is_drawer_box_panel: bool = False


class BomRequest(CamelModel):
    panels: Annotated[list[Panel], Field(max_length=MAX_PANELS)]


class BomRow(CamelModel):
    label: str
    piece_names: list[str]
    piece_codes: list[str | None]
    assembly: str
    width_mm: float
    height_mm: float
    thickness_mm: float
    material: str
    grain_interchangeable: bool
    banded_edges: list[str]
    banded_edges_label: str
    unit_banding_length_m: float
    quantity: int
    unit_area_m2: float
    is_hardware: bool
    area_m2: float
    banding_length_m: float
    banding_cost: float
    assembly_kind: Literal["box", "drawer", "group", "none"]
    assembly_index: int | None


class MaterialSummaryRow(CamelModel):
    material: str
    thickness: float
    quantity: int
    area_m2: float


class BomResponse(CamelModel):
    rows: list[BomRow]
    material_summary: list[MaterialSummaryRow]
