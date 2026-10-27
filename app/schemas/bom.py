from pydantic import ConfigDict

from .base import CamelModel


class Panel(CamelModel):
    """A RESOLVED panel (output of the modeller's resolveConstraints)."""

    model_config = CamelModel.model_config | ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    piece_code: str | None = None
    width: float
    height: float
    thickness: float
    material: str
    banded_edges: list[str] = []
    group_id: str | None = None
    box_group_id: str | None = None
    is_door: bool = False
    is_plinth_panel: bool = False
    is_leg: bool = False
    is_box_panel: bool = False
    is_drawer_front: bool = False
    is_drawer_box_panel: bool = False


class BomRequest(CamelModel):
    panels: list[Panel]


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


class MaterialSummaryRow(CamelModel):
    material: str
    thickness: float
    quantity: int
    area_m2: float


class BomResponse(CamelModel):
    rows: list[BomRow]
    material_summary: list[MaterialSummaryRow]
