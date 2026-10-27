from .base import CamelModel


class Material(CamelModel):
    name: str
    thickness_mm: float
    grain_interchangeable: bool = False
    sheet_width_mm: float = 0
    sheet_height_mm: float = 0
    price_per_sheet: float = 0
    edge_banding_price_per_m: float = 0
    kerf_mm: float | None = None
