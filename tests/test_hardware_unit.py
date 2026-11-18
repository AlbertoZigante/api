"""Unit tests of the hardware rules (phase 9a): every catalog boundary, the placement maths, the orchestration's
`unmatched` bookkeeping, determinism and the trust boundary of POST /v1/hardware-plan."""
import copy
import json

import pytest

from app.rules.hardware import (
    HINGE_CATALOG,
    RUNNER_CATALOG,
    hinge_count_for_height,
    place_along_line,
    place_fasteners_along_seam,
    select_hinge_hardware,
    select_panel_connector,
    select_runner_hardware,
)
from tests.golden_harness import GOLDEN, designs, load

P0, P1000 = {"x": 0.0, "y": 0.0, "z": 0.0}, {"x": 0.0, "y": 1000.0, "z": 0.0}


def hinge_joint(length=1000.0):
    return {"kind": "door_hinge", "lengthMm": length, "p1": P0, "p2": {"x": 0.0, "y": length, "z": 0.0}}


def slide_joint(length=400.0, clearance=21.0):
    j = {"kind": "drawer_slide", "lengthMm": length, "p1": P0, "p2": {"x": 0.0, "y": 0.0, "z": length}}
    if clearance is not None:
        j["clearanceMm"] = clearance
    return j


# ------------------------------------------------------------------ hinges
@pytest.mark.parametrize("height,count", [(1, 2), (900, 2), (900.01, 3), (1600, 3), (1600.01, 4), (2200, 4), (2200.01, 5)])
def test_hinge_count_boundaries(height, count):
    assert hinge_count_for_height(height) == count


@pytest.mark.parametrize("thickness,ok", [(15.99, False), (16, True), (18, True), (24, True), (24.01, False)])
def test_hinge_thickness_range(thickness, ok):
    assert (select_hinge_hardware(hinge_joint(), thickness) is not None) is ok


def test_hinge_first_catalog_match_and_wrong_kind():
    assert select_hinge_hardware(hinge_joint(), 18)["hardware"] is HINGE_CATALOG[0]
    assert select_hinge_hardware(slide_joint(), 18) is None


def test_hinge_inset_is_clamped_and_positions_are_symmetric():
    short = select_hinge_hardware(hinge_joint(400), 18)  # 10% = 40 -> clamped up to 80
    assert [p["y"] for p in short["positions"]] == [80.0, 320.0]
    tall = select_hinge_hardware(hinge_joint(2400), 18)  # 10% = 240 -> clamped down to 160; 5 hinges
    ys = [p["y"] for p in tall["positions"]]
    assert tall["count"] == 5 and ys[0] == 160 and ys[-1] == 2240 and ys == sorted(ys)
    assert ys[2] == pytest.approx(1200)


def test_place_along_line_single_point_is_the_midpoint_and_inset_cannot_cross():
    assert place_along_line(P0, P1000, 1, 80) == [{"x": 0.0, "y": 500.0, "z": 0.0}]
    two = place_along_line(P0, P1000, 2, 900)  # inset larger than half the line is capped just under the middle
    assert two[0]["y"] < two[1]["y"]


# ------------------------------------------------------------------ runners
@pytest.mark.parametrize("thickness,runner", [(10.99, "blum-legrabox-c"), (11, "blum-tandem-plus-blumotion-560h"),
                                              (16, "blum-tandem-plus-blumotion-560h"), (16.01, "blum-legrabox-c")])
def test_runner_model_by_side_thickness(thickness, runner):
    assert select_runner_hardware(slide_joint(), thickness)["hardware"]["id"] == runner


@pytest.mark.parametrize("clearance,ok", [(19.99, False), (20, True), (21, True), (22, True), (22.01, False)])
def test_runner_clearance_tolerance(clearance, ok):
    assert (select_runner_hardware(slide_joint(clearance=clearance), 18) is not None) is ok


