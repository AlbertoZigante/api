"""DIFFERENTIAL TESTS for the hardware layer (phase 9a), against the REAL JS (3d_modeler/src/engine/hardware.js).

1. Selector fuzz: thousands of plain inputs aimed at every catalog boundary (thickness 15.99/16/24/24.01, clearance
   20/21/22/22.01, nominal lengths, hinge-count heights, seam lengths around the spacing steps) through the JS
   selectors (scripts/golden/hardware-runner.mjs) and the Python ones.
2. Whole-plan fuzz: the random layouts of the joints fuzz through buildHardwarePlan (engine-runner.mjs) and
   build_hardware_plan, compared field by field (the JS `generatedAt` is not part of the contract).

Needs node + the modeller repo with `npm ci` done (or MODELLER_DIR). Skipped otherwise. FUZZ_N / FUZZ_SEED as usual.
"""
import json
import os
import random
import shutil
import subprocess
from collections import Counter

import pytest

from app.rules.hardware import (
    place_fasteners_along_seam,
    select_hinge_hardware,
    select_panel_connector,
    select_runner_hardware,
)
from app.schemas.panels import PanelSet
from app.services.hardware import build_hardware_plan
from app.services.resolve import resolve_constraints
from tests.golden_harness import deep_diff
from tests.test_joints_differential import FUZZ_N, MODELLER, RUNNER, random_layout, run_js

HW_RUNNER = MODELLER / "scripts" / "golden" / "hardware-runner.mjs"

pytestmark = pytest.mark.skipif(
    not (shutil.which("node") and RUNNER.is_file() and HW_RUNNER.is_file() and (MODELLER / "node_modules" / "three").is_dir()),
    reason="needs node + the modeller repo with its dependencies installed (MODELLER_DIR=<path>; run `npm ci` there)",
)

THICKNESSES = [0, 8, 10.99, 11, 12, 15.99, 16, 16.01, 18, 19, 23.99, 24, 24.01, 25, 30]
CLEARANCES = [None, 0, 19.99, 20, 20.5, 21, 21.5, 22, 22.01, 25]
LENGTHS = [1, 80, 269.99, 270, 299.99, 300, 349.99, 350, 399.99, 400, 600, 649.99, 650, 651, 900, 900.01, 1600,
           1600.01, 2200, 2200.01, 3000]
SEAMS = [0, 10, 100, 100.01, 101, 150, 250, 250.01, 400, 400.01, 550, 700.5, 1200, 2400]
JOINT_TYPES = ["face_to_face", "corner_butt", "t_butt", "edge_to_edge", "near_contact"]


def run_selectors(calls: list[dict]) -> list[dict]:
    done = subprocess.run(["node", str(HW_RUNNER)], input=json.dumps(calls).encode("utf-8"), capture_output=True,
                          cwd=MODELLER, timeout=300)
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")[:2000]
    return json.loads(done.stdout.decode("utf-8"))


def _pt(rng: random.Random) -> dict:
    return {a: round(rng.uniform(-500, 2500), 3) for a in "xyz"}


