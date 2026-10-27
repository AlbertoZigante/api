"""Nesting / cut optimisation. Port of modeller src/engine/nesting.js.

Free-rectangle guillotine packing, best-area-fit. Grain runs along HEIGHT;
a piece may only be rotated if `rotatable` (material.grainInterchangeable).
Internals use camelCase dicts, identical to the JS shapes.
"""
import math

from ..schemas.bom import BomRow
from ..schemas.catalog import Material

GRAIN_AXIS = "height"
DEFAULT_KERF_MM = 3.0
DEFAULT_EDGE_BANDING_MARGIN_MM = 1.0
EDGE_TO_MARGIN_AXIS = {"left": "width", "right": "width", "top": "height", "bottom": "height"}
EPS = 1e-9


def _fits_as_given(p, mw, mh):
    return p["widthMm"] <= mw and p["heightMm"] <= mh


def _fits_rotated(p, mw, mh):
    return p["rotatable"] and p["heightMm"] <= mw and p["widthMm"] <= mh


def _best_orientation(p, mw, mh):
    given = (
        {"widthMm": p["widthMm"], "heightMm": p["heightMm"], "rotated": False}
        if _fits_as_given(p, mw, mh)
        else None
    )
    rot = (
        {"widthMm": p["heightMm"], "heightMm": p["widthMm"], "rotated": True}
        if _fits_rotated(p, mw, mh)
        else None
    )
    if given and rot:
        return rot if (mh - rot["heightMm"]) < (mh - given["heightMm"]) else given
    return given or rot


def _rect_fits(r, w, h):
    return w <= r["widthMm"] + EPS and h <= r["heightMm"] + EPS


def _fit_score(r, w, h):
    return (r["widthMm"] * r["heightMm"] - w * h, min(r["widthMm"] - w, r["heightMm"] - h))


def _is_better(a, b):
    if a[0] < b[0] - EPS:
        return True
    if a[0] > b[0] + EPS:
        return False
    return a[1] < b[1] - EPS


def _split_free_rect(r, pw, ph, kerf):
    right_w = r["widthMm"] - pw - kerf
    bottom_h = r["heightMm"] - ph - kerf

    o1, o2 = [], []
    if right_w > 1e-6:
        o1.append({"xMm": r["xMm"] + pw + kerf, "yMm": r["yMm"], "widthMm": right_w, "heightMm": r["heightMm"]})
    if bottom_h > 1e-6:
        o1.append({"xMm": r["xMm"], "yMm": r["yMm"] + ph + kerf, "widthMm": pw, "heightMm": bottom_h})
    if bottom_h > 1e-6:
        o2.append({"xMm": r["xMm"], "yMm": r["yMm"] + ph + kerf, "widthMm": r["widthMm"], "heightMm": bottom_h})
    if right_w > 1e-6:
        o2.append({"xMm": r["xMm"] + pw + kerf, "yMm": r["yMm"], "widthMm": right_w, "heightMm": ph})

    def max_area(opts):
        return max((o["widthMm"] * o["heightMm"] for o in opts), default=0)

    return o1 if max_area(o1) >= max_area(o2) else o2


def _prune(rects):
    def contains(o, i):
        return (
            o["xMm"] <= i["xMm"] + 1e-6
            and o["yMm"] <= i["yMm"] + 1e-6
            and o["xMm"] + o["widthMm"] >= i["xMm"] + i["widthMm"] - 1e-6
            and o["yMm"] + o["heightMm"] >= i["yMm"] + i["heightMm"] - 1e-6
        )

    keep = []
    for i, r in enumerate(rects):
        drop = False
        for j, o in enumerate(rects):
            if j == i:
                continue
            o_in_r, r_in_o = contains(o, r), contains(r, o)
            if o_in_r and not r_in_o:
                drop = True
                break
            if o_in_r and r_in_o and j < i:
                drop = True
                break
        if not drop:
            keep.append(r)
    return keep


def _place(sheet, idx, w, h, rotated, piece_id, kerf):
    rect = sheet["freeRects"].pop(idx)
    sheet["placements"].append(
        {"pieceId": piece_id, "xMm": rect["xMm"], "yMm": rect["yMm"], "widthMm": w, "heightMm": h, "rotated": rotated}
    )
    sheet["freeRects"].extend(_split_free_rect(rect, w, h, kerf))
    sheet["freeRects"] = _prune(sheet["freeRects"])


def _summarize_sheet(s):
    total = s["widthMm"] * s["heightMm"]
    used = sum(p["widthMm"] * p["heightMm"] for p in s["placements"])
    return {
        "sheetIndex": s["sheetIndex"],
        "widthMm": s["widthMm"],
        "heightMm": s["heightMm"],
        "placements": s["placements"],
        "usedAreaM2": used / 1_000_000,
        "totalAreaM2": total / 1_000_000,
        "utilization": used / total if total > 0 else 0,
    }


