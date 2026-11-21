"""Phase 11: nesting in worker processes (keeps the web process responsive) — equivalence, timeouts, recovery."""
import asyncio
import os
import signal
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.nesting_runner import NestingRunner
from app.ratelimit import reset_limits
from app.services.nesting import NestingTimeout
from tests.conftest import panel
from tests.test_nesting_limits import heavy_panels


def hang_job(rows, catalog, kerf, margin, timeout_s):
    """A job that ignores its deadline (module-level: workers import it)."""
    time.sleep(60)


def pid_job(rows, catalog, kerf, margin, timeout_s):
    return os.getpid()


def die_job(rows, catalog, kerf, margin, timeout_s):
    os.kill(os.getpid(), signal.SIGKILL)


def body(n=40):
    return {"panels": [panel(f"p{i}", 200 + (i * 37) % 400, 100 + (i * 53) % 300) for i in range(n)]}


@pytest.fixture(scope="module")
def process_client():
    """The real app with worker processes (spawned once for the module)."""
    os.environ["NESTING_EXECUTOR"] = "process"
    os.environ["MAX_CONCURRENT_NESTINGS"] = "2"
    get_settings.cache_clear()
    reset_limits()
    with TestClient(app) as c:
        yield c
    os.environ["NESTING_EXECUTOR"] = "thread"
    os.environ.pop("MAX_CONCURRENT_NESTINGS", None)
    get_settings.cache_clear()


@pytest.fixture()
def thread_client(client):
    return client


def test_process_and_thread_modes_give_byte_identical_answers(process_client, thread_client):
    app.dependency_overrides[get_settings] = lambda: Settings(nesting_executor="process")
    try:
        mine = process_client.post("/v1/nesting", json=body())
    finally:
        app.dependency_overrides.pop(get_settings, None)
    other = thread_client.post("/v1/nesting", json=body())
    assert mine.status_code == other.status_code == 200
    assert mine.content == other.content


def test_workers_are_other_processes_and_warm(process_client):
    assert app.state.nesting_runner.mode == "process" and app.state.nesting_runner.workers == 2
    runner = NestingRunner("process", 1, job=pid_job)

    async def go():
        await runner.warm_up()
        try:
            return await runner.run([], [], None, None, 5)
        finally:
            runner.shutdown()
    assert asyncio.run(go()) != os.getpid()


def test_cooperative_timeout_inside_a_worker_is_a_clean_503(process_client):
    app.dependency_overrides[get_settings] = lambda: Settings(nesting_executor="process", nesting_timeout_s=0.05)
    try:
        r = process_client.post("/v1/nesting", json={"panels": heavy_panels(500)})
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code == 503 and r.json()["code"] == "nesting_timeout"
    assert process_client.post("/v1/nesting", json=body()).status_code == 200  # the workers are fine afterwards


def test_a_job_that_ignores_its_deadline_is_killed_and_workers_are_replaced():
    async def go():
        runner = NestingRunner("process", 1, job=hang_job)
        await runner.warm_up()
        old = list(runner._pool._processes.values())
        started = time.perf_counter()
        with pytest.raises(NestingTimeout):
            await runner.run([], [], None, None, 0.2)
        elapsed = time.perf_counter() - started
        assert elapsed < 3, f"hard timeout took {elapsed:.1f}s"  # 0.2 * 1.5 + 1 s grace
        assert runner.restarts == 1
        for proc in old:
            proc.join(5)
            assert not proc.is_alive(), "the stuck worker must be terminated, not left burning CPU"
        runner.job = pid_job  # next call gets a fresh pool
        assert await runner.run([], [], None, None, 5) != old[0].pid
        runner.shutdown()
    asyncio.run(go())


def test_a_dead_worker_is_a_retryable_503_then_recovers(process_client):
    runner = app.state.nesting_runner
    real_job = runner.job
    runner.job = die_job
    try:
        r = process_client.post("/v1/nesting", json=body())
    finally:
        runner.job = real_job
    assert r.status_code == 503 and r.json()["code"] == "busy" and r.headers["retry-after"] == "1"
    assert process_client.post("/v1/nesting", json=body()).status_code == 200


def test_invalid_mode_is_refused():
    with pytest.raises(ValueError, match="process.*thread"):
        NestingRunner("fork")


def test_thread_mode_needs_no_warm_up():
    async def go():
        runner = NestingRunner("thread", 2)
        await runner.warm_up()
        assert runner._pool is None
    asyncio.run(go())
