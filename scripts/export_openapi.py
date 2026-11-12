"""Write the OpenAPI contract to openapi.json (committed; the modeller generates TS types from it).

    python scripts/export_openapi.py          # write
    python scripts/export_openapi.py --check  # exit 1 if the committed file is stale
"""
import json
import sys
from pathlib import Path

from app.main import app

TARGET = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != text:
            sys.exit("openapi.json is stale: run `python scripts/export_openapi.py` and commit it")
        print("openapi.json up to date")
    else:
        TARGET.write_text(text, encoding="utf-8")
        print(f"wrote {TARGET}")
