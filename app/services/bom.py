"""BOM / cut list. Port of modeller src/engine/bom.js (stateless, pure)."""
from ..schemas.bom import BomRow, MaterialSummaryRow, Panel
from ..schemas.catalog import Material

MM2_TO_M2 = 1 / 1_000_000
EDGE_BANDING_LENGTH_FIELD = {"right": "height", "left": "height", "top": "width", "bottom": "width"}


def _entry(catalog: list[Material], name: str) -> Material | None:
    return next((m for m in catalog if m.name == name), None)


def is_grain_interchangeable(catalog: list[Material], name: str) -> bool:
    # Safe default: unknown material => grain-directional (never merge/rotate).
    m = _entry(catalog, name)
    return bool(m and m.grain_interchangeable)


def _banding_length_mm(p: Panel) -> float:
    total = 0.0
    for face in p.banded_edges:
        field = EDGE_BANDING_LENGTH_FIELD.get(face)
        if field:
            total += getattr(p, field) or 0
    return total


def _edges_label(p: Panel) -> str:
    if not p.banded_edges:
        return "—"
    short = {"left": "L", "right": "R", "top": "T", "bottom": "B"}
    return ",".join(short.get(e, e) for e in p.banded_edges)


def _footprint_key(catalog: list[Material], p: Panel) -> str:
    rot = is_grain_interchangeable(catalog, p.material)
    a, b = (min(p.width, p.height), max(p.width, p.height)) if rot else (p.width, p.height)
    banding = "|".join(sorted(p.banded_edges))
    return f"{p.material}::{p.thickness}::{a}::{b}::{'rot' if rot else 'fixed'}::{banding}"


def _label_key(p: Panel) -> str | None:
    if p.is_door or p.is_plinth_panel or p.is_leg:
        return p.box_group_id if p.box_group_id is not None else p.group_id
    return p.group_id


def _group_labels(panels: list[Panel]) -> dict[str, str]:
    labels: dict[str, str] = {}
    box = group = drawer = 0
    for p in panels:
        key = _label_key(p)
        if not key or key in labels:
            continue
        if p.is_drawer_front or p.is_drawer_box_panel:
            drawer += 1
            labels[key] = f"Drawer {drawer}"
        elif p.is_box_panel:
            box += 1
            labels[key] = f"Box {box}"
        else:
            group += 1
            labels[key] = f"Group {group}"
    return labels


def _display_name(p: Panel) -> str:
    return p.name or p.id


def compute_bom(panels: list[Panel], catalog: list[Material]) -> list[BomRow]:
    labels = _group_labels(panels)
    rows: dict[str, dict] = {}

    for p in panels:
        assembly = "—" if not p.group_id else labels.get(_label_key(p), "Group")
        key = f"{assembly}::{_footprint_key(catalog, p)}"
        name = _display_name(p)
        row = rows.get(key)
        if row is None:
            rows[key] = {
                "label": name if assembly == "—" else f"{assembly} — {name}",
                "piece_names": [name],
                "piece_codes": [p.piece_code],
                "assembly": assembly,
                "width_mm": p.width,
                "height_mm": p.height,
                "thickness_mm": p.thickness,
                "material": p.material,
                "grain_interchangeable": is_grain_interchangeable(catalog, p.material),
                "banded_edges": list(p.banded_edges),
                "banded_edges_label": _edges_label(p),
                "unit_banding_length_m": _banding_length_mm(p) / 1000,
                "quantity": 1,
                "unit_area_m2": p.width * p.height * MM2_TO_M2,
                "is_hardware": p.is_leg,
            }
            continue
        row["quantity"] += 1
        row["piece_names"].append(name)
        row["piece_codes"].append(p.piece_code)
        uniq = list(dict.fromkeys(row["piece_names"]))
        joined = "/".join(uniq)
        row["label"] = joined if assembly == "—" else f"{assembly} — {joined}"

    out = []
    for row in rows.values():
        banding_len = row["unit_banding_length_m"] * row["quantity"]
        m = _entry(catalog, row["material"])
        price = m.edge_banding_price_per_m if m else 0
        out.append(
            BomRow(
                **row,
                area_m2=row["unit_area_m2"] * row["quantity"],
                banding_length_m=banding_len,
                banding_cost=banding_len * price,
            )
        )
    return sorted(out, key=lambda r: r.label.casefold())


def compute_material_summary(panels: list[Panel]) -> list[MaterialSummaryRow]:
    acc: dict[str, MaterialSummaryRow] = {}
    for p in panels:
        key = f"{p.material}::{p.thickness}"
        area = p.width * p.height * MM2_TO_M2
        if key in acc:
            acc[key].quantity += 1
            acc[key].area_m2 += area
        else:
            acc[key] = MaterialSummaryRow(material=p.material, thickness=p.thickness, quantity=1, area_m2=area)
    return sorted(acc.values(), key=lambda r: r.material.casefold())
