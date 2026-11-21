"""WHERE nesting runs. It is pure-Python CPU work of up to `nesting_timeout_s` per call; in a thread of the web process
it holds the GIL, and the event loop that answers /health, auth and the cheap routes gets starved (measured by
scripts/loadtest.py: /health p95 ~490 ms under nesting traffic). So the default is a small pool of WORKER PROCESSES:
the web process stays responsive whatever the workers are doing.

- mode "process" (default): `max_workers` spawned processes, pre-warmed at startup, lowered priority (nice) so the
  web process wins the CPU. The cooperative deadline runs INSIDE the worker; a hard timeout (a little above it) in
  the web process is the safety net: it kills the workers and starts fresh ones (a stuck job can't be cancelled).
- mode "thread": the old behaviour, in the default threadpool (tests, tiny deployments, debugging).
"""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import multiprocessing
import os
from typing import Any

from .services.nesting import NestingTimeout, nest_cut_list, now

HARD_TIMEOUT_FACTOR = 1.5
HARD_TIMEOUT_GRACE_S = 1.0


def _init_worker(nice: int) -> None:
    if nice and hasattr(os, "nice"):  # not on Windows
        try:
            os.nice(nice)
        except OSError:
            pass


def _warm() -> int:
    return os.getpid()


def _nest_job(rows: list[Any], catalog: list[Any], kerf_mm: Any, margin_mm: Any, timeout_s: float) -> Any:
    """Runs in the worker (module-level: picklable). The deadline starts HERE, after queueing and pickling."""
    return nest_cut_list(rows, catalog, kerf_mm=kerf_mm, edge_banding_margin_mm=margin_mm, deadline=now() + timeout_s)


class NestingRunner:
    def __init__(self, mode: str = "process", workers: int = 4, nice: int = 10, job: Any = None) -> None:
        if mode not in ("process", "thread"):
            raise ValueError(f"NESTING_EXECUTOR must be 'process' or 'thread', not {mode!r}")
        self.mode, self.workers, self.nice = mode, max(1, workers), nice
        self.job = job or _nest_job  # injectable (tests): must be a module-level function, it is pickled
        self._pool: cf.ProcessPoolExecutor | None = None
        self.restarts = 0

    def _new_pool(self) -> cf.ProcessPoolExecutor:
        return cf.ProcessPoolExecutor(max_workers=self.workers, mp_context=multiprocessing.get_context("spawn"),
                                      initializer=_init_worker, initargs=(self.nice,))

    async def warm_up(self) -> None:
        """Spawn every worker now (startup), not on the first user's request."""
        if self.mode != "process":
            return
        loop = asyncio.get_running_loop()
        self._pool = self._pool or self._new_pool()
        await asyncio.gather(*[loop.run_in_executor(self._pool, _warm) for _ in range(self.workers)])

    async def run(self, rows: list[Any], catalog: list[Any], kerf_mm: Any, margin_mm: Any, timeout_s: float) -> Any:
        """Results of nest_cut_list. Raises NestingTimeout (deadline passed, or hard timeout: workers replaced)."""
        loop = asyncio.get_running_loop()
        if self.mode == "thread":
            return await loop.run_in_executor(None, self.job, rows, catalog, kerf_mm, margin_mm, timeout_s)
        if self._pool is None:
            self._pool = self._new_pool()
        future = loop.run_in_executor(self._pool, self.job, rows, catalog, kerf_mm, margin_mm, timeout_s)
        try:
            return await asyncio.wait_for(future, timeout_s * HARD_TIMEOUT_FACTOR + HARD_TIMEOUT_GRACE_S)
        except TimeoutError:
            self._kill_workers()  # a job that ignores its own deadline must not occupy a worker forever
            raise NestingTimeout from None
        except cf.process.BrokenProcessPool:
            self._kill_workers()
            raise

    def _kill_workers(self) -> None:
        pool, self._pool = self._pool, None
        self.restarts += 1
        if pool is None:
            return
        for proc in list(getattr(pool, "_processes", {}).values()):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001 - already dead
                pass
        pool.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
