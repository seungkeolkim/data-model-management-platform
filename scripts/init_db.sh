#!/usr/bin/env bash
# =============================================================================
# ML Platform - DB 마이그레이션 스크립트 (컨테이너 외부 실행용)
# 직접 Python 환경에서 alembic을 실행할 때 사용
#
# 사용법:
#   ./scripts/init_db.sh              # 최신 마이그레이션까지 적용
#   ./scripts/init_db.sh --reset      # DB 초기화 후 마이그레이션
#   ./scripts/init_db.sh --status     # 마이그레이션 상태 확인
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="${PROJECT_ROOT}/backend"

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "\033[0;34m[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

MODE="${1:-upgrade}"

# .env 로드
ENV_FILE="${PROJECT_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    source "${ENV_FILE}"
    set +a
    log_info ".env 로드됨"
else
    log_warn ".env 없음 → 기본 DATABASE_URL 사용"
fi

# DATABASE_URL이 asyncpg이면 psycopg2로 변환 (alembic은 동기 드라이버 필요)
ALEMBIC_URL="${DATABASE_URL:-postgresql://mlplatform:mlplatform_secret@localhost:5432/mlplatform}"
ALEMBIC_URL="${ALEMBIC_URL/postgresql+asyncpg/postgresql+psycopg2}"
ALEMBIC_URL="${ALEMBIC_URL/@postgres:/@localhost:}"  # Docker 네트워크 이름 → localhost

export DATABASE_URL="${ALEMBIC_URL}"

log_info "DB URL: ${DATABASE_URL//:*@//:***@}"

# Python 환경 확인
cd "${BACKEND_DIR}"

if [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
    ALEMBIC=".venv/bin/alembic"
elif command -v uv &>/dev/null; then
    PYTHON="uv run python"
    ALEMBIC="uv run alembic"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
    ALEMBIC="python3 -m alembic"
else
    log_error "Python을 찾을 수 없습니다."
fi

case "${MODE}" in
    --status)
        log_info "마이그레이션 상태 확인..."
        ${ALEMBIC} current
        ${ALEMBIC} history --verbose
        ;;
    
    --reset)
        log_warn "DB를 초기화합니다 (모든 테이블 삭제 후 재생성)..."
        ${ALEMBIC} downgrade base
        ${ALEMBIC} upgrade head
        log_ok "DB 초기화 완료"
        ;;
    
    *)
        log_info "DB 마이그레이션 실행 중 (upgrade head)..."
        ${ALEMBIC} upgrade head
        log_ok "마이그레이션 완료"
        ;;
esac
