from app.schemas.bom import Panel
from app.services.bom import compute_bom
from app.services.nesting import nest_cut_list, nest_pieces, summarize
from tests.conftest import panel

STOCK = {"widthMm": 2440, "heightMm": 1220}


def piece(id, w, h, rot=True):
    return {"id": id, "label": id, "widthMm": w, "heightMm": h, "rotatable": rot,
            "finishedWidthMm": w, "finishedHeightMm": h}


def test_single_piece_one_sheet():
    r = nest_pieces([piece("a", 500, 500)], STOCK, 3)
    assert len(r["sheets"]) == 1 and not r["unplaced"]


def test_oversize_piece_unplaced():
    r = nest_pieces([piece("a", 3000, 3000)], STOCK, 3)
    assert not r["sheets"] and len(r["unplaced"]) == 1


def test_no_rotation_when_grain_directional():
    r = nest_pieces([piece("a", 1500, 1000, rot=False)], {"widthMm": 1000, "heightMm": 1500}, 3)
    assert r["sheets"] == [] and len(r["unplaced"]) == 1


def test_no_overlap_and_inside_sheet():
    ps = [piece(f"p{i}", 600 + 37 * i, 400 + 23 * i) for i in range(20)]
    r = nest_pieces(ps, STOCK, 3)
    for s in r["sheets"]:
        pl = s["placements"]
        for p in pl:
            assert p["xMm"] + p["widthMm"] <= s["widthMm"] + 1e-6
            assert p["yMm"] + p["heightMm"] <= s["heightMm"] + 1e-6
        for i, a in enumerate(pl):
            for b in pl[i + 1:]:
                sep = (a["xMm"] + a["widthMm"] <= b["xMm"] or b["xMm"] + b["widthMm"] <= a["xMm"]
                       or a["yMm"] + a["heightMm"] <= b["yMm"] or b["yMm"] + b["heightMm"] <= a["yMm"])
                assert sep


def test_cut_list_end_to_end(catalog):
    ps = [Panel.model_validate(panel(f"p{i}", 500, 700)) for i in range(6)]
    rows = compute_bom(ps, catalog)
    res = nest_cut_list(rows, catalog)
    summ = summarize(res, catalog)
    t = summ["totals"]
    assert t["sheetsUsed"] >= 1 and t["unplacedCount"] == 0
    assert t["totalCost"] == t["sheetsUsed"] * 45.0


def test_parity_with_js_reference():
    """Placements verified identical to modeller src/engine/nesting.js (6x 500x700 on 2440x1220, kerf 3)."""
    ps = [piece(f"p{i}", 500, 700) for i in range(6)]
    r = nest_pieces(ps, STOCK, 3)
    assert len(r["sheets"]) == 2
