"""Exports the API's assembly output for every golden design, for the modeller's i18n tests.

    python scripts/export_steps_fixtures.py --out ../3d_modeler/fixtures/api-steps

One `<design>.assembly.json` per golden design (the exact body POST /v1/assembly returns). The modeller's
tests/stepsI18n.test.mjs renders these in en / fr / it, so a planner change that alters wording or codes shows up
there. Re-run after any change to the planner and commit the result.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root: app/ and tests/

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.golden_harness import GOLDEN, designs, load  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    out: Path = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.assembly.json"):
        old.unlink()
    client = TestClient(app)
    names = designs("assembly")
    for name in names:
        r = client.post("/v1/assembly", json={"panels": load(name, "raw")})
        r.raise_for_status()
        text = json.dumps(r.json(), indent=1, sort_keys=True) + "\n"
        (out / f"{name}.assembly.json").write_text(text, encoding="utf-8")
    print(f"{len(names)} designs exported to {out} (golden dir: {GOLDEN})")


if __name__ == "__main__":
    main()
