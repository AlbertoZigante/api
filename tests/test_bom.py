from app.schemas.bom import Panel
from app.services.bom import compute_bom, compute_material_summary
from tests.conftest import panel


def P(*a, **k):
    return Panel.model_validate(panel(*a, **k))


def test_identical_pieces_merge_within_assembly(catalog):
    ps = [P("Left", 400, 700, groupId="g1", isBoxPanel=True), P("Right", 400, 700, groupId="g1", isBoxPanel=True)]
    rows = compute_bom(ps, catalog)
    assert len(rows) == 1 and rows[0].quantity == 2
    assert rows[0].label == "Box 1 — Left/Right"


def test_grain_directional_never_merges_with_rotated_twin(catalog):
    m = "Melamine Oak 18mm"  # grainInterchangeable = false
    rows = compute_bom([P("A", 400, 300, m), P("B", 300, 400, m)], catalog)
    assert len(rows) == 2


def test_rotatable_material_merges_rotated_twin(catalog):
    rows = compute_bom([P("A", 400, 300), P("B", 300, 400)], catalog)
    assert len(rows) == 1 and rows[0].quantity == 2


def test_unknown_material_defaults_to_directional(catalog):
    rows = compute_bom([P("A", 400, 300, "Nope"), P("B", 300, 400, "Nope")], catalog)
    assert len(rows) == 2


def test_banding_length_and_cost(catalog):
    rows = compute_bom([P("A", 400, 700, bandedEdges=["left", "top"])], catalog)
    r = rows[0]
    assert r.banding_length_m == (700 + 400) / 1000
    assert abs(r.banding_cost - r.banding_length_m * 1.20) < 1e-9


def test_material_summary(catalog):
    s = compute_material_summary([P("A", 1000, 1000), P("B", 1000, 1000)])
    assert s[0].quantity == 2 and abs(s[0].area_m2 - 2.0) < 1e-9
