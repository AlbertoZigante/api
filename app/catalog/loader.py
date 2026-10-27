import csv
from pathlib import Path

from ..schemas.catalog import Material

DATA_DIR = Path(__file__).parent / "data"


def _bool(v: str) -> bool:
    return v.strip().lower() == "true"


def load_materials(path: Path = DATA_DIR / "materials.csv") -> list[Material]:
    """CSV -> Material list. utf-8-sig: the modeller's CSV starts with a BOM."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = []
        for r in csv.DictReader(f):
            if not r.get("name"):
                continue
            rows.append(
                Material(
                    name=r["name"].strip(),
                    thickness_mm=float(r["thicknessMm"]),
                    grain_interchangeable=_bool(r["grainInterchangeable"]),
                    sheet_width_mm=float(r["sheetWidthMm"] or 0),
                    sheet_height_mm=float(r["sheetHeightMm"] or 0),
                    price_per_sheet=float(r["pricePerSheet"] or 0),
                    edge_banding_price_per_m=float(r["edgeBandingPricePerM"] or 0),
                    kerf_mm=float(r["kerfMm"]) if r.get("kerfMm") else None,
                )
            )
    if not rows:
        raise RuntimeError("Material catalog is empty")
    return rows
