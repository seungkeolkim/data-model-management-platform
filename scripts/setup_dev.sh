#!/usr/bin/env bash
# =============================================================================
# ML Platform 개발 환경 구축 스크립트
# Ubuntu 22.04+ 기준
#
# 사용법:
#   chmod +x scripts/setup_dev.sh
#   ./scripts/setup_dev.sh
#
# 실행 내용:
#   1. 시스템 패키지 설치
#   2. conda 환경 생성 (Python 3.11)
#   3. uv 설치 및 Backend 의존성 설치
#   4. npm 설치 확인 및 Frontend 의존성 설치
#   5. .env 파일 초기화
#   6. Docker / Docker Compose 설치 확인
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONDA_ENV_NAME="mlplatform"
PYTHON_VERSION="3.11"

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo "========================================================"
echo "  ML Platform 개발 환경 구축"
echo "========================================================"
echo ""

# =============================================================================
# 1. 시스템 패키지
# =============================================================================
log_info "시스템 패키지 설치..."

if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        git curl wget unzip \
        build-essential \
        libpq-dev \
        libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 \
        2>/dev/null || log_warn "일부 패키지 설치 실패 (권한 부족할 수 있음)"
    log_success "시스템 패키지 설치 완료"
else
    log_warn "apt-get 없음. Ubuntu/Debian 아닌 경우 수동으로 OpenCV 의존성 설치 필요."
fi

# =============================================================================
# 2. conda 환경
# =============================================================================
if command -v conda &>/dev/null; then
    log_info "conda 감지됨. 환경 설정 중..."

    if conda env list | grep -q "^${CONDA_ENV_NAME} "; then
        log_warn "conda 환경 '${CONDA_ENV_NAME}' 이미 존재함. 스킵."
    else
        log_info "conda 환경 '${CONDA_ENV_NAME}' 생성 중 (Python ${PYTHON_VERSION})..."
        conda create -y -n "${CONDA_ENV_NAME}" python="${PYTHON_VERSION}" || \
            log_error "conda 환경 생성 실패"
        log_success "conda 환경 '${CONDA_ENV_NAME}' 생성 완료"
    fi

    echo ""
    echo -e "${YELLOW}>>> conda 환경 활성화 방법:${NC}"
    echo "    conda activate ${CONDA_ENV_NAME}"
    echo ""

elif command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
    log_warn "conda 없음. 시스템 Python ${PY_VER} 사용."

    if [[ "$PY_VER" != "3.11" && "$PY_VER" != "3.12" ]]; then
        log_warn "Python 3.11 이상 권장. 현재: ${PY_VER}"
    fi
else
    log_error "Python을 찾을 수 없습니다. conda 또는 Python 3.11+ 설치 필요."
fi

# =============================================================================
# 3. uv 설치 & Backend 의존성
# =============================================================================
log_info "uv 패키지 매니저 확인..."

if ! command -v uv &>/dev/null; then
    log_info "uv 설치 중..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
    log_success "uv 설치 완료"
else
    log_success "uv 이미 설치됨: $(uv --version)"
fi

log_info "Backend 의존성 설치 중..."
cd "${PROJECT_ROOT}/backend"

if uv sync --frozen 2>/dev/null; then
    log_success "Backend 의존성 설치 완료"
else
    log_info "lockfile 없음. 새로 생성 중..."
    uv sync
    log_success "Backend 의존성 설치 및 lockfile 생성 완료"
fi

cd "${PROJECT_ROOT}"

# =============================================================================
# 4. Node.js / npm & Frontend 의존성
# =============================================================================
log_info "Node.js 확인..."

if ! command -v node &>/dev/null; then
    log_warn "Node.js가 없습니다. 설치 방법:"
    echo "    # nvm 사용 (권장):"
    echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
    echo "    source ~/.bashrc"
    echo "    nvm install 20"
    echo "    nvm use 20"
else
    NODE_VER=$(node --version)
    log_success "Node.js 감지됨: ${NODE_VER}"

    log_info "Frontend 의존성 설치 중..."
    cd "${PROJECT_ROOT}/frontend"
    npm install
    log_success "Frontend 의존성 설치 완료"
    cd "${PROJECT_ROOT}"
fi

# =============================================================================
# 5. .env 파일 초기화
# =============================================================================
log_info ".env 파일 확인..."

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    log_warn ".env 파일 이미 존재. 스킵. (수동으로 확인 필요)"
else
    cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
    log_success ".env 파일 생성됨: .env.example 복사"
    echo ""
    echo -e "${YELLOW}>>> .env 파일에서 아래 항목을 확인/수정하세요:${NC}"
    echo "    - POSTGRES_PASSWORD"
    echo "    - LOCAL_STORAGE_BASE  (NAS 마운트 경로)"
    echo "    - LOCAL_EDA_BASE      (EDA 저장 경로)"
    echo "    - SECRET_KEY"
    echo ""
fi

# =============================================================================
# 6. Docker 확인
# =============================================================================
log_info "Docker 확인..."

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version)
    log_success "Docker 감지됨: ${DOCKER_VER}"

    if docker compose version &>/dev/null 2>&1; then
        log_success "Docker Compose v2 감지됨"
    else
        log_warn "Docker Compose v2 없음. 설치 필요:"
        echo "    sudo apt-get install docker-compose-plugin"
    fi
else
    log_warn "Docker가 없습니다. Docker Desktop 또는 Docker Engine 설치 필요:"
    echo "    https://docs.docker.com/engine/install/ubuntu/"
fi

# =============================================================================
# 7. data 디렉토리 생성 (개발용 로컬 스토리지)
# =============================================================================
log_info "개발용 데이터 디렉토리 생성..."

mkdir -p "${PROJECT_ROOT}/data/datasets/raw"
mkdir -p "${PROJECT_ROOT}/data/datasets/source"
mkdir -p "${PROJECT_ROOT}/data/datasets/processed"
mkdir -p "${PROJECT_ROOT}/data/datasets/fusion"
mkdir -p "${PROJECT_ROOT}/data/eda"
log_success "data/ 디렉토리 생성 완료 (개발용 로컬 스토리지)"

# =============================================================================
# 완료
# =============================================================================
echo ""
echo "========================================================"
echo -e "${GREEN}  환경 구축 완료!${NC}"
echo "========================================================"
echo ""
echo "다음 단계:"
echo "  1. .env 파일 확인 및 수정"
echo "  2. Docker 서비스 시작:"
echo "       docker compose up -d"
echo "  3. 헬스체크:"
echo "       curl http://localhost/health"
echo "  4. 브라우저에서 접속:"
echo "       http://localhost"
echo ""
