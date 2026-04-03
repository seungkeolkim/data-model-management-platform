"""
SQLAlchemy 데이터베이스 세션 관리.

두 가지 엔진을 제공한다:
  - Async 엔진 (asyncpg) — FastAPI 라우터용
  - Sync 엔진 (psycopg2) — Celery 태스크 / Alembic 용
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = structlog.get_logger(__name__)


# Async Engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,   # 개발 시 SQL 출력
    pool_pre_ping=True,             # 연결 유효성 자동 확인
    pool_size=10,
    max_overflow=20,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Sync Engine — Celery 태스크에서 사용 (psycopg2)
# ---------------------------------------------------------------------------
_sync_database_url = settings.database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)

sync_engine = create_engine(
    _sync_database_url,
    echo=settings.is_development,
    pool_pre_ping=True,
    pool_size=5,       # Celery worker 전용이므로 작게 설정
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """모든 SQLAlchemy ORM 모델의 Base 클래스."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends용 DB 세션 제공자.
    요청마다 세션을 생성하고, 완료 시 자동 닫기.

    Usage:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            logger.error("DB 세션 에러 — 롤백 수행", error=str(exc), error_type=type(exc).__name__)
            await session.rollback()
            raise
        finally:
            await session.close()
