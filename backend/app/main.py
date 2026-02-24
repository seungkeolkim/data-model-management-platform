"""
FastAPI 애플리케이션 엔트리포인트
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 이벤트 처리."""
    logger.info("Starting ML Platform API", env=settings.app_env)
    yield
    logger.info("Shutting down ML Platform API")
    await engine.dispose()


app = FastAPI(
    title="ML Platform API",
    description="데이터 관리 & 학습 자동화 플랫폼 REST API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/openapi.json",   # Swagger UI가 root-relative로 요청하므로 루트에 등록
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
from app.api.v1.router import api_router  # noqa: E402
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["system"])
async def health_check():
    """
    시스템 헬스체크.
    DB 연결 상태, 스토리지 접근 가능 여부 반환.
    """
    from app.core.storage import get_storage_client
    from pathlib import Path

    db_ok = False
    db_error = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)

    storage_ok = False
    storage_error = None
    try:
        client = get_storage_client()
        storage_base = Path(settings.local_storage_base)
        storage_ok = storage_base.exists()
        if not storage_ok:
            storage_error = f"경로 없음: {settings.local_storage_base}"
    except Exception as e:
        storage_error = str(e)

    status = "healthy" if (db_ok and storage_ok) else "degraded"

    return {
        "status": status,
        "services": {
            "database": {"ok": db_ok, "error": db_error},
            "storage": {
                "ok": storage_ok,
                "backend": settings.storage_backend,
                "base_path": settings.local_storage_base,
                "error": storage_error,
            },
        },
        "version": "0.1.0",
        "env": settings.app_env,
    }
