from app.config import Settings, get_settings
from app.deps import get_catalog
from app.main import app
from app.routers.catalog import catalog_etag


def test_first_request_returns_etag_and_revalidation_policy(client):
    r = client.get("/v1/catalog/materials")
    assert r.status_code == 200
    assert r.headers["etag"].startswith('"') and r.headers["etag"].endswith('"')
    assert r.headers["cache-control"] == "no-cache"
    assert isinstance(r.json(), list) and r.json()[0]["name"]


def test_etag_is_stable_across_requests(client):
    assert client.get("/v1/catalog/materials").headers["etag"] == client.get("/v1/catalog/materials").headers["etag"]


def test_matching_if_none_match_gives_304_with_empty_body(client):
    etag = client.get("/v1/catalog/materials").headers["etag"]
    r = client.get("/v1/catalog/materials", headers={"If-None-Match": etag})
    assert r.status_code == 304 and r.content == b"" and r.headers["etag"] == etag


def test_weak_and_list_forms_match(client):
    etag = client.get("/v1/catalog/materials").headers["etag"]
    assert client.get("/v1/catalog/materials", headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    assert client.get("/v1/catalog/materials", headers={"If-None-Match": f'"old", {etag}'}).status_code == 304
    assert client.get("/v1/catalog/materials", headers={"If-None-Match": "*"}).status_code == 304


def test_stale_etag_gets_full_body(client):
    r = client.get("/v1/catalog/materials", headers={"If-None-Match": '"stale"'})
    assert r.status_code == 200 and r.json()


def test_etag_changes_when_catalog_changes(client, catalog):
    original = client.get("/v1/catalog/materials").headers["etag"]
    changed = [catalog[0].model_copy(update={"price_per_sheet": catalog[0].price_per_sheet + 1}), *catalog[1:]]
    app.dependency_overrides[get_catalog] = lambda: changed
    try:
        r = client.get("/v1/catalog/materials", headers={"If-None-Match": original})
        assert r.status_code == 200 and r.headers["etag"] != original
    finally:
        app.dependency_overrides.clear()


def test_304_still_requires_auth_and_exposes_headers_to_the_browser(client):
    app.dependency_overrides[get_settings] = lambda: Settings(api_keys="k1")
    try:
        assert client.get("/v1/catalog/materials", headers={"If-None-Match": "*"}).status_code == 401
        ok = client.get("/v1/catalog/materials", headers={"X-API-Key": "k1", "Origin": "http://localhost:5173"})
        assert ok.status_code == 200 and "etag" in ok.headers["access-control-expose-headers"].lower()
    finally:
        app.dependency_overrides.clear()


def test_catalog_etag_is_order_independent_for_keys():
    assert catalog_etag([{"a": 1, "b": 2}]) == catalog_etag([{"b": 2, "a": 1}])
