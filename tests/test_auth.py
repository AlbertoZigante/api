"""Phase 11: authentication — beta API key, per-user JWT, startup validation, request ids, structured logs."""
import base64
import hashlib
import hmac
import json
import logging
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import MAX_TOKEN_CHARS, jwt_config, validate_settings
from app.config import Settings, get_settings
from app.logs import JsonFormatter
from app.main import app, create_app
from app.ratelimit import reset_limits

SECRET = "s" * 40
OTHER = "o" * 40
BODY = {"panels": []}
BOM = "/v1/bom"


@pytest.fixture()
def configure():
    """configure(**settings) -> TestClient-ready app with those settings; restored afterwards."""
    reset_limits()

    def _apply(**kw):
        defaults = {"rate_limit": "100000/minute", "rate_limit_heavy": "100000/minute", "auth_fail_limit": "100000/minute"}
        app.dependency_overrides[get_settings] = lambda: Settings(**{**defaults, **kw})

    yield _apply
    app.dependency_overrides.pop(get_settings, None)


def token(secret=SECRET, alg="HS256", **claims):
    now = int(time.time())
    payload = {"sub": "user-1", "exp": now + 600, **claims}
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, secret, algorithm=alg)


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def post(client, headers=None):
    return client.post(BOM, json=BODY, headers=headers or {})


# ------------------------------------------------------------------ open / API key
def test_nothing_configured_is_open(client, configure):
    configure()
    assert post(client).status_code == 200


def test_api_key_gate(client, configure):
    configure(api_keys="k1, k2")
    r = post(client)
    assert r.status_code == 401 and r.json() == {"detail": "Invalid or missing API key", "code": "invalid_api_key"}
    assert r.headers["www-authenticate"] == "Bearer"
    assert post(client, {"X-API-Key": "nope"}).status_code == 401
    assert post(client, {"X-API-Key": ""}).status_code == 401
    assert post(client, {"X-API-Key": "k1"}).status_code == 200
    assert post(client, {"X-API-Key": "k2"}).status_code == 200
    assert post(client, {"X-API-Key": "k1 "}).status_code == 401  # no trimming of the presented key


def test_bearer_alone_is_not_an_api_key(client, configure):
    configure(api_keys="k1")
    assert post(client, bearer("k1")).status_code == 401


# ------------------------------------------------------------------ JWT
def test_jwt_valid_and_missing(client, configure):
    configure(jwt_secret=SECRET)
    assert post(client, bearer(token())).status_code == 200
    r = post(client)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    assert r.headers["www-authenticate"] == "Bearer"
    assert post(client, {"Authorization": f"bearer {token()}"}).status_code == 200  # scheme is case-insensitive
    assert post(client, {"Authorization": f"Basic {token()}"}).json()["code"] == "unauthorized"


