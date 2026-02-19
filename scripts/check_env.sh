#!/usr/bin/env bash
# =============================================================================
# ML Platform - 환경 사전 검사 스크립트
# docker compose up 전에 필수 조건 확인
#
# 사용법:
#   ./scripts/check_env.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 색상
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0

check_ok()   { echo -e "${GREEN}[✓]${NC} $*"; ((PASS++)); }
check_warn() { echo -e "${YELLOW}[!]${NC} $*"; }
check_fail() { echo -e "${RED}[✗]${NC} $*"; ((FAIL++)); }

echo ""
echo "========================================================"
echo "  ML Platform 환경 검사"
echo "========================================================"
echo ""

# =============================================================================
# 1. Docker
# =============================================================================
echo "[ Docker ]"

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    check_ok "Docker ${DOCKER_VER}"
else
    check_fail "Docker 없음 → https://docs.docker.com/engine/install/ubuntu/"
fi

if docker compose version &>/dev/null 2>&1; then
    COMPOSE_VER=$(docker compose version --short 2>/dev/null || echo "unknown")
    check_ok "Docker Compose v2 (${COMPOSE_VER})"
else
    check_fail "Docker Compose v2 없음 → sudo apt-get install docker-compose-plugin"
fi

# Docker 실행 권한
if docker info &>/dev/null 2>&1; then
    check_ok "Docker 데몬 접근 가능"
else
    check_fail "Docker 데몬 접근 불가 → sudo usermod -aG docker \$USER (재로그인 필요)"
fi

# NVIDIA GPU (선택)
if command -v nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "unknown")
    check_ok "NVIDIA GPU: ${GPU_INFO}"
    
    if docker info 2>/dev/null | grep -q "nvidia"; then
        check_ok "NVIDIA Container Toolkit 설치됨"
    else
        check_warn "NVIDIA Container Toolkit 없음 (2차 GPU 학습 시 필요)"
        echo "         → https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
    fi
else
    check_warn "NVIDIA GPU/nvidia-smi 없음 (2차 GPU 학습 기능 사용 불가)"
fi

echo ""

# =============================================================================
# 2. .env 파일
# =============================================================================
echo "[ 환경 설정 ]"

ENV_FILE="${PROJECT_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    check_ok ".env 파일 존재"
    
    # 필수 환경변수 확인
    required_vars=(
        "POSTGRES_USER"
        "POSTGRES_PASSWORD"
        "DATABASE_URL"
        "CELERY_BROKER_URL"
        "CELERY_RESULT_BACKEND"
        "STORAGE_BACKEND"
        "LOCAL_STORAGE_BASE"
    )
    
    for var in "${required_vars[@]}"; do
        if grep -q "^${var}=" "${ENV_FILE}" 2>/dev/null; then
            check_ok "  ${var} 설정됨"
        else
            check_fail "  ${var} 없음 → .env 파일에 추가 필요"
        fi
    done
    
    # 기본값 경고
    if grep -q "mlplatform_secret_change_me" "${ENV_FILE}"; then
        check_warn "  POSTGRES_PASSWORD가 기본값입니다. 운영 환경에서는 반드시 변경하세요."
    fi
    if grep -q "change-me-to-a-random-secret-key" "${ENV_FILE}"; then
        check_warn "  SECRET_KEY가 기본값입니다. 운영 환경에서는 반드시 변경하세요."
    fi
else
    check_fail ".env 파일 없음 → cp .env.example .env 후 수정 필요"
fi

echo ""

# =============================================================================
# 3. NAS 스토리지 경로
# =============================================================================
echo "[ 스토리지 경로 ]"

if [[ -f "${ENV_FILE}" ]]; then
    LOCAL_STORAGE_BASE=$(grep "^LOCAL_STORAGE_BASE=" "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    LOCAL_EDA_BASE=$(grep "^LOCAL_EDA_BASE=" "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' | tr -d "'" 2>/dev/null || echo "")

    if [[ -n "${LOCAL_STORAGE_BASE}" ]]; then
        if [[ -d "${LOCAL_STORAGE_BASE}" ]]; then
            check_ok "LOCAL_STORAGE_BASE 접근 가능: ${LOCAL_STORAGE_BASE}"
            
            # 하위 디렉토리 확인
            for subdir in raw source processed fusion; do
                if [[ -d "${LOCAL_STORAGE_BASE}/${subdir}" ]]; then
                    check_ok "  ${subdir}/ 디렉토리 존재"
                else
                    check_warn "  ${subdir}/ 없음 → docker compose 시작 시 자동 마운트"
                fi
            done
        else
            check_warn "LOCAL_STORAGE_BASE 경로 없음: ${LOCAL_STORAGE_BASE}"
            echo "         개발 환경에서는 ./data/datasets 사용 가능"
            echo "         운영 환경에서는 NAS 마운트 후 .env 수정 필요"
        fi
    fi

    if [[ -n "${LOCAL_EDA_BASE}" ]] && [[ "${LOCAL_EDA_BASE}" != "/mnt/nas/eda" ]]; then
        if [[ -d "${LOCAL_EDA_BASE}" ]]; then
            check_ok "LOCAL_EDA_BASE 접근 가능: ${LOCAL_EDA_BASE}"
        else
            check_warn "LOCAL_EDA_BASE 경로 없음: ${LOCAL_EDA_BASE}"
        fi
    fi
fi

echo ""

# =============================================================================
# 4. 포트 충돌
# =============================================================================
echo "[ 포트 사용 현황 ]"

check_port() {
    local port=$1
    local service=$2
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
       netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        check_warn "포트 ${port}(${service}) 이미 사용 중 → 충돌 가능"
    else
        check_ok "포트 ${port}(${service}) 사용 가능"
    fi
}

check_port 80    "Nginx"
check_port 8000  "Backend"
check_port 5173  "Frontend"
check_port 5432  "PostgreSQL"

echo ""

# =============================================================================
# 결과
# =============================================================================
echo "========================================================"
if [[ ${FAIL} -eq 0 ]]; then
    echo -e "${GREEN}  검사 완료: ${PASS}개 통과, ${FAIL}개 실패${NC}"
    echo ""
    echo "  다음 단계: docker compose up -d"
else
    echo -e "${YELLOW}  검사 완료: ${PASS}개 통과, ${FAIL}개 실패${NC}"
    echo ""
    echo "  위의 ✗ 항목을 먼저 해결하세요."
fi
echo "========================================================"
echo ""

exit ${FAIL}
