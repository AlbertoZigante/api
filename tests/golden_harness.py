"""Golden-test harness.

One registry (STAGES) says, per stage of the pipeline, how to compute the API's answer for a design and which frozen
file (tests/golden/<design>/<stage>.json) is the reference. The files are what the ORIGINAL JS engine answered, frozen
during the migration; they are the contract the Python rules must keep. Changing a rule on purpose = bump RULES_VERSION,
run `python scripts/update_golden.py`, review the diff.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).parent / "golden"


def designs(having: str | None = None) -> list[str]:
    """Golden design names; `having="joints"` keeps only those that have that golden file (resolver-only
    designs freeze just raw + resolved)."""
    names = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
    return [d for d in names if having is None or (GOLDEN / d / f"{having}.json").is_file()]


def load(design: str, name: str) -> Any:
    return json.loads((GOLDEN / design / f"{name}.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------------- comparison
def deep_diff(actual: Any, expected: Any, abs_tol: float = 1e-3, path: str = "$") -> list[str]:
    """Structural diff with numeric tolerance. Returns human-readable differences ([] = equal)."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return [] if actual is expected else [f"{path}: {actual!r} != {expected!r}"]
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return [] if math.isclose(actual, expected, rel_tol=0, abs_tol=abs_tol) else [f"{path}: {actual!r} != {expected!r} (tol {abs_tol})"]
    if isinstance(expected, dict) and isinstance(actual, dict):
        diffs = [f"{path}.{k}: missing in actual" for k in expected.keys() - actual.keys()]
        diffs += [f"{path}.{k}: unexpected in actual" for k in actual.keys() - expected.keys()]
        for k in sorted(expected.keys() & actual.keys()):
            diffs += deep_diff(actual[k], expected[k], abs_tol, f"{path}.{k}")
        return diffs
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            return [f"{path}: length {len(actual)} != {len(expected)}"]
        return [d for i, (a, e) in enumerate(zip(actual, expected, strict=True)) for d in deep_diff(a, e, abs_tol, f"{path}[{i}]")]
    return [] if actual == expected and type(actual) is type(expected) else [f"{path}: {actual!r} != {expected!r}"]


# def assert_matches(actual: Any, expected: Any, abs_tol: float = 1e-3) -> None:
#     diffs = deep_diff(actual, expected, abs_tol)
#     assert not diffs, f"{len(diffs)} difference(s):\n  " + "\n  ".join(diffs[:10])
# Fields the Python API ADDED on top of the frozen JS output (additive contract extension).
ADDITIVE_KEYS = frozenset({
    "assemblyKind", "assemblyIndex",
    # phase 10: structured wording added to the assembly steps / clusters / plan (the JS has only prose)
    "order", "verb", "instructionVerb", "params", "warningCodes", "hardwareIds", "toolCodes", "toolNoteCodes",
    "component", "subassemblyRef", "completionRef", "ordinal", "toolsSummaryCodes",
})

def _strip_additive(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _strip_additive(v) for k, v in x.items() if k not in ADDITIVE_KEYS}
    if isinstance(x, list):
        return [_strip_additive(v) for v in x]
    return x


def assert_matches(actual: Any, expected: Any, abs_tol: float = 1e-3) -> None:
    diffs = deep_diff(_strip_additive(actual), expected, abs_tol)
    assert not diffs, f"{len(diffs)} difference(s):\n  " + "\n  ".join(diffs[:10])

# ----------------------------------------------------------------------- stages
Runner = Callable[[Any, str], Any]  # (client, design) -> actual


@dataclass(frozen=True)
class Stage:
    name: str
    expected: str         # golden file the answer is compared to
    run: Runner
    abs_tol: float = 1e-3


def _post(path: str, body_of: Callable[[str], dict]) -> Runner:
    def run(client, design: str):
        r = client.post(path, json=body_of(design))
        assert r.status_code == 200, f"{path} -> HTTP {r.status_code}: {r.text[:200]}"
        return r.json()
    return run


def _resolve(client, design: str):
    """No endpoint: the resolver is internal (the server resolves the RAW graph itself)."""
    from app.schemas.panels import PanelSet
    from app.services.resolve import resolve_constraints

    return resolve_constraints(PanelSet.model_validate({"panels": load(design, "raw")}).panels)


def _sequence(client, design: str):
    """No endpoint for the bare sequence (steps without tools / ergonomics): call the planner directly."""
    from app.rules.assembly import build_assembly_sequence
    from app.schemas.panels import PanelSet
    from app.services.resolve import resolve_constraints

    panels = PanelSet.model_validate(_raw(design)).panels
    seq = build_assembly_sequence(panels, resolve_constraints(panels))
    seq.pop("_resolved_by_id")
    return seq


def _joints_part(part: str) -> Runner:
    """POST /v1/joints returns {joints, collisions, featureJoints}; each golden stage is one slice of it."""
    def run(client, design: str):
        r = client.post("/v1/joints", json=_raw(design))
        assert r.status_code == 200, f"/v1/joints -> HTTP {r.status_code}: {r.text[:200]}"
        body = r.json()
        return body["featureJoints"] if part == "featureJoints" else {"joints": body["joints"], "collisions": body["collisions"]}
    return run


def _raw(design: str) -> dict:
    return {"panels": load(design, "raw")}


STAGES: dict[str, Stage] = {s.name: s for s in [
    Stage("bom", "legacyBom", _post("/v1/bom", lambda d: {"panels": load(d, "panels")}), abs_tol=1e-6),
    Stage("nesting", "legacyNesting", _post("/v1/nesting", lambda d: {"panels": load(d, "panels"), "options": {}}), abs_tol=1e-6),
    Stage("resolved", "resolved", _resolve),
    Stage("joints", "joints", _joints_part("joints")),
    Stage("featureJoints", "featureJoints", _joints_part("featureJoints")),
    Stage("hardware", "hardware", _post("/v1/hardware-plan", _raw)),
    Stage("sequence", "sequence", _sequence),
    Stage("assembly", "assembly", _post("/v1/assembly", _raw)),
]}
