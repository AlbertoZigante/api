"""Golden-test harness (migration phase 3).

One registry says, per stage of the pipeline, how to compute the API's answer for a
design and which frozen file is the reference. A stage whose port has not landed yet is
registered as `ported=False` and runs as a STRICT xfail: it is reported as "not ported",
and the moment the port starts passing pytest FAILS (XPASS strict) until the stage is
flipped to `ported=True` here — so the harness can never silently lag behind the code.

To un-skip a stage in a later phase:  flip `ported=True` (and point `run` at the service).
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).parent / "golden"


class NotPorted(Exception):
    """Raised by the runner of a stage that has no Python implementation yet."""


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
ADDITIVE_KEYS = frozenset({"assemblyKind", "assemblyIndex"})

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
    phase: str            # migration phase that ports it
    expected: str         # golden file the answer is compared to
    run: Runner
    ported: bool
    abs_tol: float = 1e-3


def _post(path: str, body_of: Callable[[str], dict]) -> Runner:
    def run(client, design: str):
        r = client.post(path, json=body_of(design))
        assert r.status_code == 200, f"{path} -> HTTP {r.status_code}: {r.text[:200]}"
        return r.json()
    return run


def _not_ported(stage: str) -> Runner:
    def run(client, design: str):
        raise NotPorted(stage)
    return run


def _resolve(client, design: str):
    """No endpoint: the resolver is internal (the server resolves the RAW graph itself)."""
    from app.schemas.panels import PanelSet
    from app.services.resolve import resolve_constraints

    return resolve_constraints(PanelSet.model_validate({"panels": load(design, "raw")}).panels)


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
    # --- ported
    Stage("bom", "4", "legacyBom", _post("/v1/bom", lambda d: {"panels": load(d, "panels")}), ported=True, abs_tol=1e-6),
    Stage("nesting", "6", "legacyNesting", _post("/v1/nesting", lambda d: {"panels": load(d, "panels"), "options": {}}), ported=True, abs_tol=1e-6),
    # --- not ported yet (flip ported=True when the phase lands)
    Stage("resolved", "8", "resolved", _resolve, ported=True),
    Stage("joints", "8", "joints", _joints_part("joints"), ported=True),
    Stage("featureJoints", "8", "featureJoints", _joints_part("featureJoints"), ported=True),
    Stage("hardware", "9", "hardware", _post("/v1/hardware-plan", _raw), ported=False),
    Stage("sequence", "9", "sequence", _not_ported("sequence"), ported=False),
    Stage("assembly", "9", "assembly", _post("/v1/assembly", _raw), ported=False),
]}
