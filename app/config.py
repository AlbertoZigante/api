from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:4321"
    api_keys: str = ""  # empty = auth disabled
    max_body_bytes: int = 2_000_000  # request body cap (413 above)
    nesting_timeout_s: float = 10.0  # CPU budget of one /v1/nesting call (503 nesting_timeout above)
    max_concurrent_nestings: int = 4  # simultaneous /v1/nesting calls (503 busy above)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
