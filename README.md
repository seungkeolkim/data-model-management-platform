# ML Platform - 데이터 관리 & 학습 자동화 플랫폼

데이터셋 관리, 파이프라인 처리, 모델 학습 자동화를 위한 통합 플랫폼.  
Phase 0(인프라) 구축 완료 상태.

---

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/seungkeolkim/data-model-management-platform.git
cd data-model-management-platform

# 2. 환경 파일 복사 및 수정
cp .env.example .env
# .env에서 아래 항목 확인/수정:
#   LOCAL_STORAGE_BASE  ← NAS 마운트 경로 (개발: ./data/datasets)
#   LOCAL_EDA_BASE      ← EDA 저장 경로  (개발: ./data/eda)
#   POSTGRES_PASSWORD   ← DB 비밀번호
#   SECRET_KEY          ← 랜덤 시크릿 키

# 3. 환경 사전 검사
./scripts/check_env.sh

# 4. 서비스 시작
docker compose up -d --build

# 5. 헬스체크
curl http://localhost/health
```

접속 URL:
- **웹 UI**: http://localhost
- **API 문서**: http://localhost/api/docs
- **ReDoc**: http://localhost/api/redoc

> **Makefile 사용 시** (make 설치 필요)
> ```bash
> make check   # 환경 검사
> make up      # 서비스 시작
> make health  # 헬스체크
> make help    # 전체 명령어
> ```

---

## 프로젝트 구조

```
.
├── backend/                # FastAPI 백엔드
│   ├── app/
│   │   ├── api/v1/         # REST API 라우터
│   │   ├── core/           # config, database, storage
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── schemas/        # Pydantic 스키마
│   │   ├── services/       # 비즈니스 로직
│   │   ├── tasks/          # Celery 태스크
│   │   └── pipeline/       # 파이프라인 인터페이스
│   ├── migrations/         # Alembic 마이그레이션
│   └── pyproject.toml      # 의존성 (uv)
│
├── frontend/               # React 18 + TypeScript 프론트엔드
│   └── src/
│       ├── api/            # Axios API 클라이언트
│       ├── components/     # UI 컴포넌트
│       ├── pages/          # 페이지
│       ├── stores/         # Zustand 상태 관리
│       └── types/          # TypeScript 타입
│
├── infra/
│   ├── nginx/              # Nginx 설정
│   └── postgres/init/      # DB 초기화 SQL
│
├── scripts/
│   ├── setup_dev.sh        # 개발 환경 구축
│   ├── check_env.sh        # 환경 사전 검사
│   └── init_db.sh          # DB 마이그레이션 (직접 실행)
│
├── data/                   # 개발용 로컬 데이터 (NAS 대체)
│   ├── datasets/
│   └── eda/
│
├── .env.example            # 환경변수 예시
├── config.ini              # 비민감 설정 (NAS 디렉토리 규칙 등)
├── docker-compose.yml
├── environment.yml         # conda 환경 설정
└── Makefile                # 개발 편의 명령어
```

---

## 설정 파일 구조

### `.env` (민감 정보)
```ini
# PostgreSQL 개별 변수만 설정하면 DATABASE_URL은 config.py에서 자동 조립
POSTGRES_USER=mlplatform
POSTGRES_PASSWORD=...          # 변경 포인트
POSTGRES_DB=mlplatform
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
LOCAL_STORAGE_BASE=/mnt/nas/datasets  # NAS 마운트 경로 ← 변경 포인트
LOCAL_EDA_BASE=/mnt/nas/eda
SECRET_KEY=...
```

### `config.ini` (비민감 설정)
```ini
[storage]
dir_raw = raw
dir_source = source
dir_processed = processed
dir_fusion = fusion
annotation_filename = annotation.json
images_dirname = images

[pipeline]
progress_update_interval = 100
default_jpeg_quality = 95

[celery]
worker_concurrency = 4
```

---

## NAS 스토리지 구조

```
{LOCAL_STORAGE_BASE}/
├── raw/{name}/{split}/{version}/
│   ├── images/
│   └── annotation.json
├── source/...
├── processed/...
└── fusion/...

{LOCAL_EDA_BASE}/
└── {dataset_id}/
    ├── class_distribution.png
    └── eda_result.json
