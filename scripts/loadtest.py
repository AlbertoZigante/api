"""Local load test (phase 11): heavy nesting traffic must not make /health (or the cheap routes) slow.

    python scripts/loadtest.py                      # starts its own uvicorn on a free port, ~15 s
    python scripts/loadtest.py --url http://localhost:8000 --api-key KEY --seconds 30

Scenario: N concurrent clients POST a heavy nesting request in a loop (--panels tiny panels, API max 500)
while a probe polls GET /health every 25 ms and POST /v1/bom every 250 ms. The test FAILS (exit 1) when
  - /health p95 latency > --health-p95-ms (default 250) or max > --health-max-ms (default 1500)
  - the cheap route (/v1/bom) p95 is above 4x that budget
  - any nesting request ends in anything but 200 / 503 (busy, timeout) / 429 (rate limited), or a connection error
Everything is reported: throughput, status histogram, latency percentiles.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def heavy_body(n: int = 500) -> dict:
    return {"panels": [{"id": f"p{i}", "name": f"p{i}", "pieceCode": f"P-{i}", "width": 10 + (i * 7) % 50,
                        "height": 10 + (i * 13) % 50, "thickness": 18, "material": "Melamine White 18mm"}
                       for i in range(n)]}


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def wait_ready(client: httpx.AsyncClient, url: str, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if (await client.get(f"{url}/health")).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.2)
    raise SystemExit("server did not become ready")


async def run(url: str, headers: dict, seconds: float, clients: int, panels: int) -> dict:
    body = heavy_body(panels)
    stop = time.monotonic() + seconds
    nest_status: Counter[str] = Counter()
    nest_ms: list[float] = []
    health_ms: list[float] = []
    bom_ms: list[float] = []
    health_fail: Counter[str] = Counter()

    limits = httpx.Limits(max_connections=clients + 8)
    async with httpx.AsyncClient(timeout=60, limits=limits) as http:
        await wait_ready(http, url)

        async def hammer() -> None:
            while time.monotonic() < stop:
                t = time.perf_counter()
                try:
                    r = await http.post(f"{url}/v1/nesting", json=body, headers=headers)
                    nest_status[str(r.status_code)] += 1
                except httpx.HTTPError as exc:
                    nest_status[type(exc).__name__] += 1
                nest_ms.append((time.perf_counter() - t) * 1000)

        async def probe(path: str, every: float, sink: list[float], method: str = "get") -> None:
            while time.monotonic() < stop:
                t = time.perf_counter()
                try:
                    r = await (http.get(f"{url}{path}", headers=headers) if method == "get"
                               else http.post(f"{url}{path}", json={"panels": []}, headers=headers))
                    if r.status_code != 200:
                        health_fail[f"{path} {r.status_code}"] += 1
                except httpx.HTTPError as exc:
                    health_fail[f"{path} {type(exc).__name__}"] += 1
                sink.append((time.perf_counter() - t) * 1000)
                await asyncio.sleep(every)

        await asyncio.gather(*[hammer() for _ in range(clients)], probe("/health", 0.025, health_ms),
                             probe("/v1/bom", 0.25, bom_ms, "post"))
    return {"nest_status": nest_status, "nest_ms": nest_ms, "health_ms": health_ms, "bom_ms": bom_ms,
            "health_fail": health_fail, "seconds": seconds}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--seconds", type=float, default=12)
    ap.add_argument("--clients", type=int, default=16)
    ap.add_argument("--panels", type=int, default=200, help="size of each nesting request (500 = the API maximum)")
    ap.add_argument("--health-p95-ms", type=float, default=250)
    ap.add_argument("--health-max-ms", type=float, default=1500)
    args = ap.parse_args()

    server = None
    url = args.url
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    if not url:
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "RATE_LIMIT": "1000000/minute", "RATE_LIMIT_HEAVY": "1000000/minute", "API_KEYS": "",
               "ENV": "development"}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level",
                                   "warning"], cwd=ROOT, env=env)
    try:
        res = asyncio.run(run(url, headers, args.seconds, args.clients, args.panels))
    finally:
        if server:
            server.terminate()
            server.wait(10)

    h, b, n = res["health_ms"], res["bom_ms"], res["nest_ms"]
    print(f"nesting requests : {sum(res['nest_status'].values())} in {res['seconds']:.0f}s "
          f"({sum(res['nest_status'].values()) / res['seconds']:.1f}/s)  statuses {dict(res['nest_status'])}")
    print(f"nesting latency  : p50 {pct(n, 50):.0f} ms  p95 {pct(n, 95):.0f} ms  max {max(n, default=0):.0f} ms")
    for label, v in (("/health", h), ("/v1/bom (cheap)", b)):
        print(f"{label:<17}: n={len(v)}  p50 {statistics.median(v):.1f} ms  p95 {pct(v, 95):.1f} ms  "
              f"max {max(v):.1f} ms")
    problems = []
    if pct(h, 95) > args.health_p95_ms:
        problems.append(f"/health p95 {pct(h, 95):.0f} ms > {args.health_p95_ms:.0f}")
    if max(h) > args.health_max_ms:
        problems.append(f"/health max {max(h):.0f} ms > {args.health_max_ms:.0f}")
    if pct(b, 95) > 4 * args.health_p95_ms:
        problems.append(f"/v1/bom p95 {pct(b, 95):.0f} ms > {4 * args.health_p95_ms:.0f}")
    bad = {k: v for k, v in res["nest_status"].items() if k not in ("200", "503", "429")}
    if bad:
        problems.append(f"unexpected nesting outcomes {bad}")
    if res["health_fail"]:
        problems.append(f"probe failures {dict(res['health_fail'])}")
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print("OK: heavy nesting does not starve /health")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
