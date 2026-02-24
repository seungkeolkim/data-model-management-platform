"""
애플리케이션 설정 관리
- .env 파일 및 환경변수에서 설정 로드 (pydantic-settings)
- config.ini에서 비민감 설정 로드
"""
from __future__ import annotations

import configparser
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트 (config.ini 위치)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # backend/ 상위 = 프로젝트 루트


def _load_ini() -> configparser.ConfigParser:
    """config.ini 로드. 없으면 빈 설정 반환."""
    ini = configparser.ConfigParser()
    ini_path = _PROJECT_ROOT / "config.ini"
    if ini_path.exists():
        ini.read(ini_path, encoding="utf-8")
    return ini


class Settings(BaseSettings):
    """
    환경변수 기반 설정.
    .env 파일 또는 실제 환경변수에서 자동 로드.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # PostgreSQL 개별 접속 정보 (.env에서 이 값들만 수정하면 됨)
    # -------------------------------------------------------------------------
    postgres_user: str = "mlplatform"
    postgres_password: str = "mlplatform_secret"
    postgres_db: str = "mlplatform"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # -------------------------------------------------------------------------
    # 스토리지
    # -------------------------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"

    # local 백엔드
    local_storage_base: str = "/mnt/datasets"
    local_eda_base: str = "/mnt/eda"

    # s3 백엔드 (3차 이후)
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"

    # -------------------------------------------------------------------------
    # 애플리케이션
    # -------------------------------------------------------------------------
    app_env: Literal["development", "production"] = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "dev-secret-key-change-in-production"

    # -------------------------------------------------------------------------
    # 이메일 알림 (2차 이후)
    # -------------------------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@mlplatform.local"
    notification_email_to: str | None = None

    # -------------------------------------------------------------------------
    # MLflow (Phase 5 이후)
    # -------------------------------------------------------------------------
    mlflow_tracking_uri: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # -------------------------------------------------------------------------
    # DB URL 자동 조립 (개별 postgres_* 값으로 생성, .env에서 중복 없음)
    # -------------------------------------------------------------------------

    @property
    def database_url(self) -> str:
        """FastAPI용 async PostgreSQL URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL (PostgreSQL, db+ prefix 필수)."""
        return (
            f"db+postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend URL."""
        return self.celery_broker_url

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


class AppConfig:
    """
    config.ini 기반 비민감 설정.
    환경변수로 오버라이드 불필요한 정적 설정값들.
    """

    def __init__(self) -> None:
        self._ini = _load_ini()

    def get(self, section: str, key: str, fallback: str = "") -> str:
        return self._ini.get(section, key, fallback=fallback)

    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        return self._ini.getint(section, key, fallback=fallback)

    def getbool(self, section: str, key: str, fallback: bool = False) -> bool:
        return self._ini.getboolean(section, key, fallback=fallback)

    def getlist(self, section: str, key: str, fallback: list[str] | None = None) -> list[str]:
        raw = self.get(section, key)
        if not raw:
            return fallback or []
        return [item.strip() for item in raw.split(",")]

    # ------ 자주 쓰는 설정 프로퍼티 ------

    @property
    def allowed_image_extensions(self) -> set[str]:
        return set(self.getlist("storage", "allowed_image_extensions", [".jpg", ".jpeg", ".png"]))

    @property
    def annotation_filename(self) -> str:
        return self.get("storage", "annotation_filename", "annotation.json")

    @property
    def images_dirname(self) -> str:
        return self.get("storage", "images_dirname", "images")

    @property
    def version_initial(self) -> str:
        return self.get("storage", "version_initial", "v1.0.0")

    @property
    def progress_update_interval(self) -> int:
        return self.getint("pipeline", "progress_update_interval", 100)

    @property
    def default_jpeg_quality(self) -> int:
        return self.getint("pipeline", "default_jpeg_quality", 95)

    @property
    def auto_refresh_materialized_view(self) -> bool:
        return self.getbool("materialized_view", "auto_refresh", True)

    @property
    def dataset_types(self) -> list[str]:
        return self.getlist("dataset", "types", ["RAW", "SOURCE", "PROCESSED", "FUSION"])

    @property
    def task_types(self) -> list[str]:
        return self.getlist(
            "dataset", "task_types",
            ["DETECTION", "SEGMENTATION", "ATTR_CLASSIFICATION", "ZERO_SHOT", "CLASSIFICATION"]
        )


@lru_cache
def get_settings() -> Settings:
    """Settings 싱글톤 반환 (FastAPI Depends용)."""
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    """AppConfig 싱글톤 반환."""
    return AppConfig()


# 편의용 전역 접근자
settings = get_settings()
app_config = get_app_config()