```

---

## 개발 명령어 (Makefile)

```bash
make up           # 서비스 시작
make down         # 서비스 중단
make logs SERVICE=backend  # 로그 확인
make migrate      # DB 마이그레이션
make db-shell     # PostgreSQL 콘솔
make health       # 헬스체크
make backend-lint # 백엔드 린트
make help         # 전체 명령어 목록
```

---

## 개발 단계 (Roadmap)

| Phase | 기능 | 상태 |
|-------|------|------|
| **Phase 0** | 인프라, DB 스키마, /health | ✅ **완료** |
| **Phase 1** | Dataset CRUD GUI | 🚧 진행 예정 |
| **Phase 2** | Manipulator + Celery 파이프라인 | ⏳ |
| **Phase 2-a** | EDA 자동화 | ⏳ |
| **Phase 2-b** | 샘플 보기 + Lineage 시각화 | ⏳ |
| **Phase 3** | 학습 실행 (2차 준비) | ⏳ |

---

## API 엔드포인트 (현재 활성)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 (DB + 스토리지 상태) |
| GET | `/api/v1/dataset-groups` | 데이터셋 그룹 목록 |
| POST | `/api/v1/dataset-groups` | 그룹 생성 |
| GET | `/api/v1/dataset-groups/{id}` | 그룹 상세 |
| PATCH | `/api/v1/dataset-groups/{id}` | 그룹 수정 |
| DELETE | `/api/v1/dataset-groups/{id}` | 그룹 삭제 |
| POST | `/api/v1/dataset-groups/validate-path` | NAS 경로 검증 |
| POST | `/api/v1/dataset-groups/register` | 데이터셋 등록 (GUI) |
| GET | `/api/v1/datasets` | Dataset 목록 |
| GET | `/api/v1/manipulators` | Manipulator 목록 |

> 현재 라우터는 모두 stub 상태(`"Phase 1에서 구현 예정"` 응답).  
> 실제 CRUD 구현은 Phase 1에서 진행.

---

## 기술 스택

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery
- **DB**: PostgreSQL 16 (메타데이터 + Celery broker/backend 통합)
- **Storage**: NAS 직접 마운트 (StorageClient 추상화로 향후 S3 전환 가능)
- **Frontend**: React 18, TypeScript, Vite, Ant Design, TanStack Query, Zustand
- **Infra**: Docker, Docker Compose, Nginx

---

## 현재 작업 내용 요약 (2026-02-24)

### 수정된 파일

| 파일 | 변경 내용 |
|------|-----------|
| `backend/app/main.py` | `openapi_url` 를 `/api/openapi.json` → `/openapi.json` 으로 변경 |
| `infra/nginx/conf.d/default.conf` | `/openapi.json` 경로 백엔드 프록시 블록 추가 |

### 버그 원인 및 수정 상세

**증상**: `http://localhost/api/docs` 에서 502 Bad Gateway  
**실제 동작**: `GET /api/docs` 는 200 OK, `GET /openapi.json` 은 404 → Swagger UI 화면 렌더링 실패  

**원인**: FastAPI Swagger UI 는 `openapi_url` 을 HTML 내 스크립트에 삽입할 때
root-relative URL 로 처리함. `openapi_url="/api/openapi.json"` 으로 설정하면
브라우저가 `/openapi.json` 을 요청하고, nginx 에는 해당 경로 프록시가 없어 프론트엔드(Vite)로 넘어가 404가 발생.

**수정 내용**:
1. `main.py`: `openapi_url="/openapi.json"` (루트 등록)
2. `nginx/default.conf`: `location /openapi.json` 블록 추가 → `backend:8000/openapi.json` 프록시

---

## TODO (다음 작업 항목)

### 🔴 즉시 필요 (Phase 1 착수 전)

- [ ] **API 라우터 실제 구현**: 현재 모든 라우터가 stub. Dataset Group, Dataset CRUD 구현 필요
  - `backend/app/api/v1/dataset_groups/router.py`
  - `backend/app/api/v1/datasets/router.py`
- [ ] **서비스 레이어 구현**: `dataset_service.py` 의 실제 DB 쿼리 작성
- [ ] **Pydantic 스키마 보완**: `schemas/dataset.py` 에 응답 스키마 추가 (현재 Request만 있음)

### 🟡 Phase 1 - Dataset CRUD GUI

- [ ] **프론트엔드 DatasetListPage 구현**: 실제 API 연동, 테이블 렌더링
- [ ] **DatasetDetailPage 구현**: 데이터셋 상세 정보, 이미지 샘플 뷰어
- [ ] **DatasetGroup 등록 폼**: NAS 경로 입력 → 경로 검증 → 등록 플로우
- [ ] **API 클라이언트 완성**: `frontend/src/api/dataset.ts` 실제 엔드포인트 연동

### 🟡 Phase 1 - Lineage 시각화

- [ ] **Lineage 조회 API 구현**: `GET /api/v1/lineage/{dataset_id}`
- [ ] **Lineage 그래프 UI**: React Flow 또는 Ant Design Graph 컴포넌트로 시각화

### ⏳ Phase 2 - 파이프라인 & EDA

- [ ] **Celery 워커 활성화**: `docker-compose.yml` celery-worker 서비스 주석 해제
- [ ] **Manipulator 실제 구현**: `backend/app/pipeline/manipulator.py` 에 OpenCV 기반 변환 로직
- [ ] **EDA 태스크 구현**: `backend/app/tasks/eda_tasks.py` — COCO 통계 분석, 차트 생성
- [ ] **파이프라인 실행 API**: `POST /api/v1/pipelines` → Celery 태스크 dispatch

### ⏳ Phase 3 - 학습 자동화

- [ ] **GPU 스케줄러**: TrainingJob 생성 → Docker container dispatch
- [ ] **MLflow 연동**: 실험 추적, 모델 레지스트리
- [ ] **학습 현황 대시보드**: Prometheus + Grafana 활성화

### 🔧 기술 부채

- [ ] **테스트 코드 작성**: `backend/tests/` 디렉토리 없음. pytest 기반 API 테스트 필요
- [ ] **타입 정의 보완**: `frontend/src/types/` 에 API 응답 타입 자동 생성 (openapi-typescript)
- [ ] **에러 핸들링**: FastAPI 전역 예외 핸들러 추가
- [ ] **로깅 개선**: structlog 구조화 로그 → 표준 포맷 통일

---

## GitHub

Repository: https://github.com/seungkeolkim/data-model-management-platform
