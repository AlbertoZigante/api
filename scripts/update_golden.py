"""Regenerate golden files from what the API answers NOW — only for an INTENTIONAL rule change.

    python scripts/update_golden.py --stage hardware            # all designs, one stage
    python scripts/update_golden.py --stage assembly --design box_door_left
    python scripts/update_golden.py --all

The goldens are the contract inherited from the original JS engine. Regenerating them rewrites that contract: bump
RULES_VERSION first, run this, and REVIEW the git diff line by line (each change must be the rule change you meant).
Also re-run `python scripts/export_steps_fixtures.py --out ../3d_modeler/fixtures/api-steps` after touching assembly.
Note: regenerated assembly / sequence goldens then contain the structured wording keys (the JS ones do not).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from tests.golden_harness import GOLDEN, STAGES, designs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=sorted(STAGES))
    ap.add_argument("--design")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not (args.stage or args.all):
        ap.error("give --stage or --all")
    stages = sorted(STAGES) if args.all else [args.stage]
    written = 0
    with TestClient(app) as client:
        for name in stages:
            spec = STAGES[name]
            for design in designs(spec.expected):
                if args.design and design != args.design:
                    continue
                actual = spec.run(client, design)
                text = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
                (GOLDEN / design / f"{spec.expected}.json").write_text(text, encoding="utf-8")
                written += 1
    print(f"{written} golden files rewritten — review `git diff tests/golden`")


if __name__ == "__main__":
    main()
