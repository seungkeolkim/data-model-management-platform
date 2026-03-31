# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

ML 데이터 관리 & 학습 자동화 플랫폼 — 데이터셋, 파이프라인, 모델 학습을 관리하는 풀스택 모노레포.

전체 로드맵은 **Step 1 ~ 5**로 구성되며, 현재 진행 중인 Phase 0 ~ 3은 **Step 1을 세부 phase로 나눈 것**이다.

| Step | 범위 |
|------|------|
| **Step 1** | 데이터셋 관리 (Phase 0~3으로 세분화, 현재 진행 중) |
| **Step 2** | 학습 자동화 (단일/다중 GPU 서버) |
| **Step 3** | 다중 GPU 서버 K8S 클러스터화, GPU 학습 스케줄링 |
| **Step 4** | Label Studio 연결, AI 생성 Synthetic Train Data 도입, MLOps (학습 스케줄링, 데이터 자동 수집, Auto Labeling, Offline Testing, Auto Deploy 등) |
| **Step 5** | Generative Model 도입 MLOps |

**Step 1 세부 Phase:**

Step 1의 세부적인 작업은 `objective_n_plan_1st.md` 참고할 것

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 0 | 인프라, DB 스키마, /health | 완료 |
| Phase 1 | 데이터셋 등록/관리 GUI | 일부 완료 |
| Phase 2 | Manipulator + Celery 파이프라인 | 예정 |
| Phase 2-a | EDA 자동화 | 예정 (선택) |
| Phase 2-b | 샘플 뷰어 + 리니지 시각화 | 예정 (선택) |
| Phase 3 | 2차 수용 준비 & UX 정리 | 예정 |

## 주요 명령어

모든 서비스는 Docker Compose로 실행. Makefile이 주요 작업을 래핑함:

```bash
# 서비스
make up              # 전체 서비스 시작 (백그라운드)
make up-build        # 재빌드 후 시작
make down            # 서비스 중지
make logs SERVICE=backend  # 특정 서비스 로그 확인
make health          # 헬스체크 (curl)

# 데이터베이스 (Alembic)
make migrate         # alembic upgrade head
make migrate-down    # 한 버전 롤백
make migrate-status  # 현재 마이그레이션 버전 확인
make db-reset        # 전체 초기화 (downgrade base → upgrade head, 주의!)
make db-shell        # psql 콘솔 접속

# 백엔드 (Python / uv)
make backend-lint    # ruff check
make backend-format  # ruff format
make backend-test    # pytest -v

# 프론트엔드 (Node / npm)
make frontend-lint   # eslint
make frontend-build  # tsc + vite build
```

백엔드 단일 테스트 실행: `cd backend && uv run pytest tests/path_to_test.py -v`

## 아키텍처

```
backend/   — FastAPI + SQLAlchemy 2.0 async (asyncpg) + Alembic + Pydantic 2
frontend/  — React 18 + TypeScript + Vite + Ant Design + Zustand + React Query
infra/     — nginx 리버스 프록시 + postgres 초기화 스크립트
```

Docker Compose로 4개 서비스 운영: **postgres:16**, **backend** (Uvicorn), **frontend** (Vite 개발서버), **nginx** (포트 80 리버스 프록시). nginx가 `/api/*`는 백엔드로, 나머지는 프론트엔드로 라우팅.

### 백엔드

- **진입점:** `backend/app/main.py` — FastAPI 앱, CORS, lifespan, health 엔드포인트
- **API 라우터:** `backend/app/api/v1/` — 도메인별 분리: `dataset_groups/`, `datasets/`, `pipelines/`, `manipulators/`, `eda/`, `lineage/`, `training/`
- **ORM 모델:** `backend/app/models/all_models.py` — 전체 SQLAlchemy 모델 단일 파일 (DatasetGroup, Dataset, DatasetLineage, Manipulator, PipelineExecution, Objective)
- **비즈니스 로직:** `backend/app/services/` — 라우터와 모델 사이 서비스 레이어
- **설정:** `backend/app/core/config.py` — Pydantic Settings로 `.env` 로드; 비민감 설정은 루트 `config.ini`
- **DB 세션:** `backend/app/core/database.py` — async engine + session factory
- **스토리지:** `backend/app/core/storage.py` — 추상 스토리지 클라이언트 (로컬 파일시스템, S3 대비)
- **마이그레이션:** `backend/migrations/versions/` — Alembic은 sync 엔진 사용; 앱은 async 엔진 사용
- **패키지 매니저:** `uv` (pyproject.toml + uv.lock)

### 프론트엔드

- **진입점:** `frontend/src/main.tsx` → `App.tsx` (React Router)
- **API 클라이언트:** `frontend/src/api/` — Axios 인스턴스 + 도메인별 메서드
- **상태관리:** `frontend/src/stores/` — Zustand 스토어
- **타입:** `frontend/src/types/` — API 스키마에 대응하는 TypeScript 인터페이스
- **경로 별칭:** `@/` → `frontend/src/`
- **개발 프록시:** Vite가 `/api`를 `http://backend:8000`으로 프록시

### 핵심 도메인 개념

- **DatasetGroup**: 데이터셋 split/version의 논리적 묶음. dataset_type (RAW/SOURCE/PROCESSED/FUSION), annotation_format, task_types (JSONB) 보유
- **Dataset**: 그룹 하위의 개별 split (TRAIN/VAL/TEST/NONE) × version (semver). (group_id, split, version) 유니크 제약
- **Manipulator**: 사전 정의된 데이터 처리 함수. params_schema (JSONB)로 동적 UI 생성
- **DatasetLineage**: 파이프라인을 통한 변환 이력을 추적하는 parent→child 엣지
- **PipelineExecution**: 파이프라인 실행 이력 + Celery 태스크 추적

### 데이터셋 등록 플로우

3단계 위자드 UI:
1. 태스크 타입 선택 (다중 선택)
2. NAS 경로 검증 (COCO 어노테이션 유효성 검사, 이미지 수 확인)
3. 어노테이션 포맷 선택 + 그룹명 입력 → 등록

## 환경 설정

```bash
cp .env.example .env
# LOCAL_STORAGE_BASE, LOCAL_EDA_BASE를 접근 가능한 디렉토리로 설정
make check    # .env 및 경로 유효성 검증
make up-build
```

접속 주소: 웹 UI `http://localhost`, API 문서 `http://localhost/api/docs`, DB `localhost:5432`

## 컨벤션

- 백엔드 의존성은 pip이 아닌 `uv`로 관리
- 린팅/포매팅: Python은 `ruff`, 프론트엔드는 `eslint` + `prettier`
- 마이그레이션은 sync 엔진, 애플리케이션 코드는 async 엔진 — 혼용 금지
- 모든 API 경로는 `/api/v1` 접두사
- Docker 기동 시 `alembic upgrade head` 자동 실행
- `.env`에 시크릿 (gitignored), `config.ini`에 비민감 앱 설정
