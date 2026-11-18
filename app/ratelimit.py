"""RATE LIMITING on slowapi's Limiter (storage + moving-window strategy from `limits`), applied as FastAPI
dependencies AFTER authentication so the bucket is the caller's identity (user / API key), not just an IP.

- `rate_limit()`        every /v1 route: one shared bucket per caller (settings.rate_limit, default 60/minute)
- `rate_limit_heavy()`  /v1/nesting on top of it (settings.rate_limit_heavy, default 10/minute)
- `auth_failure_allowed` failed logins per client IP (settings.auth_fail_limit), so keys / tokens cannot be brute-forced
/health and /v1/version are never limited (platform probes). Storage is in-memory per process: with several
instances set RATE_LIMIT_STORAGE=redis://... or the effective limit is N x the configured one.
"""
from __future__ import annotations

import math
import time

from fastapi import Depends, Request
from limits import RateLimitItem, parse
from slowapi import Limiter

from .config import Settings, get_settings
from .errors import ApiError

limiter = Limiter(key_func=lambda request: "n/a", strategy="moving-window",
                  storage_uri=get_settings().rate_limit_storage)


def _item(spec: str) -> RateLimitItem:
    return parse(spec)


def _retry_after(item: RateLimitItem, *identifiers: str) -> int:
    try:
        reset = limiter.limiter.get_window_stats(item, *identifiers).reset_time
        return max(1, math.ceil(reset - time.time()))
    except Exception:  # noqa: BLE001 - a storage hiccup must not turn a 429 into a 500
        return 1


def _hit(spec: str, scope: str, key: str, detail: str) -> None:
    item = _item(spec)
    if not limiter.limiter.hit(item, scope, key):
        raise ApiError(429, "rate_limited", detail, headers={"Retry-After": str(_retry_after(item, scope, key))})


def auth_failure_allowed(ip: str, spec: str) -> bool:
    """Records one failed authentication of `ip`; False once the budget is spent."""
    return bool(limiter.limiter.hit(_item(spec), "authfail", ip))


def _caller(request: Request) -> str:
    p = getattr(request.state, "principal", None)
    return p.label if p else f"ip:{request.client.host if request.client else 'unknown'}"


def rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    _hit(settings.rate_limit, "api", _caller(request), "Too many requests; slow down")


def rate_limit_heavy(request: Request, settings: Settings = Depends(get_settings)) -> None:
    _hit(settings.rate_limit_heavy, "heavy", _caller(request), "Too many nesting requests; slow down")


def reset_limits() -> None:
    """Test helper: forget every counter."""
    limiter.reset()
