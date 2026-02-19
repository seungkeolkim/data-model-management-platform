# =============================================================================
# ML Platform - Makefile
# 개발 편의 명령어 모음
#
# 사용법:
#   make help       # 도움말
#   make up         # 서비스 시작
#   make down       # 서비스 중단
#   make logs       # 로그 확인
# =============================================================================

.PHONY: help up down restart logs build migrate seed check clean

# 기본 타겟
.DEFAULT_GOAL := help

help: ## 사용 가능한 명령어 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort

# =============================================================================
# Docker Compose
# =============================================================================

up: ## Docker 서비스 시작 (백그라운드)
	docker compose up -d
	@echo "✅ 서비스 시작됨. http://localhost 접속"

up-build: ## 이미지 재빌드 후 서비스 시작
	docker compose up -d --build

down: ## Docker 서비스 중단
	docker compose down

restart: ## 특정 서비스 재시작 (make restart SERVICE=backend)
	docker compose restart $(SERVICE)

logs: ## 로그 확인 (make logs SERVICE=backend)
	docker compose logs -f $(SERVICE)

logs-all: ## 전체 서비스 로그
	docker compose logs -f

ps: ## 서비스 상태 확인
	docker compose ps

# =============================================================================
# DB 관련
# =============================================================================

migrate: ## DB 마이그레이션 실행 (alembic upgrade head)
	docker compose exec backend python -m alembic upgrade head

migrate-down: ## 마이그레이션 롤백 (1단계)
	docker compose exec backend python -m alembic downgrade -1

migrate-status: ## 마이그레이션 상태 확인
	docker compose exec backend python -m alembic current

seed: ## 시드 데이터 삽입 (Manipulator 목록 등)
	docker compose exec backend python -m alembic upgrade head
	@echo "✅ 마이그레이션 완료 (시드는 002_seed_manipulators 마이그레이션에 포함)"

db-shell: ## PostgreSQL 콘솔 접속
	docker compose exec postgres psql -U mlplatform -d mlplatform

db-reset: ## DB 초기화 (주의: 모든 데이터 삭제)
	@echo "⚠️  DB를 초기화합니다. 계속하려면 Enter를 누르세요..."
	@read confirm
	docker compose exec backend python -m alembic downgrade base
	docker compose exec backend python -m alembic upgrade head
	@echo "✅ DB 초기화 완료"

# =============================================================================
# 빌드
# =============================================================================

build: ## 특정 서비스 이미지 빌드 (make build SERVICE=backend)
	docker compose build $(SERVICE)

build-all: ## 전체 이미지 빌드
	docker compose build

# =============================================================================
# 개발 환경
# =============================================================================

setup: ## 개발 환경 초기 설정
	chmod +x scripts/setup_dev.sh
	./scripts/setup_dev.sh

check: ## 환경 사전 검사
	chmod +x scripts/check_env.sh
	./scripts/check_env.sh

health: ## 헬스체크
	@curl -sf http://localhost/health | python3 -m json.tool || echo "❌ 서비스가 응답하지 않음"

# =============================================================================
# Frontend
# =============================================================================

frontend-install: ## Frontend 의존성 설치
	cd frontend && npm install

frontend-build: ## Frontend 프로덕션 빌드
	cd frontend && npm run build

frontend-lint: ## Frontend 린트 검사
	cd frontend && npm run lint

# =============================================================================
# Backend
# =============================================================================

backend-lint: ## Backend 린트 (ruff)
	cd backend && uv run ruff check app/

backend-format: ## Backend 코드 포맷
	cd backend && uv run ruff format app/

backend-test: ## Backend 테스트
	cd backend && uv run pytest tests/ -v

# =============================================================================
# 정리
# =============================================================================

clean: ## 빌드 캐시, 컨테이너, 이미지 정리 (데이터 볼륨 제외)
	docker compose down --rmi local --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-all: ## 모든 것 정리 (DB 볼륨 포함, 주의!)
	@echo "⚠️  DB 데이터도 삭제됩니다. 계속하려면 Enter를 누르세요..."
	@read confirm
	docker compose down -v --rmi local --remove-orphans

# =============================================================================
# 정보
# =============================================================================

info: ## 프로젝트 정보 출력
	@echo ""
	@echo "ML Platform 서비스 접속 정보"
	@echo "================================"
	@echo "  웹 UI:        http://localhost"
	@echo "  API Docs:     http://localhost/api/docs"
	@echo "  Backend:      http://localhost:8000"
	@echo "  Frontend:     http://localhost:5173"
	@echo "  PostgreSQL:   localhost:5432"
	@echo ""
