# =============================================================================
# Backend Dockerfile (multi-stage)
# - development: hot reload, 디버깅 가능
# - production:  최적화된 이미지
# =============================================================================

# -----------------------------------------------------------------------------
# Base: 공통 Python 환경
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS base

# 시스템 패키지 설치 (OpenCV 의존성 포함)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV 런타임 의존성
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    # PostgreSQL 클라이언트 (alembic 등)
    libpq-dev \
    # 빌드 도구
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv 설치 (Python 패키지 매니저)
RUN pip install uv --no-cache-dir

WORKDIR /app

# 의존성만 먼저 복사 (레이어 캐시 최적화)
COPY pyproject.toml uv.lock* ./

# -----------------------------------------------------------------------------
# Development: 소스 bind mount + hot reload
# -----------------------------------------------------------------------------
FROM base AS development

# 모든 의존성 설치 (dev 포함)
RUN uv sync --frozen

# PATH에 venv 추가
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# CMD는 docker-compose에서 오버라이드
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# -----------------------------------------------------------------------------
# Builder: production 빌드용
# -----------------------------------------------------------------------------
FROM base AS builder

# production 의존성만 설치
RUN uv sync --frozen --no-dev

# -----------------------------------------------------------------------------
# Production: 최소 이미지
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# builder에서 venv 복사
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# 소스 복사
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
