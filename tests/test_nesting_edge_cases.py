"""Phase 6: behaviours of POST /v1/nesting around catalog, kerf, grain, banding and unplaceable pieces."""
import pytest

from app.deps import get_catalog
from app.main import app
from tests.conftest import panel
from tests.nesting_invariants import cut_list_violations

WHITE, OAK = "Melamine White 18mm", "Melamine Oak 18mm"  # OAK: grain directional (not interchangeable)


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.clear()


def nest(client, panels, options=None):
    r = client.post("/v1/nesting", json={"panels": panels, "options": options or {}})
    assert r.status_code == 200, r.text
    return r.json()


def result_for(body, material):
    return next(r for r in body["results"] if r["material"] == material)


def test_empty_design(client):
    body = nest(client, [])
    assert body["results"] == [] and body["summary"]["totals"]["sheetsUsed"] == 0
    assert body["summary"]["totals"]["utilization"] == 0


def test_unknown_material_is_reported_unplaced_not_an_error(client):
    body = nest(client, [panel("A", 400, 700, "No such board")])
    r = result_for(body, "No such board")
    assert r["stockSheet"] is None and r["sheets"] == [] and len(r["unplaced"]) == 1
    assert body["summary"]["totals"]["unplacedCount"] == 1


def test_oversize_piece_is_unplaced_and_named(client):
    body = nest(client, [panel("Big", 3000, 3000), panel("Ok", 400, 700)])
    r = result_for(body, WHITE)
    assert [p["label"] for p in r["unplaced"]] == ["Big"]
    assert sum(len(s["placements"]) for s in r["sheets"]) == 1
    assert body["summary"]["perMaterial"][0]["unplacedLabels"] == ["Big"]


def test_grain_rotation_depends_on_material(client):
    # 1000 x 2000 only fits a 2440x1220 sheet when turned 90 degrees
    white = result_for(nest(client, [panel("A", 1000, 2000, WHITE)]), WHITE)
    assert white["unplaced"] == [] and white["sheets"][0]["placements"][0]["rotated"] is True
    oak = result_for(nest(client, [panel("A", 1000, 2000, OAK)]), OAK)
    assert len(oak["unplaced"]) == 1 and oak["sheets"] == []


def test_directional_material_never_rotates_even_when_it_would_pack_better(client):
    panels = [panel(f"p{i}", 600, 1100, OAK) for i in range(8)]
    body = nest(client, panels)
    assert not any(pl["rotated"] for s in result_for(body, OAK)["sheets"] for pl in s["placements"])


@pytest.mark.parametrize("kerf", [0, 3, 12])
def test_kerf_option_is_honoured(client, catalog, kerf):
    panels = [panel(f"p{i}", 300 + 17 * i, 250 + 11 * i) for i in range(25)]
    body = nest(client, panels, {"kerfMm": kerf})
    assert cut_list_violations(body, {}, kerf_override=float(kerf)) == []


def test_catalog_kerf_is_used_when_no_option_is_given(client, catalog):
    thick = [m.model_copy(update={"kerf_mm": 12.0}) if m.name == WHITE else m for m in catalog]
    app.dependency_overrides[get_catalog] = lambda: thick
    panels = [panel(f"p{i}", 300 + 17 * i, 250 + 11 * i) for i in range(25)]
    body = nest(client, panels)
    assert cut_list_violations(body, {WHITE: 12.0}) == []
    # ...and the explicit option still wins over the catalog
    assert cut_list_violations(nest(client, panels, {"kerfMm": 1}), {WHITE: 12.0}, kerf_override=1.0) == []


def test_edge_banding_margin_is_added_to_the_placed_size_only(client):
    # left+right banded -> margin applies to the WIDTH twice; top banded -> HEIGHT once
    p = panel("A", 400, 700, bandedEdges=["left", "right", "top"])
    pl = result_for(nest(client, [p], {"edgeBandingMarginMm": 2}), WHITE)["sheets"][0]["placements"][0]
    assert (pl["widthMm"], pl["heightMm"]) == (404, 702)
    assert (pl["finishedWidthMm"], pl["finishedHeightMm"]) == (400, 700)
    default = result_for(nest(client, [p]), WHITE)["sheets"][0]["placements"][0]
    assert (default["widthMm"], default["heightMm"]) == (402, 701)  # default margin is 1 mm per banded edge


def test_rotated_placement_swaps_the_finished_size_too(client):
    pl = result_for(nest(client, [panel("A", 1000, 2000, WHITE)]), WHITE)["sheets"][0]["placements"][0]
    assert pl["rotated"] and (pl["finishedWidthMm"], pl["finishedHeightMm"]) == (2000, 1000)


def test_hardware_rows_are_never_nested(client):
    body = nest(client, [panel("Leg", 50, 100, isLeg=True), panel("A", 400, 700)])
    assert sum(len(s["placements"]) for r in body["results"] for s in r["sheets"]) == 1


def test_thicknesses_nest_on_separate_stock(client):
    body = nest(client, [panel("A", 400, 700, WHITE), panel("B", 400, 700, "MDF Raw 18mm"), panel("C", 400, 700, "MDF Raw 25mm", thickness=25)])
    assert {(r["material"], r["thicknessMm"]) for r in body["results"]} == {(WHITE, 18), ("MDF Raw 18mm", 18), ("MDF Raw 25mm", 25)}
    assert all(len(r["sheets"]) == 1 for r in body["results"])


def test_summary_cost_uses_the_catalog_price(client, catalog):
    price = next(m.price_per_sheet for m in catalog if m.name == WHITE)
    body = nest(client, [panel(f"p{i}", 2400, 1200) for i in range(3)])  # one panel fills a sheet
    assert body["summary"]["totals"]["sheetsUsed"] == 3
    assert body["summary"]["totals"]["totalCost"] == pytest.approx(3 * price)


def test_bom_inside_the_response_matches_the_bom_endpoint(client):
    panels = [panel(f"p{i}", 400, 700) for i in range(4)]
    assert nest(client, panels)["bom"] == client.post("/v1/bom", json={"panels": panels}).json()
