from .base import CamelModel
from .bom import BomResponse, BomRow, Panel


class NestingOptions(CamelModel):
    kerf_mm: float | None = None
    edge_banding_margin_mm: float = 1


class NestingRequest(CamelModel):
    panels: list[Panel]
    options: NestingOptions = NestingOptions()


class Piece(CamelModel):
    id: str
    label: str
    width_mm: float
    height_mm: float
    rotatable: bool
    finished_width_mm: float
    finished_height_mm: float


class Placement(CamelModel):
    piece_id: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    rotated: bool
    finished_width_mm: float | None = None
    finished_height_mm: float | None = None


class Sheet(CamelModel):
    sheet_index: int
    width_mm: float
    height_mm: float
    placements: list[Placement]
    used_area_m2: float
    total_area_m2: float
    utilization: float


class StockSheet(CamelModel):
    width_mm: float
    height_mm: float


class NestResult(CamelModel):
    material: str
    thickness_mm: float
    stock_sheet: StockSheet | None
    sheets: list[Sheet]
    unplaced: list[Piece]


class MaterialNestSummary(CamelModel):
    material: str
    thickness_mm: float
    sheets_used: int
    price_per_sheet: float
    total_cost: float
    total_area_m2: float
    used_area_m2: float
    waste_area_m2: float
    utilization: float
    unplaced_count: int
    unplaced_area_m2: float
    unplaced_labels: list[str]


class NestTotals(CamelModel):
    sheets_used: int
    total_cost: float
    total_area_m2: float
    used_area_m2: float
    waste_area_m2: float
    unplaced_count: int
    unplaced_area_m2: float
    utilization: float


class NestSummary(CamelModel):
    per_material: list[MaterialNestSummary]
    totals: NestTotals


class NestingResponse(CamelModel):
    bom: BomResponse
    results: list[NestResult]
    summary: NestSummary
