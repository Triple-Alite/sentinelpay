from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SentinelPay API"
    app_env: str = "development"
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"
    database_url: str = "postgresql+asyncpg://sentinelpay:sentinelpay@localhost:5432/sentinelpay"
    redis_url: str = "redis://localhost:6379/0"
    evm_rpc_url: str = ""
    evm_chain_id: int = 11155111
    escrow_contract_address: str = ""
    checkout_enabled: bool = False
    authorizer_private_key: str = ""
    authorizer_address: str = ""
    jwt_secret: str = "development-only-access-secret-change-before-production"
    jwt_refresh_secret: str = "development-only-refresh-secret-change-before-production"
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env.lower() == "production":
            minimum_length = 32
            if (
                len(self.jwt_secret) < minimum_length
                or len(self.jwt_refresh_secret) < minimum_length
                or self.jwt_secret.startswith("development-only-")
                or self.jwt_refresh_secret.startswith("development-only-")
            ):
                raise ValueError("Production requires separate, random JWT secrets of at least 32 characters")
            if self.jwt_secret == self.jwt_refresh_secret:
                raise ValueError("JWT_SECRET and JWT_REFRESH_SECRET must be different")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()