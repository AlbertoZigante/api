from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:4321"
    api_keys: str = ""  # beta gate: comma-separated keys accepted in X-API-Key (empty = no key gate)

    # Per-user auth (JWT, e.g. Supabase / Auth0 / self-issued). Empty = no JWT accepted.
    jwt_secret: str = ""  # HS* algorithms: shared secret (>= 32 chars)
    jwt_public_key: str = ""  # RS* / ES* / PS* / EdDSA: PEM public key of the issuer
    jwt_algorithms: str = "HS256"  # allow-list; one FAMILY only (symmetric or asymmetric), never "none"
    jwt_audience: str = ""  # required `aud` when set
    jwt_issuer: str = ""  # required `iss` when set
    jwt_leeway_s: int = 10  # clock skew tolerated on exp / nbf / iat

    # Rate limits (slowapi / limits syntax: "60/minute", "5/second"). Keyed by user, API key or IP.
    rate_limit: str = "60/minute"  # all /v1 calls of one caller together
    rate_limit_heavy: str = "10/minute"  # /v1/nesting on top of the above
    rate_limit_storage: str = "memory://"  # "redis://..." once there is more than one instance
    auth_fail_limit: str = "20/minute"  # failed authentications per client IP, then 429

    docs_enabled: bool | None = None  # /docs, /redoc, /openapi.json; default: on except in production
    max_body_bytes: int = 2_000_000  # request body cap (413 above)
    nesting_timeout_s: float = 10.0  # CPU budget of one /v1/nesting call (503 nesting_timeout above)
    max_concurrent_nestings: int = 4  # simultaneous /v1/nesting calls (503 busy above) = worker processes
    nesting_executor: str = "process"  # "process": worker processes (web process stays responsive) | "thread"
    nesting_worker_nice: int = 10  # CPU priority of the workers (Unix): the web process wins

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() == "production"

    @property
    def docs_on(self) -> bool:
        return self.docs_enabled if self.docs_enabled is not None else not self.is_production

    @property
    def jwt_algorithm_list(self) -> list[str]:
        return [a.strip() for a in self.jwt_algorithms.split(",") if a.strip()]

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
