"""AUTHENTICATION: who is calling (beta API key and / or per-user JWT), never what they may do.

Modes (settings.py): nothing configured = open (development); API_KEYS = beta gate (X-API-Key); JWT_* = per-user
bearer tokens. With either configured a request MUST present a valid credential; with both, either one works.
A credential that is PRESENTED and invalid is always a 401 (never a silent fall-through to another method).

Security notes (each has a test in tests/test_auth.py):
- algorithms are an allow-list, one family only, never "none"; the key kind must match the family, so an RS256
  public key can never be used as an HS256 secret (algorithm confusion)
- exp and sub are mandatory; aud / iss are enforced when configured; a little clock leeway only
- keys are compared in constant time; errors never echo token / key contents
- repeated failures from one IP are throttled (429) so the gate cannot be brute-forced
- the principal id used for limits / logs is a hash prefix for API keys (the key itself is never logged)
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request

from .config import Settings, get_settings
from .errors import ApiError
from .ratelimit import auth_failure_allowed

SYMMETRIC = frozenset({"HS256", "HS384", "HS512"})
ASYMMETRIC = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA"})
MAX_TOKEN_CHARS = 4096
MIN_HS_SECRET_CHARS = 32


@dataclass(frozen=True)
class Principal:
    kind: str  # "anonymous" | "api_key" | "user"
    id: str  # ip | sha256 prefix of the key | JWT `sub` — never a secret

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.id}"


@dataclass(frozen=True)
class JwtConfig:
    key: str
    algorithms: list[str]


def jwt_config(settings: Settings) -> JwtConfig | None:
    """The validated JWT setup, None when JWT is off. Raises ValueError on an unsafe / inconsistent one."""
    algs = settings.jwt_algorithm_list
    if not settings.jwt_secret and not settings.jwt_public_key:
        return None
    if not algs:
        raise ValueError("JWT_ALGORITHMS is empty")
    if any(a.lower() == "none" for a in algs):
        raise ValueError("JWT_ALGORITHMS must never contain 'none'")
    unknown = [a for a in algs if a not in SYMMETRIC | ASYMMETRIC]
    if unknown:
        raise ValueError(f"unsupported JWT algorithm(s): {', '.join(unknown)}")
    sym, asym = [a for a in algs if a in SYMMETRIC], [a for a in algs if a in ASYMMETRIC]
    if sym and asym:
        raise ValueError("JWT_ALGORITHMS mixes symmetric and asymmetric algorithms (algorithm-confusion risk)")
    if sym:
        if len(settings.jwt_secret) < MIN_HS_SECRET_CHARS:
            raise ValueError(f"JWT_SECRET must be at least {MIN_HS_SECRET_CHARS} characters for {', '.join(sym)}")
        return JwtConfig(settings.jwt_secret, algs)
    if not settings.jwt_public_key:
        raise ValueError(f"JWT_PUBLIC_KEY is required for {', '.join(asym)}")
    return JwtConfig(settings.jwt_public_key, algs)


def validate_settings(settings: Settings) -> None:
    """Fail at startup, not at the first request, when auth is misconfigured. Production must be authenticated."""
    cfg = jwt_config(settings)
    if settings.is_production and not settings.api_key_set and cfg is None:
        raise RuntimeError(
            "ENV=production requires API_KEYS and / or JWT_SECRET / JWT_PUBLIC_KEY (refusing to run open)")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


def _verify_jwt(token: str, settings: Settings, cfg: JwtConfig) -> Principal:
    if len(token) > MAX_TOKEN_CHARS:
        raise ApiError(401, "invalid_token", "Invalid token", headers=_challenge("invalid_token"))
    try:
        claims = jwt.decode(
            token,
            cfg.key,
            algorithms=cfg.algorithms,
            audience=settings.jwt_audience or None,
            issuer=settings.jwt_issuer or None,
            leeway=settings.jwt_leeway_s,
            options={"require": ["exp", "sub"], "verify_aud": bool(settings.jwt_audience),
                     "verify_iss": bool(settings.jwt_issuer)},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "Token expired", headers=_challenge("invalid_token")) from None
    except jwt.PyJWTError:
        raise ApiError(401, "invalid_token", "Invalid token", headers=_challenge("invalid_token")) from None
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 128:
        raise ApiError(401, "invalid_token", "Invalid token", headers=_challenge("invalid_token"))
    return Principal("user", sub)


def _challenge(error: str | None = None) -> dict[str, str]:
    return {"WWW-Authenticate": "Bearer" + (f' error="{error}"' if error else "")}


def _key_principal(candidate: str, keys: set[str]) -> Principal | None:
    # constant-time against EVERY key (no early exit on the first match's position)
    matched = False
    for k in keys:
        matched |= hmac.compare_digest(candidate.encode(), k.encode())
    return Principal("api_key", hashlib.sha256(candidate.encode()).hexdigest()[:12]) if matched else None


def _authenticate(request: Request, x_api_key: str | None, authorization: str | None, settings: Settings) -> Principal:
    keys, cfg = settings.api_key_set, jwt_config(settings)
    if not keys and cfg is None:
        return Principal("anonymous", client_ip(request))
    bearer = _bearer(authorization)
    if bearer is not None and cfg is not None:
        return _verify_jwt(bearer, settings, cfg)
    if x_api_key is not None and keys:
        principal = _key_principal(x_api_key, keys)
        if principal is None:
            raise ApiError(401, "invalid_api_key", "Invalid or missing API key", headers=_challenge())
        return principal
    if cfg is not None:
        raise ApiError(401, "unauthorized", "Authentication required", headers=_challenge())
    raise ApiError(401, "invalid_api_key", "Invalid or missing API key", headers=_challenge())


def require_auth(
    request: Request,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Router-level dependency of every /v1 route. Stores the principal on the request (limits + logs read it)."""
    try:
        principal = _authenticate(request, x_api_key, authorization, settings)
    except ApiError as exc:
        request.state.auth_error = exc.code
        if not auth_failure_allowed(client_ip(request), settings.auth_fail_limit):
            raise ApiError(429, "rate_limited", "Too many failed authentication attempts",
                           headers={"Retry-After": "60"}) from None
        raise
    request.state.principal = principal
    return principal
