"""BOM units, rounding and edge-banding rules, with hand-computed expectations.
(The cross-check against the original JS engine lives in test_golden.py.)"""
import pytest

from tests.conftest import panel


def bom(client, *panels):
    r = client.post("/v1/bom", json={"panels": list(panels)})
    assert r.status_code == 200
    return r.json()


def test_area_is_mm2_to_m2_without_rounding(client):
    row = bom(client, panel("A", 333.3, 777.7))["rows"][0]
    assert row["unitAreaM2"] == pytest.approx(333.3 * 777.7 / 1e6, abs=1e-12)
    assert row["areaM2"] == row["unitAreaM2"] * row["quantity"]


@pytest.mark.parametrize(
    "edges,expected_mm",
    [
        ([], 0),
        (["left"], 700), (["right"], 700),        # left/right edges run the full HEIGHT
        (["top"], 400), (["bottom"], 400),        # top/bottom edges run the full WIDTH
        (["left", "right", "top", "bottom"], 2 * 700 + 2 * 400),
        (["left", "top"], 700 + 400),
        (["nonsense"], 0),                        # unknown face contributes nothing
    ],
)
def test_banding_length_per_edge(client, edges, expected_mm):
    row = bom(client, panel("A", 400, 700, bandedEdges=edges))["rows"][0]
    assert row["unitBandingLengthM"] == pytest.approx(expected_mm / 1000)


def test_banding_scales_with_quantity_and_costs_use_material_price(client):
    # Melamine White 18mm: edgeBandingPricePerM = 1.20 (catalog)
    row = bom(client, panel("A", 400, 700, bandedEdges=["left"]), panel("B", 400, 700, bandedEdges=["left"]))["rows"][0]
    assert row["quantity"] == 2
    assert row["bandingLengthM"] == pytest.approx(1.4)
    assert row["bandingCost"] == pytest.approx(1.4 * 1.2)


def test_unknown_material_has_zero_banding_cost(client):
    row = bom(client, panel("A", 400, 700, "Nope", bandedEdges=["left"]))["rows"][0]
    assert row["bandingCost"] == 0 and row["bandingLengthM"] == pytest.approx(0.7)


def test_edges_label(client):
    assert bom(client, panel("A", 1, 1))["rows"][0]["bandedEdgesLabel"] == "—"
    assert bom(client, panel("A", 100, 200, bandedEdges=["left", "right"]))["rows"][0]["bandedEdgesLabel"] == "L,R"


def test_different_banding_never_merges(client):
    rows = bom(client, panel("A", 400, 700, bandedEdges=["left"]), panel("B", 400, 700))["rows"]
    assert len(rows) == 2


def test_legs_are_flagged_as_hardware(client):
    rows = bom(client, panel("Leg", 50, 100, isLeg=True), panel("A", 400, 700))["rows"]
    assert {r["label"]: r["isHardware"] for r in rows}["Leg"] is True
    assert [r["isHardware"] for r in rows if r["label"] == "A"] == [False]


def test_rows_sorted_by_label(client):
    labels = [r["label"] for r in bom(client, panel("Zeta", 1, 1), panel("Alpha", 2, 2), panel("Mid", 3, 3))["rows"]]
    assert labels == sorted(labels)


def test_empty_panel_list(client):
    assert bom(client) == {"rows": [], "materialSummary": []}


def test_material_summary_groups_by_material_and_thickness(client):
    s = bom(client, panel("A", 1000, 1000), panel("B", 1000, 1000, thickness=19), panel("C", 500, 500))["materialSummary"]
    by = {(x["material"], x["thickness"]): x for x in s}
    assert by[("Melamine White 18mm", 18)]["quantity"] == 2
    assert by[("Melamine White 18mm", 18)]["areaM2"] == pytest.approx(1.25)
    assert by[("Melamine White 18mm", 19)]["quantity"] == 1
