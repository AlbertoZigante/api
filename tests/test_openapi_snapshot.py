import json
from pathlib import Path

from app.main import app

SNAPSHOT = Path(__file__).resolve().parent.parent / "openapi.json"


def test_openapi_snapshot_is_current():
    """Fails when a schema/route changed without re-exporting the contract:
    run `python scripts/export_openapi.py` and commit openapi.json (the modeller's TS types derive from it)."""
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == json.loads(json.dumps(app.openapi()))
