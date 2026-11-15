"""Phase 6: guard rails of POST /v1/nesting — deadline, concurrency cap, determinism."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.concurrency import SlotLimiter
from app.config import Settings, get_settings
from app.main import app
from app.services.nesting import NestingTimeout, nest_pieces, now
from tests.conftest import panel
from tests.golden_harness import load

STOCK = {"widthMm": 2440.0, "heightMm": 1220.0}


def heavy_panels(n=500):
    """Hostile-but-valid input: the most pieces the API accepts, tiny sizes (maximises free rectangles)."""
    return [panel(f"p{i}", 10 + (i * 7) % 50, 10 + (i * 13) % 50) for i in range(n)]


def with_settings(**kw):
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys="", **kw)


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ cooperative deadline
def pieces(n):
    return [{"id": f"p{i}", "label": f"p{i}", "widthMm": 100.0 + i, "heightMm": 80.0 + i, "rotatable": True,
             "finishedWidthMm": 100.0 + i, "finishedHeightMm": 80.0 + i} for i in range(n)]


def test_deadline_in_the_past_raises():
    with pytest.raises(NestingTimeout):
        nest_pieces(pieces(5), STOCK, 3, deadline=now() - 1)


def test_generous_deadline_changes_nothing():
    assert nest_pieces(pieces(40), STOCK, 3, deadline=now() + 60) == nest_pieces(pieces(40), STOCK, 3)


def test_zero_budget_counts_as_expired_even_if_the_clock_did_not_advance(monkeypatch):
    """Regression (Windows): time.monotonic() ticks every ~15.6 ms, so `now > deadline` was False for a fast request."""
    import app.services.nesting as nesting

    monkeypatch.setattr(nesting, "now", lambda: 1000.0)  # a frozen clock
    with pytest.raises(NestingTimeout):
        nest_pieces(pieces(3), STOCK, 3, deadline=1000.0)


def test_no_pieces_never_times_out():
    assert nest_pieces([], STOCK, 3, deadline=now() - 1) == {"sheets": [], "unplaced": []}


def test_heavy_request_times_out_fast_and_cleanly(client):
    with_settings(nesting_timeout_s=0.05)
    t0 = time.perf_counter()
    r = client.post("/v1/nesting", json={"panels": heavy_panels()})
    assert r.status_code == 503 and r.json()["code"] == "nesting_timeout"
    assert time.perf_counter() - t0 < 1.5, "the deadline must actually stop the work"


def test_server_still_healthy_after_a_timeout(client):
    with_settings(nesting_timeout_s=0.05)
    assert client.post("/v1/nesting", json={"panels": heavy_panels()}).status_code == 503
    app.dependency_overrides.clear()
    assert client.get("/health").status_code == 200
    assert client.post("/v1/nesting", json={"panels": [panel("A", 400, 700)]}).status_code == 200


def test_heavy_request_completes_with_the_default_budget(client):
    r = client.post("/v1/nesting", json={"panels": heavy_panels()})
    assert r.status_code == 200 and r.json()["summary"]["totals"]["unplacedCount"] == 0


# ------------------------------------------------------------------ concurrency cap
def test_busy_when_all_slots_taken_then_recovers(client):
    limiter = app.state.nesting_slots = SlotLimiter(1)
    assert limiter.acquire()  # someone else is nesting
    r = client.post("/v1/nesting", json={"panels": [panel("A", 400, 700)]})
    assert r.status_code == 503 and r.json()["code"] == "busy" and r.headers["retry-after"] == "1"
    limiter.release()
    assert client.post("/v1/nesting", json={"panels": [panel("A", 400, 700)]}).status_code == 200


def test_slot_is_released_after_success_error_and_timeout(client):
    limiter = app.state.nesting_slots = SlotLimiter(1)
    ok = {"panels": [panel("A", 400, 700)]}
    assert client.post("/v1/nesting", json=ok).status_code == 200
    assert client.post("/v1/nesting", json={"panels": [{"id": "x"}]}).status_code == 422
    with_settings(nesting_timeout_s=0.0)
    assert client.post("/v1/nesting", json=ok).status_code == 503
    assert limiter.acquire(), "a slot leaked"
    limiter.release()


def test_zero_slots_means_always_busy(client):
    app.state.nesting_slots = SlotLimiter(0)
    assert client.post("/v1/nesting", json={"panels": []}).status_code == 503


def test_other_endpoints_are_not_throttled_by_nesting_slots(client):
    limiter = app.state.nesting_slots = SlotLimiter(1)
    limiter.acquire()
    assert client.post("/v1/bom", json={"panels": [panel("A", 400, 700)]}).status_code == 200
    assert client.get("/v1/catalog/materials").status_code == 200
    limiter.release()


def test_overload_codes_are_in_the_contract():
    spec = app.openapi()
    desc = spec["paths"]["/v1/nesting"]["post"]["responses"]["503"]["description"]
    assert "code=busy" in desc and "code=nesting_timeout" in desc


# ------------------------------------------------------------------ determinism across processes
SNIPPET = """
import hashlib, json, sys
from app.schemas.bom import Panel
from app.catalog.loader import load_materials
from app.services.bom import compute_bom
from app.services.nesting import nest_cut_list
panels = [Panel.model_validate(p) for p in json.load(open(sys.argv[1], encoding="utf-8"))]
catalog = load_materials()
res = nest_cut_list(compute_bom(panels, catalog), catalog)
print(hashlib.sha256(json.dumps(res, sort_keys=True).encode()).hexdigest())
"""


@pytest.mark.parametrize("design", ["box_drawers_plinth", "two_boxes"])
def test_output_is_independent_of_pythonhashseed(design):
    path = Path(__file__).parent / "golden" / design / "panels.json"
    root = Path(__file__).resolve().parent.parent
    digests = {
        subprocess.run([sys.executable, "-c", SNIPPET, str(path)], cwd=root, capture_output=True, text=True,
                       env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(root), "PATH": ""}, check=True).stdout.strip()
        for seed in ("0", "1", "424242", "random")
    }
    assert len(digests) == 1, f"output depends on hash randomisation: {digests}"


def test_api_answer_is_byte_identical_between_calls(client):
    body = {"panels": load("box_drawers_plinth", "panels")}
    a = client.post("/v1/nesting", json=body).content
    b = client.post("/v1/nesting", json=body).content
    assert hashlib.sha256(a).digest() == hashlib.sha256(b).digest()
    assert json.loads(a) == json.loads(b)
