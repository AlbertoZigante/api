"""DIFFERENTIAL FUZZ for joint detection: random layouts through the REAL JS (resolveConstraints + detectJoints +
detectFeatureJoints) and through the Python port; every number, id, type and flag must agree.

Layouts are built to hit the JS thresholds on purpose — panels placed exactly at, just inside and just outside
the contact epsilon (0.05), near-contact tolerance (3), minimum contact length (5), collision depth (1) and the
corner/T boundary tolerance (0.5) — plus random door / drawer flags with missing, wrong and dangling references.

Needs `node` + the modeller repo next to this one with `npm ci` done (or MODELLER_DIR). Skipped otherwise.
FUZZ_N=20000 FUZZ_SEED=7 for a long run.
"""
import json
import os
import random
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from app.schemas.panels import PanelSet
from app.services.geometry import get_aligned_axis, world_half_extents
from app.services.joints import detect_feature_joints, detect_joints
from app.services.resolve import resolve_constraints
from tests.golden_harness import deep_diff

MODELLER = Path(os.environ.get("MODELLER_DIR", Path(__file__).resolve().parents[2] / "3d_modeler"))
RUNNER = MODELLER / "scripts" / "golden" / "engine-runner.mjs"
FUZZ_N = int(os.environ.get("FUZZ_N", "400"))

pytestmark = pytest.mark.skipif(
    not (shutil.which("node") and RUNNER.is_file() and (MODELLER / "node_modules" / "three").is_dir()),
    reason="needs node + the modeller repo with its dependencies installed (MODELLER_DIR=<path>; run `npm ci` there)",
)

ROTATIONS = [(0, 0, 0), (0, 90, 0), (90, 0, 0), (0, 0, 90), (90, 90, 0), (0, 90, 90), (90, 0, 90), (0, 180, 0),
             (0, -90, 0), (0, 0, 5), (0, 0, 45)]
DIMS = [18, 18, 100, 300, 400, 600, 800.5]
# face-to-face distance along the contact axis (negative = the panels overlap by that much)
GAPS = [0, 0, 0, 0.049, 0.05, 0.051, 1, 2.9, 3, 3.1, 5, -0.049, -0.05, -0.051, -0.5, -0.99, -1, -1.01, -2, 10]
CONTACT_MARGINS = [0.5, 4.9, 5, 5.1, 20]  # how little footprint two panels share along a non-contact axis
EDGE_TWEAKS = [0, 0.4, 0.5, 0.6, -0.4, -0.5, -0.6]  # around the corner/T boundary tolerance


def _node(pid: str, rng: random.Random) -> dict:
    rot = rng.choice(ROTATIONS)
    rotation = {"x": rot[0], "y": rot[1], "z": rot[2]}
    w, h = rng.choice(DIMS), rng.choice(DIMS)
    aligned = get_aligned_axis(type("R", (), rotation)(), "front")
    axis = aligned[0] if aligned else "z"
    if rng.random() < 0.08:
        axis = rng.choice("xyz")  # deliberately inconsistent: thicknessAxis is passed through, not recomputed
    return {
        "id": pid, "name": pid, "material": "Melamine White 18mm", "quantity": 1, "thicknessAxis": axis,
        "width": w, "height": h, "thickness": 18, "rotation": rotation,
        "basePosition": {"x": 0, "y": 0, "z": 0}, "offset": {"x": 0, "y": 0, "z": 0},
        "constraints": [], "groupId": rng.choice([None, None, "g1", "g2"]), "hidden": rng.random() < 0.08,
    }


def _geom(n: dict) -> tuple[dict, dict]:
    half = world_half_extents({"rotation": n["rotation"], "width": n["width"], "height": n["height"], "thickness": 18})
    return dict(n["basePosition"]), half


