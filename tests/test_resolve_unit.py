"""Resolver (snap.js port): geometry helpers, rounding, ordering, and robustness on arbitrary graphs.
(Equality with the real JS resolver is in test_golden.py [resolved-*] and test_resolve_differential.py.)"""
import json
import math
import random

import pytest

from app.schemas.panels import PanelSet, Rotation3
from app.services.geometry import get_aligned_axis
from app.services.resolve import js_round, resolve_constraints
from tests.test_resolve_differential import random_graph


def rot(x=0, y=0, z=0):
    return Rotation3(x=x, y=y, z=z)


def node(id, w=100, h=100, **kw):
    return {"id": id, "name": id, "material": "m", "width": w, "height": h, "thickness": 18, **kw}


def resolve(*nodes):
    return {r["id"]: r for r in resolve_constraints(PanelSet.model_validate({"panels": list(nodes)}).panels)}


# ------------------------------------------------------------------ geometry
@pytest.mark.parametrize("face,expected", [
    ("right", ("x", 1)), ("left", ("x", -1)), ("top", ("y", 1)), ("bottom", ("y", -1)),
    ("front", ("z", 1)), ("back", ("z", -1)),
])
def test_unrotated_faces_point_along_their_axes(face, expected):
    assert get_aligned_axis(rot(), face) == expected


def test_quarter_turns_keep_every_face_aligned_and_opposites_opposite():
    for x in (0, 90, 180, 270):
        for y in (0, 90, 180, 270):
            for z in (0, 90, 180, 270):
                r = rot(x, y, z)
                for a, b in (("right", "left"), ("top", "bottom"), ("front", "back")):
                    fa, fb = get_aligned_axis(r, a), get_aligned_axis(r, b)
                    assert fa and fb and fa[0] == fb[0] and fa[1] == -fb[1]


def test_rotation_about_y_moves_the_thickness_axis_to_x():
    assert get_aligned_axis(rot(y=90), "front") == ("x", 1)
    assert get_aligned_axis(rot(y=90), "right") == ("z", -1)


@pytest.mark.parametrize("deg,aligned", [(0, True), (10, True), (11, True), (12, False), (45, False), (78, False), (79, True), (80, True), (90, True)])
def test_alignment_tolerance_is_about_11_5_degrees_either_side_of_a_quarter_turn(deg, aligned):
    assert (get_aligned_axis(rot(z=deg), "right") is not None) is aligned


def test_unknown_or_missing_face_is_not_aligned():
    assert get_aligned_axis(rot(), "sideways") is None and get_aligned_axis(rot(), None) is None
    assert get_aligned_axis(None, "top") == ("y", 1)


# ------------------------------------------------------------------ JS Math.round
@pytest.mark.parametrize("x,expected", [(30.5, 31), (2.5, 3), (-2.5, -2), (0.49, 0), (-0.5, 0), (54.0, 54), (1.5, 2)])
def test_js_round_halves_go_up(x, expected):
    assert js_round(x) == expected


# ------------------------------------------------------------------ behaviour
def spans(field, a, b, **kw):
    return {"type": "spansBetween", "field": field, "from": a, "to": b, **kw}


def test_unconstrained_panels_just_add_offset_to_base():
    r = resolve(node("a", basePosition={"x": 1, "y": 2, "z": 3}, offset={"x": 10, "y": 20, "z": 30}))["a"]
    assert r["position"] == {"x": 11, "y": 22, "z": 33} and r["warnings"] == [] and not any(r["lockedFields"].values())


def test_thickness_axis_is_derived_from_rotation_when_absent():
    assert resolve(node("a", rotation={"x": 0, "y": 90, "z": 0}))["a"]["thicknessAxis"] == "x"
    assert resolve(node("a"))["a"]["thicknessAxis"] == "z"
    assert resolve(node("a", thicknessAxis="y"))["a"]["thicknessAxis"] == "y"


