"""Phase 11: rate limiting — per caller, shared across routes, heavier on nesting, never on probes."""
import time

import pytest

from app.config import Settings, get_settings
from app.main import app
from app.ratelimit import reset_limits
from tests.conftest import panel
from tests.test_auth import SECRET, bearer, token

BOM = "/v1/bom"
BODY = {"panels": []}


def nesting_body():
    return {"panels": [panel("a", 600, 400), panel("b", 500, 300)]}


@pytest.fixture()
def limits():
    reset_limits()

    def _apply(**kw):
        defaults = {"rate_limit": "100000/minute", "rate_limit_heavy": "100000/minute", "auth_fail_limit": "100000/minute"}
        app.dependency_overrides[get_settings] = lambda: Settings(**{**defaults, **kw})

    yield _apply
    app.dependency_overrides.pop(get_settings, None)
    reset_limits()


def statuses(client, n, path=BOM, headers=None, body=BODY):
    return [client.post(path, json=body, headers=headers or {}).status_code for _ in range(n)]


def test_the_61st_request_in_a_minute_is_429(client, limits):
    limits(rate_limit="60/minute")
    codes = statuses(client, 61)
    assert codes[:60] == [200] * 60 and codes[60] == 429


def test_429_envelope_and_retry_after(client, limits):
    limits(rate_limit="2/minute")
    statuses(client, 2)
    r = client.post(BOM, json=BODY)
    assert r.status_code == 429
    assert r.json() == {"detail": "Too many requests; slow down", "code": "rate_limited"}
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert r.headers["x-rules-version"] and r.headers["x-request-id"]


def test_429_is_readable_by_the_browser(client, limits):
    limits(rate_limit="1/minute")
    statuses(client, 1)
    r = client.post(BOM, json=BODY, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 429
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_one_bucket_for_all_v1_routes_of_a_caller(client, limits):
    limits(rate_limit="4/minute")
    paths = [("post", BOM), ("post", "/v1/joints"), ("post", "/v1/hardware-plan"), ("get", "/v1/catalog/materials")]
    codes = []
    for method, path in paths:
        codes.append(getattr(client, method)(path, **({"json": BODY} if method == "post" else {})).status_code)
    assert codes == [200] * 4
    assert client.post("/v1/assembly", json=BODY).status_code == 429


def test_callers_have_separate_buckets(client, limits):
    limits(rate_limit="2/minute", api_keys="k1,k2")
    assert statuses(client, 3, headers={"X-API-Key": "k1"}) == [200, 200, 429]
    assert statuses(client, 2, headers={"X-API-Key": "k2"}) == [200, 200]  # k2 untouched by k1's spending


def test_users_have_separate_buckets_even_from_one_ip(client, limits):
    limits(rate_limit="2/minute", jwt_secret=SECRET)
    alice, bob = bearer(token(sub="alice")), bearer(token(sub="bob"))
    assert statuses(client, 3, headers=alice) == [200, 200, 429]
    assert statuses(client, 2, headers=bob) == [200, 200]
    assert statuses(client, 1, headers=bearer(token(sub="alice"))) == [429]  # a fresh token, same user, same bucket


def test_a_user_and_an_api_key_do_not_share_a_bucket(client, limits):
    limits(rate_limit="1/minute", jwt_secret=SECRET, api_keys="k1")
    assert statuses(client, 2, headers={"X-API-Key": "k1"}) == [200, 429]
    assert statuses(client, 1, headers=bearer(token())) == [200]


def test_anonymous_callers_are_limited_by_ip(client, limits):
    limits(rate_limit="2/minute")
    assert statuses(client, 3) == [200, 200, 429]


def test_failed_authentication_does_not_spend_the_callers_budget(client, limits):
    limits(rate_limit="2/minute", api_keys="k1")
    assert statuses(client, 5, headers={"X-API-Key": "bad"}) == [401] * 5
    assert statuses(client, 3, headers={"X-API-Key": "k1"}) == [200, 200, 429]


def test_nesting_has_a_tighter_limit_on_top(client, limits):
    limits(rate_limit="100/minute", rate_limit_heavy="3/minute")
    body = nesting_body()
    assert statuses(client, 4, "/v1/nesting", body=body) == [200, 200, 200, 429]
    assert client.post(BOM, json=BODY).status_code == 200  # the cheap routes keep their own, larger budget


def test_nesting_also_spends_the_shared_budget(client, limits):
    limits(rate_limit="2/minute", rate_limit_heavy="100/minute")
    assert statuses(client, 3, "/v1/nesting", body=nesting_body()) == [200, 200, 429]
    assert client.post(BOM, json=BODY).status_code == 429


def test_probes_are_never_limited(client, limits):
    limits(rate_limit="1/minute")
    assert [client.get("/health").status_code for _ in range(50)] == [200] * 50
    assert [client.get("/v1/version").status_code for _ in range(50)] == [200] * 50


def test_the_window_moves_on(client, limits):
    limits(rate_limit="2/second")
    assert statuses(client, 3) == [200, 200, 429]
    time.sleep(1.1)
    assert statuses(client, 2) == [200, 200]


def test_limit_is_read_per_request_from_settings(client, limits):
    limits(rate_limit="1/minute")
    assert statuses(client, 2) == [200, 429]
    limits(rate_limit="100/minute")  # operators change the env: the next request uses it
    assert statuses(client, 1) == [200]


def test_a_rejected_request_does_not_run_the_expensive_work(client, limits, monkeypatch):
    limits(rate_limit="1/minute")
    calls = []
    import app.routers.bom as bom_router

    real = bom_router.compute_bom
    monkeypatch.setattr(bom_router, "compute_bom", lambda *a, **k: calls.append(1) or real(*a, **k))
    statuses(client, 3)
    assert len(calls) == 1