def nest_pieces(pieces, stock, kerf=DEFAULT_KERF_MM):
    sw, sh = stock["widthMm"], stock["heightMm"]
    if not (sw > 0 and sh > 0):
        raise ValueError(f"stock sheet must have positive dimensions, got {stock}")
    if not kerf >= 0:
        raise ValueError(f"kerfMm must be >= 0, got {kerf}")

    ordered = sorted(
        pieces,
        key=lambda p: (-max(p["widthMm"], p["heightMm"]), -min(p["widthMm"], p["heightMm"])),
    )
    sheets, unplaced = [], []

    for piece in ordered:
        if not _fits_as_given(piece, sw, sh) and not _fits_rotated(piece, sw, sh):
            unplaced.append(piece)
            continue

        best = None
        for sheet in sheets:
            for ri, rect in enumerate(sheet["freeRects"]):
                cands = [(piece["widthMm"], piece["heightMm"], False)]
                if piece["rotatable"]:
                    cands.append((piece["heightMm"], piece["widthMm"], True))
                for w, h, rotated in cands:
                    if not _rect_fits(rect, w, h):
                        continue
                    score = _fit_score(rect, w, h)
                    if best is None or _is_better(score, best["score"]):
                        best = {"sheet": sheet, "ri": ri, "w": w, "h": h, "rotated": rotated, "score": score}

        if best:
            _place(best["sheet"], best["ri"], best["w"], best["h"], best["rotated"], piece["id"], kerf)
        else:
            sheet = {
                "sheetIndex": len(sheets),
                "widthMm": sw,
                "heightMm": sh,
                "freeRects": [{"xMm": 0, "yMm": 0, "widthMm": sw, "heightMm": sh}],
                "placements": [],
            }
            sheets.append(sheet)
            o = _best_orientation(piece, sw, sh)
            _place(sheet, 0, o["widthMm"], o["heightMm"], o["rotated"], piece["id"], kerf)

    return {"sheets": [_summarize_sheet(s) for s in sheets], "unplaced": unplaced}


def nest_cut_list(rows: list[BomRow], catalog: list[Material], kerf_mm=None, edge_banding_margin_mm=DEFAULT_EDGE_BANDING_MARGIN_MM):
    by_material: dict[str, list] = {}
    for row in rows:
        if row.is_hardware:
            continue
        key = f"{row.material}::{row.thickness_mm:g}"
        lst = by_material.setdefault(key, [])
        mw = sum(1 for e in row.banded_edges if EDGE_TO_MARGIN_AXIS.get(e) == "width") * edge_banding_margin_mm
        mh = sum(1 for e in row.banded_edges if EDGE_TO_MARGIN_AXIS.get(e) == "height") * edge_banding_margin_mm
        for i in range(row.quantity):
            code = row.piece_codes[i] if i < len(row.piece_codes) else None
            lst.append(
                {
                    "id": code or f"{row.label}#{i + 1}",
                    "label": row.label,
                    "widthMm": row.width_mm + mw,
                    "heightMm": row.height_mm + mh,
                    "rotatable": row.grain_interchangeable,
                    "finishedWidthMm": row.width_mm,
                    "finishedHeightMm": row.height_mm,
                }
            )

    results = []
    for key, pieces in by_material.items():
        material, thickness = key.rsplit("::", 1)
        entry = next((m for m in catalog if m.name == material), None)
        if not entry or not entry.sheet_width_mm or not entry.sheet_height_mm:
            results.append(
                {"material": material, "thicknessMm": float(thickness), "stockSheet": None, "sheets": [], "unplaced": pieces}
            )
            continue
        stock = {"widthMm": entry.sheet_width_mm, "heightMm": entry.sheet_height_mm}

        kerf = DEFAULT_KERF_MM
        if kerf_mm is not None:
            kerf = kerf_mm
        elif entry.kerf_mm is not None and math.isfinite(entry.kerf_mm) and entry.kerf_mm >= 0:
            kerf = entry.kerf_mm

        res = nest_pieces(pieces, stock, kerf)
        by_id = {p["id"]: p for p in pieces}
        for sheet in res["sheets"]:
            for pl in sheet["placements"]:
                src = by_id.get(pl["pieceId"])
                if not src:
                    continue
                pl["finishedWidthMm"] = src["finishedHeightMm"] if pl["rotated"] else src["finishedWidthMm"]
                pl["finishedHeightMm"] = src["finishedWidthMm"] if pl["rotated"] else src["finishedHeightMm"]
        results.append(
            {"material": material, "thicknessMm": float(thickness), "stockSheet": stock, "sheets": res["sheets"], "unplaced": res["unplaced"]}
        )
    return results


def summarize(results, catalog: list[Material]):
    per = []
    for r in results:
        entry = next((m for m in catalog if m.name == r["material"]), None)
        price = (entry.price_per_sheet if entry else 0) or 0
        used_sheets = len(r["sheets"])
        total_area = sum(s["totalAreaM2"] for s in r["sheets"])
        used_area = sum(s["usedAreaM2"] for s in r["sheets"])
        unplaced_area = sum(
            (p.get("finishedWidthMm", p["widthMm"]) * p.get("finishedHeightMm", p["heightMm"])) / 1_000_000
            for p in r["unplaced"]
        )
        per.append(
            {
                "material": r["material"],
                "thicknessMm": r["thicknessMm"],
                "sheetsUsed": used_sheets,
                "pricePerSheet": price,
                "totalCost": used_sheets * price,
                "totalAreaM2": total_area,
                "usedAreaM2": used_area,
                "wasteAreaM2": total_area - used_area,
                "utilization": used_area / total_area if total_area > 0 else 0,
                "unplacedCount": len(r["unplaced"]),
                "unplacedAreaM2": unplaced_area,
                "unplacedLabels": list(dict.fromkeys(p["label"] for p in r["unplaced"] if p.get("label"))),
            }
        )
    keys = ["sheetsUsed", "totalCost", "totalAreaM2", "usedAreaM2", "wasteAreaM2", "unplacedCount", "unplacedAreaM2"]
    totals = {k: sum(m[k] for m in per) for k in keys}
    totals["utilization"] = totals["usedAreaM2"] / totals["totalAreaM2"] if totals["totalAreaM2"] > 0 else 0
    return {"perMaterial": per, "totals": totals}