def test_runner_without_measured_clearance_matches_on_thickness_only():
    assert select_runner_hardware(slide_joint(clearance=None), 18) is not None


@pytest.mark.parametrize("length,nominal", [(269.99, None), (270, 270), (349.99, 270), (350, 350), (399, 350), (5000, 600)])
def test_runner_nominal_length_is_the_largest_that_fits(length, nominal):
    sel = select_runner_hardware(slide_joint(length=length), 18)  # 18 mm side -> LEGRABOX (no 300 / 650)
    assert (sel["nominalLengthMm"] if sel else None) == nominal


def test_tandem_has_its_own_nominal_lengths():
    assert select_runner_hardware(slide_joint(length=320), 12)["nominalLengthMm"] == 300
    assert select_runner_hardware(slide_joint(length=700), 12)["nominalLengthMm"] == 650
    assert RUNNER_CATALOG[0]["nominalLengthsMm"][-1] == 650


# ------------------------------------------------------------------ connectors
def seam(length):
    return {"p1": P0, "p2": {"x": 0.0, "y": 0.0, "z": length}, "lengthMm": length}


@pytest.mark.parametrize("length,count", [(100, 1), (101, 2), (250, 2), (400, 3), (400.01, 4), (700, 5)])
def test_fastener_count_for_seam_length(length, count):
    assert len(place_fasteners_along_seam(seam(length), 50, 150)) == count


def test_fasteners_are_inset_and_evenly_spaced():
    zs = [p["z"] for p in place_fasteners_along_seam(seam(500), 50, 150)]
    assert zs == pytest.approx([50.0, 50 + 400 / 3, 50 + 800 / 3, 450.0])


def test_short_seam_gets_one_centred_fastener():
    assert place_fasteners_along_seam(seam(80), 50, 150) == [{"x": 0.0, "y": 0.0, "z": 40.0}]


@pytest.mark.parametrize("jtype,thickness,ok", [("corner_butt", 16, True), ("t_butt", 18, True), ("t_butt", 15.99, False),
                                                ("face_to_face", 18, False), ("edge_to_edge", 18, False),
                                                ("near_contact", 18, False)])
def test_connector_by_joint_type_and_thickness(jtype, thickness, ok):
    assert (select_panel_connector({"type": jtype}, seam(300), thickness) is not None) is ok


# ------------------------------------------------------------------ the whole plan, through the endpoint
HAS_HARDWARE = designs("hardware")


def raw(design):
    return {"panels": load(design, "raw")}


def test_goldens_exist_for_the_designs_with_hardware():
    assert len(HAS_HARDWARE) >= 15


@pytest.mark.parametrize("design", HAS_HARDWARE)
def test_plan_is_deterministic_and_summary_is_consistent(client, design):
    first = client.post("/v1/hardware-plan", json=raw(design)).json()
    assert client.post("/v1/hardware-plan", json=raw(design)).json() == first
    s = first["summary"]
    assert s["hingeCount"] == len(first["hinges"]) and s["runnerCount"] == len(first["runners"])
    assert s["totalHingeUnits"] == sum(h["count"] for h in first["hinges"])
    assert s["fastenerJointCount"] == len(first["fasteners"])
    assert s["totalFastenerCount"] == sum(len(f["positions"]) for f in first["fasteners"])
    assert s["unmatchedCount"] == len(first["unmatched"])
    assert "generatedAt" not in json.dumps(first)
    for items, prefix in ((first["hinges"], "HG"), (first["runners"], "RN"), (first["fasteners"], "FS")):
        assert [i["displayId"] for i in items] == [f"{prefix}{n:03d}" for n in range(1, len(items) + 1)]


def test_full_cabinet_gets_hinges_runners_and_fasteners(client):
    drawers = client.post("/v1/hardware-plan", json=raw("box_drawers_plinth")).json()
    assert drawers["summary"]["runnerCount"] == 4 and drawers["summary"]["fastenerJointCount"] > 0
    door = client.post("/v1/hardware-plan", json=raw("box_door_left")).json()
    assert door["summary"]["hingeCount"] == 1 and door["hinges"][0]["side"] == "left"
    assert client.post("/v1/hardware-plan", json=raw("box_tall_door")).json()["hinges"][0]["count"] == 4