@pytest.mark.parametrize("bad", ["abc", "a.b.c", "", " "])
def test_garbage_tokens_are_invalid_token(client, configure, bad):
    configure(jwt_secret=SECRET)
    r = post(client, {"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401 and r.json()["code"] in ("invalid_token", "unauthorized")


def test_expired_token(client, configure):
    configure(jwt_secret=SECRET, jwt_leeway_s=0)
    r = post(client, bearer(token(exp=int(time.time()) - 5)))
    assert r.status_code == 401 and r.json() == {"detail": "Token expired", "code": "token_expired"}
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


def test_clock_leeway_is_small_and_explicit(client, configure):
    configure(jwt_secret=SECRET, jwt_leeway_s=10)
    assert post(client, bearer(token(exp=int(time.time()) - 5))).status_code == 200
    assert post(client, bearer(token(exp=int(time.time()) - 60))).status_code == 401


def test_wrong_signature_and_unsigned_tokens(client, configure):
    configure(jwt_secret=SECRET)
    assert post(client, bearer(token(secret=OTHER))).json()["code"] == "invalid_token"
    unsigned = jwt.encode({"sub": "x", "exp": int(time.time()) + 600}, key=None, algorithm="none")
    assert post(client, bearer(unsigned)).json()["code"] == "invalid_token"


def test_other_symmetric_algorithm_is_rejected_when_not_allowed(client, configure):
    configure(jwt_secret=SECRET, jwt_algorithms="HS256")
    assert post(client, bearer(token(alg="HS512"))).json()["code"] == "invalid_token"


def test_the_algorithm_allow_list_is_exactly_what_is_configured(client, configure):
    configure(jwt_secret=SECRET, jwt_algorithms="HS512")
    assert post(client, bearer(token(alg="HS512"))).status_code == 200
    assert post(client, bearer(token(alg="HS256"))).json()["code"] == "invalid_token"


@pytest.mark.parametrize("claims", [{"exp": None}, {"sub": None}, {"sub": ""}, {"nbf": int(time.time()) + 3600}])
def test_required_and_time_claims(client, configure, claims):
    configure(jwt_secret=SECRET, jwt_leeway_s=0)
    assert post(client, bearer(token(**claims))).status_code == 401


def test_audience_and_issuer_are_enforced_when_configured(client, configure):
    configure(jwt_secret=SECRET, jwt_audience="diy-api", jwt_issuer="https://auth.example")
    ok = token(aud="diy-api", iss="https://auth.example")
    assert post(client, bearer(ok)).status_code == 200
    for bad in (token(), token(aud="other", iss="https://auth.example"), token(aud="diy-api", iss="https://evil"),
                token(aud="diy-api")):
        assert post(client, bearer(bad)).json()["code"] == "invalid_token"


def test_audience_not_checked_when_not_configured(client, configure):
    configure(jwt_secret=SECRET)
    assert post(client, bearer(token(aud="whatever"))).status_code == 200


def test_oversized_token_is_rejected_before_decoding(client, configure):
    configure(jwt_secret=SECRET)
    big = token(pad="x" * (MAX_TOKEN_CHARS + 10))
    assert len(big) > MAX_TOKEN_CHARS and post(client, bearer(big)).json()["code"] == "invalid_token"


def test_errors_never_echo_credentials(client, configure):
    configure(jwt_secret=SECRET, api_keys="topsecretkey")
    t = token(secret=OTHER)
    for headers in (bearer(t), {"X-API-Key": "wrongkey123"}):
        body = post(client, headers).text
        assert t not in body and "wrongkey123" not in body and SECRET not in body and "topsecretkey" not in body


# ------------------------------------------------------------------ asymmetric keys / algorithm confusion
def forge_hs256(payload: dict, secret: bytes) -> str:
    """Hand-made HS256 token (PyJWT itself refuses to sign with a PEM key — an attacker would not)."""
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{b64(json.dumps(payload).encode())}"
    mac = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(mac)}"


@pytest.fixture(scope="module")
def rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private.decode(), public.decode()


def test_rs256(client, configure, rsa_pair):
    private, public = rsa_pair
    configure(jwt_public_key=public, jwt_algorithms="RS256")
    assert post(client, bearer(token(secret=private, alg="RS256"))).status_code == 200
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    assert post(client, bearer(token(secret=other, alg="RS256"))).json()["code"] == "invalid_token"


def test_algorithm_confusion_public_key_as_hmac_secret(client, configure, rsa_pair):
    """The classic attack: sign HS256 with the (public) RSA key text as the secret. Must never validate."""
    _, public = rsa_pair
    configure(jwt_public_key=public, jwt_algorithms="RS256")
    forged = forge_hs256({"sub": "attacker", "exp": int(time.time()) + 600}, public.encode())
    assert post(client, bearer(forged)).json()["code"] == "invalid_token"
    configure(jwt_public_key=public, jwt_algorithms="RS256,HS256")  # and the unsafe mix is refused outright
    with pytest.raises(ValueError):
        jwt_config(Settings(jwt_public_key=public, jwt_algorithms="RS256,HS256"))


# ------------------------------------------------------------------ both methods
def test_either_credential_works_but_a_bad_one_is_never_ignored(client, configure):
    configure(api_keys="k1", jwt_secret=SECRET)
    assert post(client, {"X-API-Key": "k1"}).status_code == 200
    assert post(client, bearer(token())).status_code == 200
    assert post(client, {**bearer(token(secret=OTHER)), "X-API-Key": "k1"}).status_code == 401  # bad token + good key
    assert post(client, {**bearer(token()), "X-API-Key": "bad"}).status_code == 200  # good token wins; key not consulted
    assert post(client).json()["code"] == "unauthorized"


# ------------------------------------------------------------------ public routes, CORS
def test_health_version_and_preflight_stay_open(client, configure):
    configure(api_keys="k1", jwt_secret=SECRET)
    assert client.get("/health").status_code == 200
    assert client.get("/v1/version").status_code == 200
    r = client.options(BOM, headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                     "Access-Control-Request-Headers": "authorization,x-api-key,content-type"})
    assert r.status_code == 200
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed and "x-api-key" in allowed
    assert client.get("/v1/catalog/materials").status_code == 401  # a protected GET


