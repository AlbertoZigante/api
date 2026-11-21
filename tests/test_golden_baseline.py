"""Phase 0 regression net: BOM + nesting must keep matching the frozen baselines.

Baselines are produced by scripts/dump_golden.py from the modeller's frozen
fixtures (3d_modeler/fixtures/golden). If a change here is INTENDED, re-run
the script and review the diff of tests/golden/ in the PR.
"""
import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden"
STAGES = ["raw", "resolved", "joints", "featureJoints", "hardware", "sequence", "assembly", "panels", "bom", "nesting"]
DESIGNS = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir() and (p / "panels.json").is_file())  # full designs


def load(design: str, stage: str):
    return json.loads((GOLDEN / design / f"{stage}.json").read_text(encoding="utf-8"))


def test_manifest_matches_folders():
    manifest = load_manifest()
    on_disk = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
    assert sorted(manifest["designs"]) == on_disk
    assert len(DESIGNS) >= 20


def load_manifest():
    return json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("design", DESIGNS)
def test_every_stage_file_present(design):
    missing = [s for s in STAGES if not (GOLDEN / design / f"{s}.json").is_file()]
    assert not missing, f"{design}: missing {missing}"


@pytest.mark.parametrize("design", DESIGNS)
def test_bom_baseline(client, design):
    r = client.post("/v1/bom", json={"panels": load(design, "panels")})
    assert {"status": r.status_code, "body": r.json()} == load(design, "bom")


@pytest.mark.parametrize("design", DESIGNS)
def test_nesting_baseline(client, design):
    r = client.post("/v1/nesting", json={"panels": load(design, "panels"), "options": {}})
    assert {"status": r.status_code, "body": r.json()} == load(design, "nesting")