def selector_cases(rng: random.Random, n: int) -> list[tuple[dict, object]]:
    """(js call, python result thunk) pairs."""
    cases = []
    for _ in range(n):
        kind = rng.choice(["hinge", "runner", "connector", "fasteners"])
        if kind == "hinge":
            p1, length = _pt(rng), rng.choice(LENGTHS)
            joint = {"kind": rng.choice(["door_hinge"] * 5 + ["drawer_slide"]), "lengthMm": length, "p1": p1,
                     "p2": {**p1, "y": p1["y"] + length}}
            t = rng.choice(THICKNESSES)
            cases.append(({"fn": "selectHingeHardware", "args": [joint, t]}, lambda j=joint, t=t: select_hinge_hardware(j, t)))
        elif kind == "runner":
            p1, length = _pt(rng), rng.choice(LENGTHS)
            joint = {"kind": rng.choice(["drawer_slide"] * 5 + ["door_hinge"]), "lengthMm": length, "p1": p1,
                     "p2": {**p1, "z": p1["z"] + length}}
            clearance = rng.choice(CLEARANCES)
            if clearance is not None:
                joint["clearanceMm"] = clearance
            t = rng.choice(THICKNESSES)
            cases.append(({"fn": "selectRunnerHardware", "args": [joint, t]}, lambda j=joint, t=t: select_runner_hardware(j, t)))
        else:
            p1, length = _pt(rng), rng.choice(SEAMS)
            seam = {"p1": p1, "p2": {**p1, "x": p1["x"] + length}, "lengthMm": length}
            if kind == "fasteners":
                off, spacing = rng.choice([(50, 150), (50, 150), (30, 100), (0, 150), (10, 37.5)])
                cases.append(({"fn": "placeFastenersAlongSeam", "args": [seam, off, spacing]},
                              lambda s=seam, o=off, sp=spacing: place_fasteners_along_seam(s, o, sp)))
            else:
                joint, t = {"type": rng.choice(JOINT_TYPES)}, rng.choice(THICKNESSES)
                cases.append(({"fn": "selectPanelConnector", "args": [joint, seam, t]},
                              lambda j=joint, s=seam, t=t: select_panel_connector(j, s, t)))
    return cases


def test_python_selectors_match_the_js_selectors_at_every_boundary():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261115")))
    cases = selector_cases(rng, max(FUZZ_N * 10, 4000))
    js = run_selectors([c for c, _ in cases])
    problems, outcomes = [], Counter()
    for (call, python), expected in zip(cases, js, strict=True):
        assert "ok" in expected, f"JS threw on {call}: {expected}"
        actual = python()
        outcomes[(call["fn"], "match" if actual is not None else "none")] += 1
        diffs = deep_diff(actual, expected["ok"], abs_tol=1e-6)
        if diffs:
            problems.append(f"{call['fn']} {json.dumps(call['args'])[:300]}: {diffs[0]}")
    assert not problems, f"{len(problems)} differences\n" + "\n".join(problems[:5])
    # the generator must reach both outcomes of every selector, or it proves nothing
    for fn in ("selectHingeHardware", "selectRunnerHardware", "selectPanelConnector"):
        assert outcomes[(fn, "match")] > 50 and outcomes[(fn, "none")] > 50, dict(outcomes)