def test_every_v1_route_is_protected(client, configure):
    configure(api_keys="k1")
    for method, path in (("post", "/v1/bom"), ("post", "/v1/nesting"), ("post", "/v1/joints"),
                         ("post", "/v1/hardware-plan"), ("post", "/v1/assembly"), ("get", "/v1/catalog/materials")):
        r = getattr(client, method)(path, **({"json": BODY} if method == "post" else {}))
        assert r.status_code == 401, path


# ------------------------------------------------------------------ failed-auth throttle
def test_failed_attempts_are_throttled_per_ip(client, configure):
    configure(api_keys="k1", auth_fail_limit="3/minute")
    assert [post(client, {"X-API-Key": f"bad{i}"}).status_code for i in range(3)] == [401, 401, 401]
    r = post(client, {"X-API-Key": "bad4"})
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and "retry-after" in r.headers
    assert post(client, {"X-API-Key": "k1"}).status_code == 200  # a legitimate caller is not locked out


# ------------------------------------------------------------------ configuration safety
@pytest.mark.parametrize("kw,fragment", [
    ({"jwt_secret": "short"}, "at least 32"),
    ({"jwt_secret": SECRET, "jwt_algorithms": "none"}, "none"),
    ({"jwt_secret": SECRET, "jwt_algorithms": "HS256,RS256"}, "mixes"),
    ({"jwt_secret": SECRET, "jwt_algorithms": "HS999"}, "unsupported"),
    ({"jwt_public_key": "x", "jwt_algorithms": "HS256"}, "at least 32"),
    ({"jwt_secret": SECRET, "jwt_algorithms": "RS256"}, "JWT_PUBLIC_KEY"),
    ({"jwt_secret": SECRET, "jwt_algorithms": ""}, "empty"),
])
def test_unsafe_jwt_configuration_is_refused(kw, fragment):
    with pytest.raises(ValueError, match=fragment):
        jwt_config(Settings(**kw))


def test_jwt_off_when_no_key_is_configured():
    assert jwt_config(Settings()) is None


def test_production_refuses_to_run_open(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="refusing to run open"), TestClient(create_app()):
            pass
        with pytest.raises(RuntimeError):
            validate_settings(Settings(env="production"))
        validate_settings(Settings(env="production", api_keys="k"))
        validate_settings(Settings(env="production", jwt_secret=SECRET))
        validate_settings(Settings(env="development"))
    finally:
        monkeypatch.setenv("ENV", "development")
        get_settings.cache_clear()


