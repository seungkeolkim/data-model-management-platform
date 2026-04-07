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

Step 1의 세부적인 작업:
- 1차 설계: `docs_history/objective_n_plan_1st.md`
- 2차 설계: `docs_history/objective_n_plan_2nd.md`
- 3차 설계: `docs_history/objective_n_plan_3rd.md`
- 4차 설계: `docs_history/objective_n_plan_4th.md`
- **5차 설계 (현행)**: `objective_n_plan_5th.md`
- 파이프라인/Manipulator 핸드오프: `docs_for_claude/003-pipeline-manipulator-handoff.md`

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 0 | 인프라, DB 스키마, /health | 완료 |
| Phase 1 | 데이터셋 등록/관리 GUI | 완료 |
| Phase 2 | Manipulator + Celery 파이프라인 + GUI 에디터 | **진행 중** (실행엔진/Celery/GUI 에디터/3종 manipulator 완료. 추가 manipulator/GUI 고도화 미완) |
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
- **API 라우터:** `backend/app/api/v1/` — 도메인별 분리: `dataset_groups/`, `datasets/`, `pipelines/`, `manipulators/`, `eda/`, `lineage/`, `training/`, `filebrowser/`
- **ORM 모델:** `backend/app/models/all_models.py` — 전체 SQLAlchemy 모델 단일 파일 (DatasetGroup, Dataset, DatasetLineage, Manipulator, PipelineExecution, Objective)
- **비즈니스 로직:** `backend/app/services/` — 라우터와 모델 사이 서비스 레이어
- **설정:** `backend/app/core/config.py` — Pydantic Settings로 `.env` 로드; 비민감 설정은 루트 `config.ini`
- **DB 세션:** `backend/app/core/database.py` — async engine + session factory
- **스토리지:** `backend/app/core/storage.py` — 추상 스토리지 클라이언트 (로컬 파일시스템, S3 대비)
- **마이그레이션:** `backend/migrations/versions/` — Alembic은 sync 엔진 사용; 앱은 async 엔진 사용
- **패키지 매니저:** `uv` (pyproject.toml + uv.lock)

### lib/ — 순수 로직 패키지 (DB/FastAPI 무의존)

파이프라인 실행, Manipulator, IO 파서 등 핵심 로직을 `backend/lib/`에 분리.
`app/pipeline/`과 `app/manipulators/`는 `lib/`의 re-export 래퍼로 유지 (기존 import 호환).

- **`lib/pipeline/models.py`** — DatasetMeta, Annotation, ImageRecord, ImagePlan, DatasetPlan 등 핵심 데이터 모델
- **`lib/pipeline/manipulator.py`** — UnitManipulator ABC (transform_annotation + build_image_manipulation)
- **`lib/pipeline/executor.py`** — PipelineExecutor (Phase A: annotation 처리, Phase B: 이미지 실체화)
- **`lib/pipeline/image_executor.py`** — ImageExecutor (이미지 파일 복사/변환)
- **`lib/pipeline/config.py`** — PipelineConfig, SourceConfig, ManipulatorConfig (Pydantic)
- **`lib/pipeline/storage_protocol.py`** — StorageProtocol (typing.Protocol) — app.core.storage.StorageClient와 분리
- **`lib/pipeline/io/`** — COCO JSON / YOLO txt 파서·라이터, 클래스 매핑 테이블
- **`lib/manipulators/`** — UnitManipulator 구현체 + MANIPULATOR_REGISTRY

**절대 원칙:** `lib/` → `app/` import 금지. `app/` → `lib/` import만 허용.

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

### 데이터셋 타입 계층 관계

데이터 상태는 **RAW / SOURCE / PROCESSED / FUSION** 4가지로 고정. 코드, 문서, 대화 모두 이 표기를 일관되게 사용할 것.

```
RAW
 └─(format_convert, remap 등)──▶ SOURCE
                                    └─(augment, filter 등)──▶ PROCESSED
                                                                │
                                    (SOURCE/PROCESSED)─────────┴─(merge)──▶ FUSION
```

| 타입 | 의미 |
|---|---|
| RAW | 플랫폼 외부에서 수동으로 NAS에 올리고 GUI로 직접 등록. 파이프라인 입력으로는 쓰지 않는 것이 원칙 |
| SOURCE | RAW를 파이프라인으로 정제한 결과 (예: VisDrone→COCO, class remap). 파이프라인의 실질적 입력 시작점 |
| PROCESSED | SOURCE에 augmentation/filter 등을 적용한 학습용 데이터 |
| FUSION | 여러 SOURCE/PROCESSED를 merge한 결과 |

