"""应用配置：环境变量集中读取。"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql+psycopg2://xzc25:xzc25_pwd@postgres:5432/xzc25_db"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "xzc25-super-secret-key"
    jwt_alg: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    storage_dir: str = os.path.join(os.path.dirname(__file__), "..", "storage")
    quality_supervision_endpoint: str = "http://localhost:9999/quality/archives"

    @property
    def is_docker(self) -> bool:
        return self.app_env.lower() == "docker"


@lru_cache
def get_settings() -> Settings:
    return Settings()