def test_docs_are_off_in_production_unless_enabled(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("API_KEYS", "k1")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as c:
            assert c.get("/openapi.json").status_code == 404 and c.get("/docs").status_code == 404
        monkeypatch.setenv("DOCS_ENABLED", "true")
        get_settings.cache_clear()
        with TestClient(create_app()) as c:
            assert c.get("/openapi.json").status_code == 200
    finally:
        monkeypatch.setenv("ENV", "development")
        monkeypatch.setenv("API_KEYS", "")
        monkeypatch.delenv("DOCS_ENABLED", raising=False)
        get_settings.cache_clear()


# ------------------------------------------------------------------ request ids + structured logs
@pytest.fixture()
def log_lines():
    lines: list[dict] = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(json.loads(JsonFormatter().format(record)))

    handler = Collect()
    logger = logging.getLogger("diy")
    logger.addHandler(handler)
    yield lines
    logger.removeHandler(handler)


def test_request_id_is_echoed_or_generated(client, configure, log_lines):
    configure()
    r = client.get("/health", headers={"X-Request-ID": "abc-123_X.9"})
    assert r.headers["x-request-id"] == "abc-123_X.9"
    for evil in ("a b", "x" * 65, "a\tb", "<script>"):
        got = client.get("/health", headers={"X-Request-ID": evil}).headers["x-request-id"]
        assert got != evil and len(got) == 32
    assert any(line["event"] == "request" and line["requestId"] == "abc-123_X.9" for line in log_lines)


def test_access_log_has_identity_but_no_secrets(client, configure, log_lines):
    configure(api_keys="supersecretkey", jwt_secret=SECRET)
    post(client, {"X-API-Key": "supersecretkey"})
    post(client, bearer(token(sub="alice")))
    post(client, {"X-API-Key": "wrong-key-value"})
    text = json.dumps(log_lines)
    assert "supersecretkey" not in text and "wrong-key-value" not in text and SECRET not in text
    lines = [line for line in log_lines if line["event"] == "request" and line["path"] == BOM]
    assert [line["status"] for line in lines] == [200, 200, 401]
    assert lines[0]["caller"].startswith("api_key:") and len(lines[0]["caller"]) == len("api_key:") + 12
    assert lines[1]["caller"] == "user:alice"
    assert lines[2]["caller"] is None and lines[2]["authError"] == "invalid_api_key" and lines[2]["level"] == "warning"
    assert all(isinstance(line["ms"], float) and "?" not in line["path"] for line in lines)


def test_query_string_is_not_logged(client, configure, log_lines):
    configure()
    client.get("/health?token=SECRETVALUE")
    assert "SECRETVALUE" not in json.dumps(log_lines)


def test_unhandled_errors_are_generic_and_logged(configure, log_lines):
    configure()
    boom = create_app()

    @boom.get("/boom")
    def _boom():
        raise RuntimeError("internal detail with a password=hunter2")

    with TestClient(boom, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500 and r.json() == {"code": "internal_error", "detail": "Internal server error"}
    assert "hunter2" not in r.text and r.headers["x-request-id"]
    errors = [line for line in log_lines if line["event"] == "unhandled_error"]
    assert errors and errors[0]["requestId"] == r.headers["x-request-id"] and "RuntimeError" in errors[0]["exception"]


# ------------------------------------------------------------------ the token-issuing script
def test_issue_token_script_makes_tokens_the_api_accepts(client, configure):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from issue_token import issue

    configure(jwt_secret=SECRET, jwt_audience="diy-api", jwt_issuer="me")
    good = issue(SECRET, "alberto", 5, aud="diy-api", iss="me")
    assert post(client, bearer(good)).status_code == 200
    assert post(client, bearer(issue(SECRET, "alberto", 5))).status_code == 401  # no aud / iss: refused
    assert post(client, bearer(issue(SECRET, "alberto", -5, aud="diy-api", iss="me"))).json()["code"] == "token_expired"
    with pytest.raises(SystemExit):
        issue("short", "x", 5)
    with pytest.raises(SystemExit):
        issue(SECRET, "", 5)