**등록 원칙 (절대 규칙)**
- RAW: 사람이 NAS에 직접 업로드 후 GUI로 등록
- SOURCE / PROCESSED / FUSION: 반드시 파이프라인을 통해서만 생성. 사람의 직접 파일 수정 및 DB 조작 금지

**Lineage 메커니즘**

파이프라인 실행 1회 = 새로운 Dataset 1개 생성 + lineage 엣지 자동 기록.
Palantir Foundry의 data lineage / Spark RDD transformation plan과 동일한 개념.

```
[SOURCE A]──[per-source ops]──┐
                               ├──[merge]──[post-merge ops]──▶ [FUSION C]
[SOURCE B]──[per-source ops]──┘
```

생성되는 lineage 엣지: `A → C`, `B → C` (각각 transform_config 스냅샷 포함)

- **재현**: transform_config 스냅샷으로 동일 파이프라인 언제든 재실행 가능
- **역추적**: 특정 Dataset의 upstream 전체를 재귀 CTE로 조회
- **영향 분석**: 특정 Dataset 변경 시 downstream 영향 범위 파악
- **시각화**: Phase 2-b — React Flow DAG (노드=Dataset, 엣지=변형 내용)

타입 간 변환 경로를 강제하는 DB/코드 제약은 없음 — `dataset_type`은 DatasetGroup의 속성값일 뿐.

### RAW 데이터셋 등록 플로우

사전 조건: 사용자가 등록할 데이터를 `LOCAL_UPLOAD_BASE` 경로에 미리 복사해 둔다 (컨테이너는 해당 경로만 마운트).

3단계 위자드 UI:
1. **태스크 타입 선택** — 다중 선택 (DETECTION, SEGMENTATION 등)
2. **파일 선택** — 서버 파일 브라우저(`GET /api/v1/filebrowser/list`)로 `/mnt/uploads` 하위를 탐색
   - 이미지 디렉토리 1개 선택 (directory 모드)
   - 어노테이션 파일 1개 이상 선택 (file 모드, 다중 선택 가능)
3. **어노테이션 포맷 + 그룹명 입력 → 등록**
   - 백엔드가 선택된 경로에서 `LOCAL_STORAGE_BASE`로 파일을 **copy** (원본 유지, move 아님)
   - 버전 자동 생성, 어노테이션 파일명 DB 저장 (`annotation_files` JSONB 컬럼)

## 환경 설정

```bash
cp .env.example .env
# 아래 2개 경로를 접근 가능한 디렉토리로 설정:
#   LOCAL_STORAGE_BASE — 플랫폼이 관리하는 데이터셋 저장 경로
#   LOCAL_UPLOAD_BASE  — 사용자가 등록 전 데이터를 올려두는 업로드 전용 경로
make check    # .env 및 경로 유효성 검증
make up-build
```

접속 주소: 웹 UI `http://localhost:18080`, API 문서 `http://localhost:18080/api/docs`, DB `localhost:15432`

## 컨벤션

- 백엔드 의존성은 pip이 아닌 `uv`로 관리
- 린팅/포매팅: Python은 `ruff`, 프론트엔드는 `eslint` + `prettier`
- 마이그레이션은 sync 엔진, 애플리케이션 코드는 async 엔진 — 혼용 금지
- 모든 API 경로는 `/api/v1` 접두사
- Docker 기동 시 `alembic upgrade head` 자동 실행
- `.env`에 시크릿 (gitignored), `config.ini`에 비민감 앱 설정

### 네이밍 규칙 (절대 준수)

**함수명·변수명은 한 글자 또는 한 단어 금지.** 이름만 보고 무엇을 하는지 알 수 있어야 한다.

- 나쁜 예: `_m()`, `s`, `p`, `cfg`
- 좋은 예: `_build_manipulator_seed_record()`, `storage_backend_config`, `annotation_file_path`, `app_config`

**주석은 한글로 충실하게 작성.** 반년 뒤의 나는 다른 사람이다. 로직이 자명하지 않으면 반드시 설명을 달 것.

- 함수·클래스는 docstring으로 역할, 인자, 주의사항을 기술한다
- 단순한 루프 변수(`for item in items`)는 예외적으로 짧아도 무방하나, 용도가 불분명하면 풀어서 쓴다
