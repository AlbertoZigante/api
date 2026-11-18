import os

import pytest
from fastapi.testclient import TestClient

# Tests must NOT depend on a developer's local .env: an API_KEYS there would turn auth on and every
# request would answer 401. Env vars beat .env in pydantic-settings, so force auth OFF before the app
# is imported; the tests that exercise auth enable it explicitly (dependency_overrides).
os.environ["API_KEYS"] = ""
os.environ["JWT_SECRET"] = ""
os.environ["JWT_PUBLIC_KEY"] = ""
os.environ["ENV"] = "development"
# a few hundred requests per test run from one client: the real limits are exercised by tests/test_rate_limit.py
os.environ["NESTING_EXECUTOR"] = "thread"  # worker processes are covered by tests/test_nesting_runner.py
os.environ["RATE_LIMIT"] = "100000/minute"
os.environ["RATE_LIMIT_HEAVY"] = "100000/minute"
os.environ["AUTH_FAIL_LIMIT"] = "100000/minute"

from app.catalog.loader import load_materials  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def catalog():
    return load_materials()


@pytest.fixture()
def client(monkeypatch):
    from app.config import get_settings
    from app.ratelimit import reset_limits

    monkeypatch.setenv("API_KEYS", "")
    get_settings.cache_clear()
    reset_limits()
    with TestClient(app) as c:
        yield c


def panel(id, w, h, material="Melamine White 18mm", thickness=18, **kw):
    return {"id": id, "name": id, "pieceCode": f"P-{id}", "width": w, "height": h,
            "thickness": thickness, "material": material, **kw}


# ----------------------------------------------------------------------- per-stage golden report
_stage_counts: dict[str, dict[str, int]] = {}


def pytest_runtest_logreport(report):
    """Collects pass / not-ported / fail counts per golden stage (test ids look like `bom-box_plain`)."""
    if "test_stage_matches_golden[" not in report.nodeid:
        return
    if report.when == "call" or (report.when == "setup" and report.skipped):
        stage = report.nodeid.split("[", 1)[1].split("-", 1)[0]
        if hasattr(report, "wasxfail"):
            outcome = "not ported"
        else:
            outcome = {"passed": "passed", "failed": "FAILED", "skipped": "skipped"}[report.outcome]
        _stage_counts.setdefault(stage, {}).setdefault(outcome, 0)
        _stage_counts[stage][outcome] += 1


def pytest_terminal_summary(terminalreporter):
    if not _stage_counts:
        return
    terminalreporter.section("golden stages (JS reference vs Python)")
    for stage, counts in _stage_counts.items():
        terminalreporter.write_line(f"{stage:<14} " + "  ".join(f"{k}: {v}" for k, v in counts.items()))
