"""REGRESSION CORPUS: 703 designs and what the original JS engine answered for each, frozen in phase 12 (before the
JS was deleted) in tests/golden/corpus.jsonl.gz. This replaces the differential fuzz tests that ran Python against
live JS during the migration: same inputs (random layouts at every joint-tolerance boundary, furniture with drawers /
doors, cabinets with plinth / identical drawers / loose panels, constraint graphs), same expectations, no node needed.

  engine   503 designs: resolved, joints (+ collisions), featureJoints, hardware plan, assembly sequence, assembly plan
  resolve  200 designs: the constraint resolver alone (warnings, equalSpacing, rotations...)

The structured wording added after the port (verbs, codes, refs: ADDITIVE_KEYS) is not in the JS answers and is
ignored here; tests/test_assembly_structured.py proves it rebuilds the prose. When a rule changes ON PURPOSE (and
RULES_VERSION is bumped) regenerate with scripts/update_golden.py and review the diff.
"""
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.rules.assembly import build_assembly_plan, build_assembly_sequence
from app.schemas.panels import PanelSet
from app.services.hardware import build_hardware_plan
from app.services.joints import detect_feature_joints, detect_joints
from app.services.resolve import resolve_constraints
from tests.golden_harness import _strip_additive, deep_diff

CORPUS_PATH = Path(__file__).parent / "golden" / "corpus.jsonl.gz"


def _load() -> list[dict]:
    with gzip.open(CORPUS_PATH, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


CORPUS = _load()
ENGINE = [e for e in CORPUS if e["kind"] == "engine"]
RESOLVE = [e for e in CORPUS if e["kind"] == "resolve"]


def _actual(entry: dict) -> dict:
    panels = PanelSet.model_validate({"panels": entry["raw"]}).panels
    resolved = resolve_constraints(panels)
    joints = detect_joints(resolved)
    features = detect_feature_joints(panels, resolved)
    sequence = build_assembly_sequence(panels, resolved)
    sequence.pop("_resolved_by_id")
    return {
        "resolved": resolved, "joints": joints, "featureJoints": features,
        "hardware": build_hardware_plan(panels, resolved, joints=joints["joints"], feature_joints=features),
        "sequence": sequence, "assembly": build_assembly_plan(panels, resolved),
    }


def _report(kind: str, problems: list[str], kinds: Counter, total: int) -> str:
    return (f"{len(problems)} of {total} {kind} designs differ. Most common differing fields: {kinds.most_common(5)}\n"
            + "\n".join(problems[:3]))


def test_the_corpus_is_what_we_think_it_is():
    assert len(ENGINE) == 503 and len(RESOLVE) == 200
    assert {e["name"].split("-")[0] for e in ENGINE} == {"random", "furniture", "cabinet"}
    assert sum(e["name"].startswith("cabinet-twin") for e in ENGINE) == 33  # cabinets with identical drawers (x N)
    assert len({e["name"] for e in CORPUS}) == len(CORPUS)


def test_engine_stages_match_what_the_js_answered():
    problems: list[str] = []
    kinds: Counter = Counter()
    seen: Counter = Counter()
    for entry in ENGINE:
        actual, expected = _strip_additive(_actual(entry)), entry["expected"]
        for stage in ("resolved", "joints", "featureJoints", "hardware", "sequence", "assembly"):
            diffs = deep_diff(actual[stage], expected[stage], abs_tol=1e-6, path=stage)
            if diffs:
                kinds.update(re.sub(r"\[\d+\]", "[]", d.split(":")[0]) for d in diffs)
                problems.append(f"{entry['name']}: {diffs[0]}  (+{len(diffs) - 1} more)")
        exp = entry["expected"]
        for j in exp["joints"]["joints"]:
            seen[j["type"]] += 1
        seen["collision"] += len(exp["joints"]["collisions"])
        seen["featureJoint"] += len(exp["featureJoints"])
        for key in ("hinges", "runners", "fasteners", "unmatched"):
            seen[key] += len(exp["hardware"][key])
        for s in exp["assembly"]["steps"]:
            seen[f"stage:{s['stage']}"] += 1
            seen[f"kind:{s['kind']}"] += 1
            seen["repeat>1"] += s.get("repeatCount", 1) > 1
    assert not problems, _report("engine", problems, kinds, len(ENGINE))
    # the corpus must really reach every kind of result, or this test proves nothing
    needed = ["face_to_face", "corner_butt", "t_butt", "edge_to_edge", "near_contact", "collision", "featureJoint",
              "hinges", "runners", "fasteners", "unmatched", "stage:doors", "stage:drawers", "stage:guides", "stage:plinth",
              "stage:carcass", "stage:integration", "kind:pre_install", "kind:fit_handle", "kind:integrate",
              "kind:unattached", "repeat>1"]
    assert all(seen[k] >= 10 for k in needed), {k: seen[k] for k in needed}


def test_resolver_matches_what_the_js_answered():
    problems: list[str] = []
    kinds: Counter = Counter()
    warned = constrained = 0
    for entry in RESOLVE:
        actual = resolve_constraints(PanelSet.model_validate({"panels": entry["raw"]}).panels)
        diffs = deep_diff(actual, entry["expected"], abs_tol=1e-6)
        if diffs:
            kinds.update(re.sub(r"\[\d+\]", "[]", d.split(":")[0]) for d in diffs)
            problems.append(f"{entry['name']}: {diffs[0]}  (+{len(diffs) - 1} more)")
        warned += any(r["warnings"] for r in entry["expected"])
        constrained += any(p["constraints"] for p in entry["raw"])
    assert not problems, _report("resolve", problems, kinds, len(RESOLVE))
    assert constrained > len(RESOLVE) * 0.7 and warned > len(RESOLVE) * 0.2, (constrained, warned)


@pytest.mark.parametrize("name", ["cabinet-000", "furniture-000", "random-000"])
def test_a_few_entries_are_individually_checkable(name):
    """Named entries so a regression can be bisected without running the whole corpus."""
    entry = next(e for e in ENGINE if e["name"] == name)
    actual = _strip_additive(_actual(entry))
    for stage in ("resolved", "joints", "hardware", "assembly"):
        assert not deep_diff(actual[stage], entry["expected"][stage], abs_tol=1e-6)