def random_layout(rng: random.Random) -> list[dict]:
    count = rng.randint(2, 10)
    nodes = [_node("p0", rng)]
    nodes[0]["basePosition"] = {a: round(rng.uniform(-200, 200), 3) for a in "xyz"}
    for i in range(1, count):
        new = _node(f"p{i}", rng)
        anchor = rng.choice(nodes)
        a_pos, a_half = _geom(anchor)
        n_half = _geom(new)[1]
        axis, sign = rng.choice("xyz"), rng.choice([-1, 1])
        pos = {}
        for a in "xyz":
            if a == axis:
                face = a_pos[a] + sign * a_half[a]
                pos[a] = face + sign * (rng.choice(GAPS) + n_half[a])
            else:
                kind = rng.random()
                if kind < 0.25:
                    off = 0.0
                elif kind < 0.55:  # share only a thin strip of footprint
                    off = rng.choice([-1, 1]) * (a_half[a] + n_half[a] - rng.choice(CONTACT_MARGINS))
                elif kind < 0.8:  # flush with an edge, give or take the boundary tolerance
                    off = rng.choice([-1, 1]) * (a_half[a] - n_half[a] + rng.choice(EDGE_TWEAKS))
                else:
                    off = rng.uniform(-150, 150)
                pos[a] = a_pos[a] + off
        new["basePosition"] = {a: round(pos[a], 6) for a in "xyz"}
        nodes.append(new)

    ids = [n["id"] for n in nodes]
    fronts: list[str] = []
    for n in nodes:
        roll = rng.random()
        if roll < 0.18:
            n.update({"isDoor": True, "hinge": rng.choice(["left", "right", "right", None]),
                      "normalAxis": rng.choice(["x", "y", "z", "z", "x"]),
                      "boundaryIds": rng.choice([{}, {"left": rng.choice(ids + ["ghost"]), "right": rng.choice(ids)},
                                                 {"right": rng.choice(ids)}, None])})
        elif roll < 0.32:
            n.update({"isDrawerFront": True, "normalAxis": rng.choice(["x", "z", "z", "y"]),
                      "boundaryIds": rng.choice([{"left": rng.choice(ids), "right": rng.choice(ids)},
                                                 {"left": rng.choice(ids + ["ghost"])}, {}, None])})
            fronts.append(n["id"])
        elif roll < 0.5 and fronts:
            n.update({"isDrawerBoxPanel": True, "drawerBoxFrontId": rng.choice(fronts + ["ghost"]),
                      "drawerBoxRole": rng.choice(["left", "right", "left", "right", "bottom"])})
    for n in nodes:  # JSON has no `undefined`: absent keys, not nulls (the modeller never sends null here)
        for k in [k for k, v in n.items() if v is None and k in ("hinge", "boundaryIds")]:
            del n[k]
    rng.shuffle(nodes)
    return nodes


def run_js(graphs: list[list[dict]]) -> list[dict]:
    # Bytes in/out, UTF-8 explicit (text=True would use the platform code page — cp1252 on Windows).
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(graphs).encode("utf-8"), capture_output=True,
                          cwd=MODELLER, timeout=600)
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")[:2000]
    return json.loads(done.stdout.decode("utf-8"))


def test_python_joints_match_the_js_joints_on_random_layouts():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261115")))
    graphs = [random_layout(rng) for _ in range(FUZZ_N)]
    js = run_js(graphs)
    problems: list[str] = []
    kinds: Counter = Counter()
    seen = Counter()
    for i, (graph, expected) in enumerate(zip(graphs, js, strict=True)):
        assert "ok" in expected, f"JS threw on graph {i}: {expected} (generator produced an unsupported shape)"
        panels = PanelSet.model_validate({"panels": graph}).panels
        resolved = resolve_constraints(panels)
        actual = {"resolved": resolved, "joints": detect_joints(resolved), "featureJoints": detect_feature_joints(panels, resolved)}
        diffs = deep_diff(actual, expected["ok"], abs_tol=1e-6)
        if diffs:
            kinds.update(re.sub(r"\[\d+\]", "[]", d.split(":")[0]) for d in diffs)
            problems.append(f"graph {i}: {diffs[0]}   (+{len(diffs) - 1} more)\n{json.dumps(graph)[:700]}")
        for j in expected["ok"]["joints"]["joints"]:
            seen[j["type"]] += 1
        seen["collision"] += len(expected["ok"]["joints"]["collisions"])
        seen["featureJoint"] += len(expected["ok"]["featureJoints"])
    assert not problems, (
        f"{len(problems)} of {FUZZ_N} graphs differ. Most common differing fields: {kinds.most_common(5)}\n"
        + "\n".join(problems[:3])
    )
    # the generator must really reach every kind of result, or this test proves nothing
    needed = ["face_to_face", "corner_butt", "t_butt", "edge_to_edge", "near_contact", "collision", "featureJoint"]
    assert all(seen[k] >= FUZZ_N * 0.02 for k in needed), dict(seen)
