"""DIFFERENTIAL FUZZ: random constraint graphs through the REAL JS resolver (modeller snap.js) and the Python
port; every number, flag and warning text must agree. This is what proves the port beyond the frozen goldens:
it covers all four constraint types, cycles, dangling references, bad faces, angled panels (including the 11.5
degree alignment boundary), literal anchors and ordering — in combinations nobody wrote by hand.

Needs `node` and the modeller repo next to this one with `npm ci` done (3d_modeler/scripts/golden/resolve-runner.mjs),
or MODELLER_DIR=<path>. Skipped otherwise (e.g. CI without the modeller checkout). FUZZ_N=5000 for a long run.
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
from app.services.resolve import resolve_constraints
from tests.golden_harness import deep_diff

MODELLER = Path(os.environ.get("MODELLER_DIR", Path(__file__).resolve().parents[2] / "3d_modeler"))
RUNNER = MODELLER / "scripts" / "golden" / "resolve-runner.mjs"
FUZZ_N = int(os.environ.get("FUZZ_N", "400"))

pytestmark = pytest.mark.skipif(
    not (shutil.which("node") and RUNNER.is_file() and (MODELLER / "node_modules" / "three").is_dir()),
    reason="needs node + the modeller repo with its dependencies installed (MODELLER_DIR=<path>; run `npm ci` there)",
)

FACES = ["right", "left", "top", "bottom", "front", "back"]
FIELDS = ["width", "height", "thickness", "positionX", "positionY", "positionZ"]
ROTATIONS = [(0, 0, 0), (0, 90, 0), (90, 0, 0), (0, 0, 90), (90, 90, 0), (0, -90, 0), (0, 180, 0), (180, 0, 0),
             (0, 0, 45), (0, 0, 11), (0, 0, 12), (30, 60, 0), (270, 0, 90), (0, 0, 11.4), (0, 0, 11.6),
             # all three angles non-zero: exercises every term of the Euler matrix
             (90, 90, 90), (90, 0, 90), (0, 90, 90), (30, 60, 45), (180, 90, 180), (10, 10, 10), (89, 91, 90)]


def random_graph(rng: random.Random) -> list[dict]:
    n = rng.randint(1, 8)
    ids = [f"p{i}" for i in range(n)]

    def ref(allow_literal=True):
        roll = rng.random()
        if allow_literal and roll < 0.12:
            return {"mm": round(rng.uniform(-500, 1500), 3)}
        node = rng.choice(ids + ["ghost"] if roll < 0.2 else ids)
        end = {"node": node, "face": rng.choice(FACES + (["sideways"] if rng.random() < 0.05 else []))}
        if rng.random() < 0.6:
            end["offset"] = rng.choice([0, 10, -10, 25.5, 100])
        return end

    def constraint():
        t = rng.choices(["spansBetween", "attachedTo", "distance", "equalSpacing", "weird"], [4, 3, 3, 2, 0.3])[0]
        c: dict = {"id": f"c{rng.randint(0, 999)}", "type": t, "field": rng.choice(FIELDS),
                   "overridden": rng.random() < 0.08}
        if t == "spansBetween":
            c["field"] = rng.choice(["width", "height", "width", "height", "thickness", "positionX"])
            c["from"], c["to"] = ref(), ref()
        elif t == "attachedTo":
            c["field"] = rng.choice(["positionX", "positionY", "positionZ", "width"])
            c["from"] = ref(allow_literal=False) if rng.random() < 0.9 else ref()
            if rng.random() < 0.92:
                c["myFace"] = rng.choice(FACES)
        elif t == "distance":
            c["field"] = rng.choice(["positionX", "positionY", "positionZ", "positionX", "width"])
            c["from"] = ref(allow_literal=False)
            if rng.random() < 0.92:
                c["myFace"] = rng.choice(FACES)
            if rng.random() < 0.93:
                c["value"] = rng.choice([0, 5, 25, 120.5, -3])
        elif t == "equalSpacing":
            c["field"] = rng.choice(["positionX", "positionY", "positionZ", "height"])
            c["from"], c["to"] = ref(allow_literal=False), ref(allow_literal=False)
            c["members"] = rng.sample(ids, rng.randint(1, min(4, n))) + (["ghost"] if rng.random() < 0.1 else [])
            c["spacingId"] = "sp"
        return c

    panels = []
    for pid in ids:
        rot = rng.choice(ROTATIONS)
        panels.append({
            "id": pid, "name": f"Panel {pid}", "material": "Melamine White 18mm", "quantity": 1, "thicknessAxis": "z",
            "width": round(rng.uniform(10, 1500), 3), "height": round(rng.uniform(10, 1500), 3), "thickness": 18,
            "rotation": {"x": rot[0], "y": rot[1], "z": rot[2]},
            "basePosition": {a: round(rng.uniform(-300, 800), 3) for a in "xyz"},
            "offset": {a: rng.choice([0, 0, round(rng.uniform(-100, 100), 3)]) for a in "xyz"},
            "constraints": [constraint() for _ in range(rng.choice([0, 1, 1, 2, 3]))],
            "groupId": rng.choice([None, None, "g1"]), "hidden": rng.random() < 0.1,
            "lockedMoveAxes": rng.choice([[], [], ["x"], ["y", "z"], ["x", "bogus"]]),
        })
    rng.shuffle(panels)
    return panels


def run_js(graphs: list[list[dict]]) -> list[dict]:
    # Bytes in, bytes out, decoded as UTF-8 EXPLICITLY: warning texts contain an em dash, and `text=True` would decode
    # node's UTF-8 with the platform default (cp1252 on Windows) and corrupt them.
    done = subprocess.run(
        ["node", str(RUNNER)], input=json.dumps(graphs).encode("utf-8"), capture_output=True, cwd=MODELLER, timeout=300
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")[:2000]
    return json.loads(done.stdout.decode("utf-8"))


def test_python_resolver_matches_the_js_resolver_on_random_graphs():
    rng = random.Random(int(os.environ.get("FUZZ_SEED", "20261114")))
    graphs = [random_graph(rng) for _ in range(FUZZ_N)]
    js = run_js(graphs)
    problems, warned, constrained = [], 0, 0
    kinds: Counter = Counter()
    for i, (graph, expected) in enumerate(zip(graphs, js, strict=True)):
        assert "ok" in expected, f"JS resolver threw on graph {i}: {expected} (generator produced an unsupported shape)"
        actual = resolve_constraints(PanelSet.model_validate({"panels": graph}).panels)
        diffs = deep_diff(actual, expected["ok"], abs_tol=1e-6)
        if diffs:
            kinds.update(re.sub(r"\[\d+\]", "[]", d.split(":")[0]) for d in diffs)
            problems.append(f"graph {i}: {diffs[0]}   (+{len(diffs) - 1} more)\n{json.dumps(graph)[:600]}")
        warned += any(r["warnings"] for r in expected["ok"])
        constrained += any(p["constraints"] for p in graph)
    assert not problems, (
        f"{len(problems)} of {FUZZ_N} graphs differ. Most common differing fields: {kinds.most_common(5)}\n"
        + "\n".join(problems[:3])
    )
    # the generator must really exercise warnings and constraints, or this test proves nothing
    assert constrained > FUZZ_N * 0.7 and warned > FUZZ_N * 0.2, (constrained, warned)
