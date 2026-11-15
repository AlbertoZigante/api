"""Invariants every nesting result must satisfy, whatever the heuristic does (migration phase 6).

They are the safety net that lets the packing algorithm change later (rectpack, better heuristics)
without silently producing cut lists that cannot be cut:
  geometry  - every piece inside the sheet, no two pieces closer than the saw kerf
  grain     - a piece is rotated only if its material allows it
  integrity - every input piece is placed XOR reported unplaced, never lost or duplicated;
              a piece reported unplaced really does not fit the stock sheet
  numbers   - areas / utilisation / summary totals are consistent with the placements
Each checker returns a list of human-readable violations ([] = fine).
"""
from __future__ import annotations

from typing import Any

EPS = 1e-6


def sheet_geometry_violations(sheet: dict, kerf: float) -> list[str]:
    out: list[str] = []
    sw, sh, pl = sheet["widthMm"], sheet["heightMm"], sheet["placements"]
    if not pl:
        out.append(f"sheet {sheet['sheetIndex']}: empty sheet")
    for p in pl:
        if p["xMm"] < -EPS or p["yMm"] < -EPS:
            out.append(f"{p['pieceId']}: negative origin")
        if p["xMm"] + p["widthMm"] > sw + EPS or p["yMm"] + p["heightMm"] > sh + EPS:
            out.append(f"{p['pieceId']}: outside the {sw:g}x{sh:g} sheet")
        if p["widthMm"] <= 0 or p["heightMm"] <= 0:
            out.append(f"{p['pieceId']}: non-positive size")
    for i, a in enumerate(pl):
        for b in pl[i + 1:]:
            gap_x = max(a["xMm"] - (b["xMm"] + b["widthMm"]), b["xMm"] - (a["xMm"] + a["widthMm"]))
            gap_y = max(a["yMm"] - (b["yMm"] + b["heightMm"]), b["yMm"] - (a["yMm"] + a["heightMm"]))
            if gap_x < kerf - EPS and gap_y < kerf - EPS:
                out.append(f"{a['pieceId']} / {b['pieceId']}: closer than kerf {kerf:g} (gaps {gap_x:.3f}, {gap_y:.3f})")
    ids = [p["pieceId"] for p in pl]
    if len(ids) != len(set(ids)):
        out.append(f"sheet {sheet['sheetIndex']}: a piece is placed twice")
    used = sum(p["widthMm"] * p["heightMm"] for p in pl) / 1e6
    total = sw * sh / 1e6
    if abs(sheet["usedAreaM2"] - used) > 1e-9 or abs(sheet["totalAreaM2"] - total) > 1e-9:
        out.append(f"sheet {sheet['sheetIndex']}: area fields disagree with placements")
    if not -EPS <= sheet["utilization"] <= 1 + EPS:
        out.append(f"sheet {sheet['sheetIndex']}: utilization {sheet['utilization']} out of [0,1]")
    return out


def nest_pieces_violations(pieces: list[dict], stock: dict, kerf: float, result: dict[str, Any]) -> list[str]:
    """Full check of `nest_pieces(pieces, stock, kerf)`."""
    out: list[str] = []
    sheets, unplaced = result["sheets"], result["unplaced"]
    by_id = {p["id"]: p for p in pieces}
    if [s["sheetIndex"] for s in sheets] != list(range(len(sheets))):
        out.append("sheet indexes are not 0..n-1")
    for s in sheets:
        if (s["widthMm"], s["heightMm"]) != (stock["widthMm"], stock["heightMm"]):
            out.append(f"sheet {s['sheetIndex']}: not the stock size")
        out += sheet_geometry_violations(s, kerf)

    placed = [pl["pieceId"] for s in sheets for pl in s["placements"]]
    lost = [p["id"] for p in unplaced]
    if len(placed) != len(set(placed)):
        out.append("a piece is placed on more than one sheet")
    if set(placed) & set(lost):
        out.append("a piece is both placed and unplaced")
    if sorted(placed + lost) != sorted(by_id):
        out.append(f"pieces lost or invented: placed+unplaced={len(placed) + len(lost)} input={len(by_id)}")

    for s in sheets:
        for pl in s["placements"]:
            src = by_id.get(pl["pieceId"])
            if src is None:
                continue
            expect = (src["heightMm"], src["widthMm"]) if pl["rotated"] else (src["widthMm"], src["heightMm"])
            if (pl["widthMm"], pl["heightMm"]) != expect:
                out.append(f"{pl['pieceId']}: placed size does not match the piece (rotated={pl['rotated']})")
            if pl["rotated"] and not src["rotatable"]:
                out.append(f"{pl['pieceId']}: rotated although grain forbids it")
    sw, sh = stock["widthMm"], stock["heightMm"]
    for p in unplaced:
        fits = (p["widthMm"] <= sw and p["heightMm"] <= sh) or (p["rotatable"] and p["heightMm"] <= sw and p["widthMm"] <= sh)
        if fits:
            out.append(f"{p['id']}: reported unplaced but fits an empty sheet")
    return out


def cut_list_violations(body: dict, kerf_of_material: dict[str, float], kerf_override: float | None = None) -> list[str]:
    """Check a whole POST /v1/nesting response (bom + results + summary)."""
    out: list[str] = []
    expected: dict[tuple[str, float], int] = {}
    for row in body["bom"]["rows"]:
        if not row["isHardware"]:
            key = (row["material"], float(row["thicknessMm"]))
            expected[key] = expected.get(key, 0) + row["quantity"]

    seen: dict[tuple[str, float], int] = {}
    for r in body["results"]:
        key = (r["material"], float(r["thicknessMm"]))
        seen[key] = len(r["unplaced"]) + sum(len(s["placements"]) for s in r["sheets"])
        kerf = kerf_override if kerf_override is not None else kerf_of_material.get(r["material"], 3.0)
        if r["stockSheet"] is None and r["sheets"]:
            out.append(f"{key}: sheets without a stock sheet")
        for s in r["sheets"]:
            out += [f"{key}: {v}" for v in sheet_geometry_violations(s, kerf)]
            for pl in s["placements"]:
                if not (0 < pl["finishedWidthMm"] <= pl["widthMm"] + EPS and 0 < pl["finishedHeightMm"] <= pl["heightMm"] + EPS):
                    out.append(f"{pl['pieceId']}: finished size larger than the placed size")
    if seen != expected:
        out.append(f"piece counts differ from the BOM: nested={seen} bom={expected}")

    per, totals = body["summary"]["perMaterial"], body["summary"]["totals"]
    if totals["sheetsUsed"] != sum(len(r["sheets"]) for r in body["results"]):
        out.append("summary.sheetsUsed != number of sheets")
    if totals["unplacedCount"] != sum(len(r["unplaced"]) for r in body["results"]):
        out.append("summary.unplacedCount != number of unplaced pieces")
    if abs(totals["totalCost"] - sum(m["totalCost"] for m in per)) > 1e-6:
        out.append("summary.totalCost != sum of per-material costs")
    if not -EPS <= totals["utilization"] <= 1 + EPS:
        out.append("summary.utilization out of [0,1]")
    return out
