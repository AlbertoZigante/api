"""DIFFERENTIAL TESTS for the assembly planner (phase 9b), against the REAL JS (engine/assembly + ergonomics).

Cabinets with carcass panels named like the modeller names them (Top / Bottom / Back / Shelf / Divider / Plinth),
0-3 drawers (identical ones included, so the x N grouping is hit), doors, a plinth frame, random piece codes
(mixed case: the ICU `localeCompare` tie-breaks matter) and some deliberately unattached panels, through
buildAssemblySequence + buildAssemblyPlan and assembly sequence / plan of the Python port, compared field by field.
Plus `localeCompare` itself, fuzzed against node's Intl. Needs node + `npm ci` in the modeller (MODELLER_DIR).
"""
import json
import os
import random
import shutil
import subprocess
from collections import Counter

import pytest

from app.rules.assembly import build_assembly_plan, build_assembly_sequence
from app.rules.collation import locale_compare
from app.schemas.panels import PanelSet
from app.services.resolve import resolve_constraints
from tests.golden_harness import _strip_additive, deep_diff
from tests.test_joints_differential import FUZZ_N, MODELLER, RUNNER, random_layout, run_js

COLLATE = MODELLER / "scripts" / "golden" / "collate-runner.mjs"

pytestmark = pytest.mark.skipif(
    not (shutil.which("node") and RUNNER.is_file() and COLLATE.is_file() and (MODELLER / "node_modules" / "three").is_dir()),
    reason="needs node + the modeller repo with its dependencies installed (MODELLER_DIR=<path>; run `npm ci` there)",
)


