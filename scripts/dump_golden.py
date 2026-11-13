"""Freeze BOM + nesting baselines for every golden design.

Reads  <modeller>/fixtures/golden/<design>/resolved.json  (frozen JS output)
Writes tests/golden/<design>/{resolved,panels,bom,nesting}.json
  - resolved.json : copy of the modeller's resolved panels (shared fixture)
  - panels.json   : the exact request payload the modeller sends (= api/payload.js toPayload)
  - bom.json / nesting.json : current API responses (already verified identical
    to the old JS engine, see tests/test_nesting.py) -> regression baselines.

Usage:  python scripts/dump_golden.py [path/to/3d_modeler/fixtures/golden]
Also copies the JS-only stage goldens (joints, featureJoints, hardware,
sequence, assembly) so later migration phases test against the same folder.

Extra (migration phase 4):
  - catalog.json: the API's material catalog, written BOTH here and next to the
    modeller goldens (the legacy JS oracle needs the exact same catalog).
  - legacyBom.json / legacyNesting.json: output of the ORIGINAL JS bom/nesting
    engine (3d_modeler `npm run golden:legacy`), copied here when present.
    They are the independent reference the API is compared against.

Panels sent to /v1/bom and /v1/nesting are the VISIBLE resolved panels, exactly
what modeller-main.js passes to requestBom().
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ["API_KEYS"] = ""  # never freeze baselines through an auth wall (a local .env may enable API keys)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "3d_modeler" / "fixtures" / "golden"
DST = ROOT / "tests" / "golden"
JS_STAGES = ["raw", "resolved", "joints", "featureJoints", "hardware", "sequence", "assembly"]
LEGACY_STAGES = ["legacyBom", "legacyNesting"]  # optional: produced by the modeller oracle


def to_payload(panels: list[dict]) -> list[dict]:
    """Python twin of 3d_modeler/src/api/payload.js toPayload()."""
    return [
        {
            "id": p["id"], "name": p.get("name"), "pieceCode": p.get("pieceCode"),
            "width": p["width"], "height": p["height"], "thickness": p["thickness"],
            "material": p["material"], "bandedEdges": p.get("bandedEdges") or [],
            "groupId": p.get("groupId"), "boxGroupId": p.get("boxGroupId"),
            "isDoor": bool(p.get("isDoor")), "isPlinthPanel": bool(p.get("isPlinthPanel")),
            "isLeg": bool(p.get("isLeg")), "isBoxPanel": bool(p.get("isBoxPanel")),
            "isDrawerFront": bool(p.get("isDrawerFront")),
            "isDrawerBoxPanel": bool(p.get("isDrawerBoxPanel")),
        }
        for p in panels
    ]


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    if not SRC.is_dir():
        sys.exit(f"golden source not found: {SRC}")
    designs = sorted(p.name for p in SRC.iterdir() if p.is_dir())
    with TestClient(app) as client:
        catalog = client.get("/v1/catalog/materials").json()
        dump(DST / "catalog.json", catalog)
        dump(SRC / "catalog.json", catalog)  # input of the modeller's legacy oracle
        for name in designs:
            out = DST / name
            out.mkdir(parents=True, exist_ok=True)
            for stage in JS_STAGES + LEGACY_STAGES:
                if (SRC / name / f"{stage}.json").is_file():
                    shutil.copyfile(SRC / name / f"{stage}.json", out / f"{stage}.json")
            resolved = json.loads((SRC / name / "resolved.json").read_text(encoding="utf-8"))
            visible = [p for p in resolved if not p.get("hidden")] if isinstance(resolved, list) else []
            panels = to_payload(visible)
            dump(out / "panels.json", panels)
            bom = client.post("/v1/bom", json={"panels": panels})
            nest = client.post("/v1/nesting", json={"panels": panels, "options": {}})
            if bom.status_code != 200 or nest.status_code != 200:  # a baseline must never freeze an error
                sys.exit(f"{name}: bom={bom.status_code} nesting={nest.status_code} — refusing to write baselines")
            dump(out / "bom.json", {"status": bom.status_code, "body": bom.json()})
            dump(out / "nesting.json", {"status": nest.status_code, "body": nest.json()})
            print(f"ok  {name:<24} bom={bom.status_code} nesting={nest.status_code} panels={len(panels)}")
    shutil.copyfile(SRC / "manifest.json", DST / "manifest.json")
    print(f"\n{len(designs)} designs -> {DST}")


if __name__ == "__main__":
    main()