def test_span_sets_size_centres_the_panel_and_locks_the_field():
    wall = node("w", 1000, 600)
    s = node("s", constraints=[spans("width", {"node": "w", "face": "left"}, {"node": "w", "face": "right"})])
    r = resolve(wall, s)["s"]
    assert r["width"] == 1000 and r["position"]["x"] == 0 and r["lockedFields"]["width"] is True


def test_dependency_order_does_not_depend_on_array_order():
    chain = [node(f"n{i}", 200, 100) for i in range(5)]
    for i in range(1, 5):
        chain[i]["constraints"] = [spans("width", {"node": f"n{i - 1}", "face": "left"}, {"node": f"n{i - 1}", "face": "right", "offset": 20})]
    forward = resolve(*chain)
    backward = resolve(*reversed(chain))
    assert {k: v["width"] for k, v in forward.items()} == {k: v["width"] for k, v in backward.items()}
    assert forward["n4"]["width"] == 200 + 4 * 20  # each link adds its 20 mm face offset


def test_cycles_are_flagged_not_resolved_and_dependents_still_resolve():
    x = node("x", 300, 300, constraints=[spans("width", {"node": "y", "face": "left"}, {"node": "y", "face": "right"})])
    y = node("y", 300, 300, constraints=[spans("width", {"node": "x", "face": "left"}, {"node": "x", "face": "right"})])
    w = node("w", 50, 50, constraints=[spans("width", {"node": "x", "face": "left"}, {"node": "x", "face": "right"})])
    r = resolve(w, x, y)
    assert "circular" in r["x"]["warnings"][0] and "circular" in r["y"]["warnings"][0]
    assert r["x"]["width"] == 300 and r["w"]["warnings"] == [] and r["w"]["width"] == 300


def test_self_reference_is_a_cycle():
    z = node("z", constraints=[{"type": "attachedTo", "field": "positionX", "myFace": "left", "from": {"node": "z", "face": "right"}}])
    assert "circular" in resolve(z)["z"]["warnings"][0]


def test_overridden_constraints_are_ignored_everywhere():
    a = node("a", 1000, 600)
    b = node("b", 300, 300, constraints=[spans("width", {"node": "a", "face": "left"}, {"node": "a", "face": "right"}, overridden=True)])
    r = resolve(a, b)["b"]
    assert r["width"] == 300 and r["warnings"] == [] and r["lockedFields"]["width"] is False


def test_failed_constraint_leaves_values_untouched_and_does_not_stop_the_others():
    a = node("a", 1000, 600)
    b = node("b", 300, 300, constraints=[
        spans("width", {"node": "ghost", "face": "right"}, {"node": "a", "face": "right"}),
        spans("height", {"node": "a", "face": "bottom"}, {"node": "a", "face": "top"}),
    ])
    r = resolve(a, b)["b"]
    assert r["warnings"] == ['references missing panel "ghost"'] and r["width"] == 300 and r["height"] == 600


# ------------------------------------------------------------------ robustness on arbitrary (valid) graphs
@pytest.mark.parametrize("seed", range(6))
def test_never_raises_and_is_deterministic_and_pure(seed):
    rng = random.Random(seed)
    for _ in range(150):
        graph = random_graph(rng)
        before = json.dumps(graph, sort_keys=True)
        panels = PanelSet.model_validate({"panels": graph}).panels
        first = resolve_constraints(panels)
        assert json.dumps(first, sort_keys=True) == json.dumps(resolve_constraints(panels), sort_keys=True)
        assert json.dumps(graph, sort_keys=True) == before  # input untouched
        assert [r["id"] for r in first] == [p["id"] for p in graph]  # same order, same ids
        for r in first:
            assert all(math.isfinite(r[k]) for k in ("width", "height", "thickness"))
            assert all(math.isfinite(v) for v in r["position"].values())
            assert all(isinstance(w, str) and w for w in r["warnings"])
