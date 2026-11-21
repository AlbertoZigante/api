# Security: authentication, rate limits, logs (phase 11)

## Authentication (`app/auth.py`)
Every `/v1/*` route requires a credential once any is configured; `/health` and `/v1/version` stay open (platform probes).

| setting | meaning |
|---|---|
| `API_KEYS=k1,k2` | **beta gate**: `X-API-Key`. In a browser build the key is visible to anyone: it keeps casual traffic out, it is not an identity |
| `JWT_SECRET` (HS256, >= 32 chars) or `JWT_PUBLIC_KEY` (RS256/ES256...) | **per-user**: `Authorization: Bearer <jwt>` from Supabase / Auth0 / `scripts/issue_token.py` |
| `JWT_ALGORITHMS`, `JWT_AUDIENCE`, `JWT_ISSUER`, `JWT_LEEWAY_S` | algorithm allow-list (ONE family), required `aud` / `iss` when set, clock skew (default 10 s) |
| `ENV=production` | the app **refuses to start** without `API_KEYS` or a JWT key; `/docs` and `/openapi.json` are off unless `DOCS_ENABLED=true` |

Either credential works when both are configured; a credential that is **presented and invalid is always a 401** (no silent fallback).
`exp` and `sub` are mandatory. Errors (envelope `{code, detail}`, `WWW-Authenticate: Bearer`):
`invalid_api_key`, `unauthorized` (nothing presented), `invalid_token`, `token_expired`. Details never echo the token / key.

Protections, each with a test (`tests/test_auth.py`): `alg: none`, wrong signature, **algorithm confusion** (RSA public key used as an HMAC
secret), mixed symmetric / asymmetric config refused at startup, short HS secrets refused, oversized tokens, missing / wrong
`aud` / `iss`, constant-time key comparison, brute-force throttle (`AUTH_FAIL_LIMIT`, default 20 failures / minute / IP, then 429; a correct credential still works).

## Rate limits (`app/ratelimit.py`, slowapi's limiter + `limits` moving window)
`RATE_LIMIT` (default **60/minute**) is one bucket per caller across all `/v1` routes; `/v1/nesting` also spends `RATE_LIMIT_HEAVY`
(default 10/minute). Caller = user (`sub`), else API key (hash), else client IP. 429 -> `{code: "rate_limited"}` + `Retry-After`
(exposed to the browser). Failed authentications do not spend the caller's budget. Counters are **per process**: with several instances use
`RATE_LIMIT_STORAGE=redis://...`. Behind a proxy the client IP comes from `X-Forwarded-For` (`--proxy-headers`, `FORWARDED_ALLOW_IPS`):
trust it only when the platform proxy is the sole way in.

## Nesting does not starve the server (`app/nesting_runner.py`)
Nesting is CPU-bound Python. In a thread it holds the GIL and the event loop (health, auth, cheap routes) stalls; in the loadtest
(`scripts/loadtest.py`, 16 clients on 1 core) `/health` p95 was ~290 ms and `/v1/bom` p95 ~950 ms. The default `NESTING_EXECUTOR=process`
runs it in `MAX_CONCURRENT_NESTINGS` pre-warmed worker processes (lower priority): `/health` p95 ~130 ms, `/v1/bom` ~140 ms in the same
run. The cooperative deadline runs inside the worker; a hard timeout (1.5 x budget + 1 s) kills the workers and starts new ones; a dead
worker is a retryable `503 busy`.

## Logs (`app/logs.py`, `AccessLogMiddleware`)
One JSON line per request on stdout: `requestId` (accepted from `X-Request-ID` when `[A-Za-z0-9._-]{1,64}`, else generated, echoed back),
method, path (**no query string**), status, ms, client IP, `caller` (`user:<sub>` / `api_key:<hash12>` / `anonymous:<ip>`), `authError`.
Never bodies, tokens, or keys. Unhandled exceptions: stack trace in the log with the request id, a generic `{code: "internal_error"}` to the client.

## Verification
`tests/test_auth.py` (41), `tests/test_rate_limit.py` (15), `tests/test_nesting_runner.py` (6 + the existing nesting suite),
`python scripts/loadtest.py` (CI: fails when `/health` p95 / max or `/v1/bom` p95 exceed their budgets, or a nesting call ends in anything but 200 / 503 / 429).