def test_locale_compare_matches_icu():
    rng = random.Random(7)
    alphabet = "abcABC012 -_.XyZ9"
    pairs = [["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6))),
              "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))] for _ in range(4000)]
    pairs += [["PC1", "pc1"], ["a", "B"], ["B", "a"], ["Left", "back"], ["A1", "A10"], ["A-1", "A1"], ["", "a"], ["a", ""]]
    done = subprocess.run(["node", str(COLLATE)], input=json.dumps(pairs).encode(), capture_output=True, cwd=MODELLER, timeout=120)
    assert done.returncode == 0, done.stderr.decode()[:500]
    wrong = [(p, e, locale_compare(*p)) for p, e in zip(pairs, json.loads(done.stdout), strict=True) if locale_compare(*p) != e]
    assert not wrong, f"{len(wrong)} differ, e.g. {wrong[:5]}"


NAMES = {"top": ["Top", "Top Panel", "Roof"], "bottom": ["Bottom", "Base"], "back": ["Back", "Back Panel", "Rear"],
         "shelf": ["Shelf", "Fixed shelf", "Horizontal 1"], "vert": ["Divider", "Vertical Divider", "Partition"],
         "side": ["Left Side", "Right Side", "Side", "Panel", "Shelf Side"]}


def cabinet_layout(rng: random.Random) -> list[dict]:
    def node(pid, name, w, h, t, rot, pos, **extra):
        n = {"id": pid, "name": name, "material": rng.choice(["Melamine White 18mm", "Oak 18mm"]), "quantity": 1,
             "thicknessAxis": extra.pop("axis"), "width": w, "height": h, "thickness": t, "rotation": rot,
             "basePosition": pos, "offset": {"x": 0, "y": 0, "z": 0}, "constraints": [], "groupId": "g",
             "hidden": rng.random() < 0.03, **extra}
        code = rng.choice([None, None, f"{rng.choice('abAB')}{rng.randint(1, 30):02d}", f"PC-{pid}", ""])
        if code is not None:
            n["pieceCode"] = code
        return n

    half, depth = rng.choice([250, 291, 400]), rng.choice([300, 450, 600])
    height = rng.choice([500, 900, 1700, 2300])
    side = {"x": 0, "y": 90, "z": 0}
    flat = {"x": 90, "y": 0, "z": 0}
    nodes = [
        node("L", rng.choice(NAMES["side"]), depth, height, 18, side, {"x": -half - 9, "y": height / 2, "z": 0}, axis="x"),
        node("R", rng.choice(NAMES["side"]), depth, height, 18, side, {"x": half + 9, "y": height / 2, "z": 0}, axis="x"),
        node("T", rng.choice(NAMES["top"]), 2 * half + 36, depth, 18, flat, {"x": 0, "y": height + 9, "z": 0}, axis="y"),
    ]
    if rng.random() < 0.8:
        nodes.append(node("B", rng.choice(NAMES["bottom"]), 2 * half, depth, 18, flat, {"x": 0, "y": 9, "z": 0}, axis="y"))
    if rng.random() < 0.7:
        nodes.append(node("K", rng.choice(NAMES["back"]), 2 * half + 36, height, 8, {"x": 0, "y": 0, "z": 0},
                          {"x": 0, "y": height / 2, "z": -depth / 2 - 4}, axis="z"))
    for i in range(rng.randint(0, 2)):
        nodes.append(node(f"S{i}", rng.choice(NAMES["shelf"]), 2 * half, depth, 18, flat,
                          {"x": 0, "y": 200 + 250 * i, "z": 0}, axis="y"))
    if rng.random() < 0.3:
        nodes.append(node("V", rng.choice(NAMES["vert"]), depth, height - 36, 18, side,
                          {"x": rng.choice([-half / 2, 0, half / 2]), "y": height / 2, "z": 0}, axis="x"))
    if rng.random() < 0.4:  # plinth frame under the bottom: front board + two returns (sometimes with a gap: no contact)
        drop = rng.choice([0, 0, 120])  # a gap leaves the plinth touching nothing -> the 'bottom panel' fallback
        nodes.append(node("PF", "Plinth Front", 2 * half, 100, 18, {"x": 0, "y": 0, "z": 0}, {"x": 0, "y": -50 - drop, "z": depth / 2 - 41}, axis="z", isPlinthPanel=True))
        nodes.append(node("PL", "Plinth Side", depth - 100, 100, 18, side, {"x": -half + 9, "y": -50 - drop, "z": 0}, axis="x", isPlinthPanel=True))
        nodes.append(node("PR", "Plinth Side", depth - 100, 100, 18, side, {"x": half - 9, "y": -50 - drop, "z": 0}, axis="x", isPlinthPanel=True))
    identical = rng.random() < 0.5
    t0, gap0, len0 = rng.choice([12, 15, 16, 18]), rng.choice([21, 21, 20.5, 25]), rng.choice([300, 450, 650])
    for i in range(rng.randint(0, 3)):
        fid = f"F{i}"
        nodes.append(node(fid, "Drawer Front", 2 * half, 150, 18, {"x": 0, "y": 0, "z": 0},
                          {"x": 0, "y": 100 + 160 * i, "z": depth / 2 + 9}, axis="z", isDrawerFront=True, normalAxis="z",
                          boundaryIds={"left": "L", "right": "R"}))
        t = t0 if identical else rng.choice([12, 16, 18])
        gap = gap0 if identical else rng.choice([21, 22.5])
        length = len0 if identical else rng.choice([300, 450, 650])
        for role, sign in (("left", -1), ("right", 1)):
            nodes.append(node(f"{fid}{role[0]}", f"Drawer Box {role}", length, 120, t, side,
                              {"x": sign * (half - gap - t / 2), "y": 100 + 160 * i, "z": 0}, axis="x",
                              isDrawerBoxPanel=True, drawerBoxFrontId=fid, drawerBoxRole=role))
        if rng.random() < 0.8:
            nodes.append(node(f"{fid}k", "Drawer Box back", 2 * (half - gap) - 2 * t, 120, t, {"x": 0, "y": 0, "z": 0},
                              {"x": 0, "y": 100 + 160 * i, "z": -length / 2 + t / 2}, axis="z",
                              isDrawerBoxPanel=True, drawerBoxFrontId=fid, drawerBoxRole="back"))
        if rng.random() < 0.8:
            nodes.append(node(f"{fid}b", "Drawer Box bottom", 2 * (half - gap) - 2 * t, length, 8, flat,
                              {"x": 0, "y": 100 + 160 * i - 56, "z": 0}, axis="y",
                              isDrawerBoxPanel=True, drawerBoxFrontId=fid, drawerBoxRole="bottom"))
    for i in range(rng.randint(0, 2)):
        nodes.append(node(f"D{i}", "Door", half, rng.choice([300, 900, 1700]), 18, {"x": 0, "y": 0, "z": 0},
                          {"x": rng.choice([-half / 2, half / 2]), "y": 700, "z": depth / 2 + 30}, axis="z",
                          isDoor=True, hinge=rng.choice(["left", "right"]), normalAxis="z", doorSign=rng.choice([-1, 1]),
                          boundaryIds={"left": "L", "right": "R"}))
    if rng.random() < 0.15:  # a loose panel that touches nothing
        nodes.append(node("X", "Loose Panel", 300, 300, 18, flat, {"x": 3000, "y": 3000, "z": 3000}, axis="y"))
    rng.shuffle(nodes)
    return nodes


def _compare(graphs, js, label, seen: Counter) -> list[str]:
    problems = []
    for i, (graph, expected) in enumerate(zip(graphs, js, strict=True)):
        assert "ok" in expected, f"JS threw on {label} graph {i}: {expected}"
        panels = PanelSet.model_validate({"panels": graph}).panels
        resolved = resolve_constraints(panels)
        seq = build_assembly_sequence(panels, resolved)
        seq.pop("_resolved_by_id")
        plan = build_assembly_plan(panels, resolved)
        for name, actual in (("sequence", seq), ("assembly", plan)):
            diffs = deep_diff(_strip_additive(actual), expected["ok"][name], abs_tol=1e-6)  # phase-10 structured keys are additive
            if diffs:
                problems.append(f"{label} graph {i} {name}: {diffs[0]}  (+{len(diffs) - 1} more)\n{json.dumps(graph)[:500]}")
        for s in plan["steps"]:
            seen[f"stage:{s['stage']}"] += 1
            seen[f"kind:{s['kind']}"] += 1
            seen[f"phase:{s['phase']}"] += 1
            seen["repeat>1"] += s.get("repeatCount", 1) > 1
            seen["reposition"] += bool(s["requiresReposition"])
            seen["twoPerson"] += bool(s["ergonomics"]["twoPersonJob"])
            seen["prereq"] += bool(s["prerequisiteStepIds"])
            seen["complete"] += bool(s["subassemblyComplete"])
    return problems


def test_python_assembly_matches_the_js_on_cabinets():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261115")) + 3)
    graphs = [cabinet_layout(rng) for _ in range(max(FUZZ_N, 600))]
    seen: Counter = Counter()
    problems = _compare(graphs, run_js(graphs), "cabinet", seen)
    assert not problems, f"{len(problems)} differences\n" + "\n".join(problems[:3])
    for key in ["stage:doors", "stage:drawers", "stage:guides", "stage:plinth", "stage:carcass", "stage:integration",
                "kind:pre_install", "kind:fit_handle", "kind:join", "kind:integrate", "kind:unattached",
                "phase:closure", "phase:internal", "repeat>1", "reposition", "prereq", "complete"]:
        assert seen[key] > 5, (key, dict(seen))


def test_python_assembly_matches_the_js_on_random_layouts():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261115")) + 4)
    graphs = [random_layout(rng) for _ in range(FUZZ_N)]
    problems = _compare(graphs, run_js(graphs), "random", Counter())
    assert not problems, f"{len(problems)} differences\n" + "\n".join(problems[:3])