def test_empty_design_is_an_empty_plan(client):
    r = client.post("/v1/hardware-plan", json={"panels": []})
    assert r.status_code == 200
    assert r.json() == {"summary": {"hingeCount": 0, "totalHingeUnits": 0, "runnerCount": 0, "fastenerJointCount": 0,
                                    "totalFastenerCount": 0, "unmatchedCount": 0},
                        "hinges": [], "runners": [], "fasteners": [], "unmatched": []}


def test_too_thin_door_and_drawer_side_are_reported_not_dropped(client):
    body = raw("box_drawers_plinth")
    for p in body["panels"]:
        if p.get("isDrawerBoxPanel"):
            p["thickness"] = 8  # no runner fits an 8 mm side
    out = client.post("/v1/hardware-plan", json=body).json()
    assert out["runners"] == []
    assert sorted(u["kind"] for u in out["unmatched"] if u["kind"] == "runner") == ["runner"] * 4
    assert all("jointId" not in u for u in out["unmatched"] if u["kind"] == "runner")

    door = raw("box_door_left")
    for p in door["panels"]:
        if p.get("isDoor"):
            p["thickness"] = 30
    out = client.post("/v1/hardware-plan", json=door).json()
    assert out["hinges"] == [] and [u["kind"] for u in out["unmatched"] if u["kind"] == "hinge"] == ["hinge"]


def test_unmatchable_carcass_joints_are_unmatched_fasteners(client, monkeypatch):
    from app.rules.hardware import PANEL_CONNECTOR_CATALOG

    monkeypatch.setitem(PANEL_CONNECTOR_CATALOG[0], "minPanelThicknessMm", 30)  # nothing fits an 18 mm panel now
    body = raw("box_plain")
    out = client.post("/v1/hardware-plan", json=body).json()
    assert out["fasteners"] == []
    assert out["unmatched"] and all(u["kind"] == "fastener" and u["jointId"] and u["jointType"] for u in out["unmatched"])


def test_client_cannot_inject_joints_or_hardware_or_positions(client):
    clean = client.post("/v1/hardware-plan", json=raw("box_drawers_plinth")).json()
    body = copy.deepcopy(raw("box_drawers_plinth"))
    body["joints"] = [{"id": "evil", "type": "corner_butt"}]
    body["hardware"] = [{"id": "evil"}]
    body["featureJoints"] = [{"id": "evil", "kind": "door_hinge"}]
    body["panels"][0]["relations"] = [{"kind": "joint", "id": "evil"}]
    r = client.post("/v1/hardware-plan", json=body)
    assert r.status_code == 200 and r.json() == clean and "evil" not in r.text


def test_hardware_plan_validates_input_like_every_engine_route(client):
    bad = raw("box_plain")
    bad["panels"][0]["width"] = -5
    assert client.post("/v1/hardware-plan", json=bad).status_code == 422
    dup = raw("box_plain")
    dup["panels"].append(dup["panels"][0])
    assert client.post("/v1/hardware-plan", json=dup).status_code == 422
    assert client.post("/v1/hardware-plan", json={"panels": []}).headers["x-rules-version"]


def test_catalog_entries_are_not_shared_between_responses(client):
    """Responses must not alias the module-level catalog (a mutation would corrupt every later request)."""
    a = client.post("/v1/hardware-plan", json=raw("box_door_left")).json()
    a["hinges"][0]["hardware"]["minDoorThicknessMm"] = 999
    b = client.post("/v1/hardware-plan", json=raw("box_door_left")).json()
    assert b["hinges"][0]["hardware"]["minDoorThicknessMm"] == 16
    assert (GOLDEN / "box_door_left" / "hardware.json").is_file()