def furniture_layout(rng: random.Random) -> list[dict]:
    """A carcass with two sides, 0-3 drawers (box sides at a random gap / thickness / depth: the runner rules
    only fire when these line up) and 0-2 doors of random thickness, with piece codes present / absent / empty."""
    def node(pid, w, h, t, rot, pos, **extra):
        axis = {"x": "x", "y": "y", "z": "z"}[extra.pop("axis")]
        n = {"id": pid, "name": f"Name {pid}", "material": "Melamine White 18mm", "quantity": 1, "thicknessAxis": axis,
             "width": w, "height": h, "thickness": t, "rotation": rot, "basePosition": pos,
             "offset": {"x": 0, "y": 0, "z": 0}, "constraints": [], "groupId": "g", "hidden": False, **extra}
        code = rng.choice([None, None, f"PC{pid}", ""])
        if code is not None:
            n["pieceCode"] = code
        return n

    half = rng.choice([250, 291, 400])
    depth, height = rng.choice([300, 450, 600, 700]), rng.choice([500, 900, 1700, 2300])
    side_rot = {"x": 0, "y": 90, "z": 0}
    left = node("L", depth, height, 18, side_rot, {"x": -half - 9, "y": height / 2, "z": 0}, axis="x")
    right = node("R", depth, height, 18, side_rot, {"x": half + 9, "y": height / 2, "z": 0}, axis="x")
    top = node("T", 2 * half, depth, 18, {"x": 90, "y": 0, "z": 0}, {"x": 0, "y": height + 9, "z": 0}, axis="y")
    nodes = [left, right, top]
    for i in range(rng.randint(0, 3)):
        front_id = f"F{i}"
        nodes.append(node(front_id, 2 * half, 150, 18, {"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 100 + 160 * i, "z": depth / 2 + 9},
                          axis="z", isDrawerFront=True, normalAxis="z", boundaryIds={"left": "L", "right": "R"}))
        for role, sign in (("left", -1), ("right", 1)):
            t = rng.choice([8, 12, 15.99, 16, 16.01, 18, 19, 20])
            gap = rng.choice([19.99, 20, 21, 21, 21, 22, 22.01, 25])
            length = rng.choice([250, 269.99, 270, 300, 349.99, 350, 450, 650, 651])
            x = sign * (half - gap - t / 2)
            nodes.append(node(f"{front_id}{role[0]}", length, 120, t, side_rot, {"x": x, "y": 100 + 160 * i, "z": 0}, axis="x",
                              isDrawerBoxPanel=True, drawerBoxFrontId=front_id, drawerBoxRole=role))
    for i in range(rng.randint(0, 2)):
        nodes.append(node(f"D{i}", half, rng.choice([300, 900, 1600, 1601, 2200, 2201]), rng.choice([15.99, 16, 18, 24, 24.01]),
                          {"x": 0, "y": 0, "z": 0}, {"x": rng.choice([-half / 2, half / 2]), "y": 700, "z": depth / 2 + 30},
                          axis="z", isDoor=True, hinge=rng.choice(["left", "right"]), normalAxis="z",
                          boundaryIds={"left": "L", "right": rng.choice(["R", "R", "ghost"])}))
    rng.shuffle(nodes)
    return nodes


def test_python_hardware_plan_matches_the_js_plan_on_furniture_layouts():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261115")) + 2)
    graphs = [furniture_layout(rng) for _ in range(max(FUZZ_N, 400))]
    js = run_js(graphs)
    problems, seen = [], Counter()
    for i, (graph, expected) in enumerate(zip(graphs, js, strict=True)):
        assert "ok" in expected, f"JS threw on graph {i}: {expected}"
        panels = PanelSet.model_validate({"panels": graph}).panels
        actual = build_hardware_plan(panels, resolve_constraints(panels))
        diffs = deep_diff(actual, expected["ok"]["hardware"], abs_tol=1e-6)
        if diffs:
            problems.append(f"graph {i}: {diffs[0]}   (+{len(diffs) - 1} more)\n{json.dumps(graph)[:600]}")
        for key in ("hinges", "runners", "fasteners", "unmatched"):
            seen[key] += len(actual[key])
        for u in actual["unmatched"]:
            seen["unmatched-" + u["kind"]] += 1
        seen["runner-tandem"] += sum(r["hardware"]["id"].startswith("blum-tandem") for r in actual["runners"])
        seen["runner-legrabox"] += sum(r["hardware"]["id"].startswith("blum-legrabox") for r in actual["runners"])
    assert not problems, f"{len(problems)} of {len(graphs)} graphs differ\n" + "\n".join(problems[:3])
    needed = ["hinges", "runner-tandem", "runner-legrabox", "unmatched-runner", "unmatched-hinge", "fasteners"]
    assert all(seen[k] > 20 for k in needed), dict(seen)


def test_python_hardware_plan_matches_the_js_plan_on_random_layouts():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261115")) + 1)
    graphs = [random_layout(rng) for _ in range(FUZZ_N)]
    js = run_js(graphs)
    problems, seen = [], Counter()
    for i, (graph, expected) in enumerate(zip(graphs, js, strict=True)):
        assert "ok" in expected, f"JS threw on graph {i}: {expected}"
        panels = PanelSet.model_validate({"panels": graph}).panels
        actual = build_hardware_plan(panels, resolve_constraints(panels))
        diffs = deep_diff(actual, expected["ok"]["hardware"], abs_tol=1e-6)
        if diffs:
            problems.append(f"graph {i}: {diffs[0]}   (+{len(diffs) - 1} more)\n{json.dumps(graph)[:600]}")
        for key in ("hinges", "runners", "fasteners", "unmatched"):
            seen[key] += len(actual[key])
    assert not problems, f"{len(problems)} of {FUZZ_N} graphs differ\n" + "\n".join(problems[:3])
    assert all(seen[k] > 0 for k in ("hinges", "fasteners", "unmatched")), dict(seen)
