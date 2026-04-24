# ML Platform — 데이터 관리 & 학습 자동화 플랫폼

데이터셋 관리, 파이프라인 처리, 모델 학습 자동화를 위한 통합 플랫폼.

**현재 상태 (v7.9, 2026-04).** Phase 1 완료 · Phase 2 거의 마무리 (Classification DAG / Celery
runner / Manipulator 26종 / Dataset 3계층 분리 완료). Automation 목업이 별도 브랜치에서 진행 중.

---

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/seungkeolkim/data-model-management-platform.git
cd data-model-management-platform

# 2. 환경 파일 복사 및 수정
cp .env.example .env
# .env 에서 아래 항목 반드시 설정:
#   LOCAL_STORAGE_BASE  ← 플랫폼이 관리하는 데이터셋 저장 경로
#   LOCAL_UPLOAD_BASE   ← 사용자가 RAW 를 미리 올려둘 업로드 전용 경로
#   POSTGRES_PASSWORD   ← DB 비밀번호
#   SECRET_KEY          ← 랜덤 시크릿 키

# 3. 환경 사전 검사
make check

# 4. 서비스 시작 (4개 컨테이너: postgres / backend / celery-worker / frontend / nginx)
make up-build

# 5. 헬스체크
make health
```

접속 URL:
- **웹 UI**: http://localhost:18080
- **API 문서 (Swagger)**: http://localhost:18080/api/docs
- **ReDoc**: http://localhost:18080/api/redoc
- **DB (호스트)**: `localhost:15432`

---

## 프로젝트 구조

```
.
├── backend/                    # FastAPI + SQLAlchemy 2.0 async
│   ├── app/
│   │   ├── api/v1/             # REST 라우터 (도메인별: dataset_groups / datasets /
│   │   │                       #   pipelines / manipulators / eda / lineage /
│   │   │                       #   filebrowser / training)
│   │   ├── core/               # config, database, storage
│   │   ├── models/             # SQLAlchemy ORM (all_models.py 단일 파일)
│   │   ├── schemas/            # Pydantic 스키마
│   │   ├── services/           # 비즈니스 로직
│   │   ├── tasks/              # Celery 태스크 (파이프라인 / RAW 등록)
│   │   ├── manipulators/       # lib/manipulators 의 re-export 래퍼
│   │   └── pipeline/           # lib/pipeline 의 re-export 래퍼
│   ├── lib/                    # 순수 로직 (DB/FastAPI 무의존)
│   │   ├── pipeline/           # DAG executor, IO 파서(COCO/YOLO), manifest
│   │   ├── manipulators/       # UnitManipulator 구현체 26종 + REGISTRY
│   │   └── classification/     # Classification ingest (manifest.jsonl)
│   ├── migrations/             # Alembic 마이그레이션 (030 까지 반영)
│   └── pyproject.toml          # 의존성 (uv 관리)
│
├── frontend/                   # React 18 + TypeScript + Vite + Ant Design
│   └── src/
│       ├── api/                # Axios API 클라이언트
│       ├── components/         # UI 컴포넌트 (pipeline / dataset / automation / ...)
│       ├── pages/              # 페이지
│       ├── pipeline-sdk/       # 파이프라인 에디터 SDK (React Flow 기반)
│       ├── dataset-display-sdk/# 데이터셋 상세 뷰어 SDK (task type 별 분기)
│       ├── mocks/              # 프론트 전용 mock fixture (현재 automation 목업)
│       ├── stores/             # Zustand 스토어
│       └── types/              # TypeScript 타입
│
├── infra/
│   ├── nginx/                  # 리버스 프록시 설정 (포트 18080)
│   └── postgres/init/          # DB 초기화 SQL
│
├── scripts/
│   ├── setup_dev.sh            # 개발 환경 구축
│   ├── check_env.sh            # .env 필수값 + 경로 검증
│   └── init_db.sh              # Alembic upgrade head
│
├── docs_for_claude/            # 진행 중 핸드오프 / 설계 문서
├── docs_history/handoffs/      # 완료된 핸드오프 아카이브 (001~025)
├── objective_n_plan_7th.md     # 현행 설계서 (v7.9)
├── .env.example                # 환경변수 예시
├── config.ini                  # 비민감 설정
├── docker-compose.yml
├── CLAUDE.md                   # 개발 가이드 (Claude Code / 사람 공용)
└── Makefile                    # 개발 편의 명령어
```

---

## 설정 파일

### `.env` (민감 정보 — git 제외)

```ini
POSTGRES_USER=mlplatform
POSTGRES_PASSWORD=...              # ← 변경 필수
POSTGRES_DB=mlplatform
POSTGRES_PORT=5432
POSTGRES_EXTERNAL_PORT=15432       # 호스트에서 DB 접근 시 포트

LOCAL_STORAGE_BASE=/mnt/nas/datasets   # ← 플랫폼 관리 경로
LOCAL_UPLOAD_BASE=/mnt/nas/uploads     # ← 사용자 업로드 경로 (RAW 등록 전)

SECRET_KEY=...                     # ← 변경 필수
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
```

---

## NAS 스토리지 구조

### Detection (COCO / YOLO)

```
{LOCAL_STORAGE_BASE}/
└── {raw|source|processed|fusion}/{group_name}/{split}/{version}/
    ├── images/
    └── annotation.json       # COCO / YOLO 는 data.yaml + labels/ 디렉토리
```

### Classification (v7.5 — filename-identity)

```
{LOCAL_STORAGE_BASE}/
└── {raw|source|processed|fusion}/{group_name}/{split}/{version}/
    ├── images/               # 평면 구조, basename 이 identity
    ├── manifest.jsonl        # 한 줄 = 한 이미지 { filename, original_filename, labels }
    └── head_schema.json      # DatasetGroup.head_schema 의 불변 스냅샷
```

**RAW 등록 방식:**
- **Detection RAW**: 사용자가 `LOCAL_UPLOAD_BASE` 에 이미지·annotation 을 미리 배치 → GUI 3단계 위자드로 등록
- **Classification RAW**: `<root>/<head>/<class>/<images>` 2레벨 폴더 구조로 업로드 → GUI 에서 split 별로 등록

---

## 주요 API 엔드포인트

모든 경로는 `/api/v1` 접두사.

### 데이터셋 그룹

| Method | Path | 설명 |
|--------|------|------|
| GET | `/dataset-groups` | 그룹 목록 (필터 / 정렬 / 페이지네이션) |
| POST | `/dataset-groups` | 그룹 직접 생성 |
| GET | `/dataset-groups/{id}` | 그룹 상세 |
| PATCH | `/dataset-groups/{id}` | 그룹 수정 |
| DELETE | `/dataset-groups/{id}` | 그룹 삭제 |
| POST | `/dataset-groups/register` | Detection RAW 등록 (202 + Celery) |
| POST | `/dataset-groups/register-classification` | Classification RAW 등록 (202 + Celery) |
| POST | `/dataset-groups/validate-format` | 어노테이션 포맷 사전 검증 |
| GET | `/dataset-groups/next-version` | 다음 버전 번호 조회 |

### 데이터셋 (DatasetVersion)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/datasets` | DatasetVersion 목록 |
| GET | `/datasets/{id}` | 단건 조회 |
| PATCH | `/datasets/{id}` | 수정 |
| DELETE | `/datasets/{id}` | 삭제 |
| POST | `/datasets/{id}/validate` | 무결성 검증 |
| GET | `/datasets/{id}/samples` | 샘플 뷰어 (이미지 + bbox / head_schema) |
| GET | `/datasets/{id}/eda` | EDA 통계 |
| GET | `/datasets/{id}/lineage` | Lineage 그래프 |

### 파이프라인 / Manipulator

| Method | Path | 설명 |
|--------|------|------|
| GET | `/manipulators` | Manipulator 목록 (26종, params_schema 포함) |
| POST | `/pipelines/validate` | PipelineConfig 정적 검증 |
| POST | `/pipelines/preview-schema` | 출력 schema 미리 계산 (classification) |
| POST | `/pipelines/execute` | 파이프라인 실행 (202 + Celery dispatch) |
| GET | `/pipelines` | 실행 이력 목록 |
| GET | `/pipelines/{execution_id}/status` | 실행 상태 / 진행률 |

### 보조

| Method | Path | 설명 |
|--------|------|------|
| GET | `/filebrowser/list` | 서버 파일 브라우저 (LOCAL_UPLOAD_BASE 탐색) |
| GET | `/filebrowser/classification-scan` | classification 폴더 구조 사전 스캔 |
| GET | `/eda/{dataset_id}` / `POST /eda/{dataset_id}/run` | EDA 조회 / 실행 |
| GET | `/lineage/{dataset_id}/upstream` / `downstream` | Lineage 상류 / 하류 |
| GET | `/health` | 헬스체크 (DB + 스토리지) |

---

## 데이터 모델 (v7.9 3계층)

```
DatasetGroup (정적)
  └─ DatasetSplit (정적)       — unique(group_id, split)
     └─ DatasetVersion (동적)   — unique(split_id, version)
```

### DatasetGroup (그룹 정적 메타)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | PK |
| `name` | String | 그룹명 (예: `helmet_classification`) |
| `dataset_type` | String | `RAW` \| `SOURCE` \| `PROCESSED` \| `FUSION` |
| `annotation_format` | String | `COCO` \| `YOLO` \| `ATTR_JSON` \| `CLS_MANIFEST` \| `CUSTOM` \| `NONE` |
| `task_types` | JSONB | `["DETECTION", "CLASSIFICATION", ...]` 다중 선택 |
| `modality` | String | `RGB` \| `THERMAL` \| `DEPTH` \| `MULTISPECTRAL` |
| `head_schema` | JSONB | **Classification SSOT** (v7.8 단일 원칙 — 같은 그룹 안에서는 불변) |
| `description` | Text | 설명 |
| `created_at` / `updated_at` | Timestamp | 생성 / 수정 시각 (자식 변경 시 자동 전파) |

### DatasetSplit (v7.9 신규 — 정적 슬롯)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | PK |
| `group_id` | UUID | FK → DatasetGroup |
| `split` | String | `TRAIN` \| `VAL` \| `TEST` \| `NONE` |
| `created_at` | Timestamp | — |

`(group_id, split)` UNIQUE. 한 번 만들어지면 버전이 쌓여도 재사용.

### DatasetVersion (v7.9 — 기존 `Dataset` rename)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | PK |
| `split_id` | UUID | FK → DatasetSplit |
| `version` | String | `{major}.{minor}` (예: `1.0`, `2.1`) |
| `annotation_format` | String | 그룹 기본값 override 가능 |
| `storage_uri` | String | NAS 상대경로 |
| `status` | String | `PENDING` \| `PROCESSING` \| `READY` \| `READY_WITH_SKIPS` \| `ERROR` |
| `image_count` | Integer | 이미지 수 |
| `class_count` | Integer | 클래스 수 (detection 전용) |
| `annotation_files` | JSONB | 파일명 목록 |
| `metadata` | JSONB | EDA 결과 / classification class_info 등 |

`(split_id, version)` UNIQUE. ORM 편의로 `version.split / group / group_id` 는 `split_slot`
relationship 경유 association_proxy 로 노출 — 구 코드 호환 유지.

### 기타

- **DatasetLineage**: 파이프라인 실행 변환 이력 (parent → child DatasetVersion 엣지)
- **Manipulator**: 사전 정의된 데이터 처리 함수 26종. `params_schema` JSONB 로 동적 UI 생성
- **PipelineExecution**: 파이프라인 실행 이력 + Celery 태스크 추적

---

## Roadmap

전체 로드맵은 **Step 1 ~ 5** 로 구성. 현재 Phase 0 ~ 3 은 Step 1 을 세부 phase 로 나눈 것.

| Step | 범위 | 상태 |
|------|------|------|
| **Step 1** | 데이터셋 관리 (Phase 0 ~ 3) | Phase 2 거의 마무리 |
| **Step 2** | 학습 자동화 (단일/다중 GPU) | 예정 |
| **Step 3** | K8S 클러스터화, GPU 스케줄링 | 미착수 |
| **Step 4** | Label Studio / Synthetic Data / MLOps | 미착수 |
| **Step 5** | Generative Model MLOps | 미착수 |

### Step 1 세부 Phase

| Phase | 기능 | 상태 |
|-------|------|------|
| Phase 0 | 인프라 / DB 스키마 / `/health` | ✅ 완료 |
| Phase 1 | 데이터셋 등록·관리 GUI (Detection + Classification) | ✅ 완료 |
| Phase 2 | Manipulator + Celery 파이프라인 + GUI 에디터 | 🔧 거의 마무리 (26 manipulator · Classification DAG · 3계층 분리 완료, Automation 실구현 대기) |
| Phase 2-a | EDA 자동화 | ✅ 완료 |
| Phase 2-b | 샘플 뷰어 + Lineage 시각화 | ✅ 완료 |
| Phase 3 | 2차 수용 준비 + UX 정리 | 예정 |

---

## 구현 완료 내용 요약

### Phase 1 — 데이터셋 등록·관리 (완료)

- **Detection RAW 등록 3단계 위자드** (DatasetRegisterModal)
  1. 태스크 타입 선택 (다중) 2. 서버 파일 브라우저로 이미지 / 어노테이션 경로 선택 3. 포맷 + 그룹명 입력
- **Classification RAW 등록 전용 플로우** (v7.5) — `<root>/<head>/<class>/<images>` 2 레벨 폴더 기반.
  filename-identity + per-head manifest.jsonl + head_schema.json FS 스냅샷
- **그룹 중심 목록 뷰** — task_type / dataset_type / annotation_format / split 필터, 정렬, 이미지 수 집계
- **샘플 뷰어** — Detection 은 bbox 오버레이, Classification 은 head_schema 기반 라벨 테이블
- **Lineage 탭** — React Flow DAG (Detection / Classification 공유)

### Phase 2 — 파이프라인 (거의 마무리)

- **통일 포맷 DAG Executor** — Phase A (annotation) + Phase B (이미지 실체화) 분리
- **Manipulator 26종 실구현**
  - Detection 12: format_convert (COCO / YOLO / VisDrone), merge, filter 3종, remap, rotate, mask, sample
  - Classification 14: rename_head / rename_class / reorder_heads / reorder_classes / select_heads,
    merge_datasets / merge_classes, demote_head_to_single_label, sample_n_images, rotate_image,
    add_head, set_head_labels_for_all_images, crop_image, filter_by_class
- **파이프라인 에디터 SDK** — React Flow + Node SDK (5 NodeKind, 자동 발견 registry)
- **Celery 비동기 실행** — PostgreSQL broker, 큐 3종 (pipeline / eda / default), worker concurrency 4
- **head_schema SSOT 단일 원칙** (v7.8) — 같은 그룹 내 schema 불변, 두 진입로 (RAW 등록 / 파이프라인 실행) 에서 구조적 강제
- **Dataset 3계층 분리** (v7.9) — DatasetGroup → DatasetSplit → DatasetVersion. Pipeline 이 FK 무결성으로 split 참조 가능

### 현재 진행 중 (feature/pipeline-automation-mockup 브랜치)

- **Automation 목업 UI** — 관리 페이지 / 상세 탭 / 실행 이력 / 수동 재실행 2-버튼 모달.
  프론트 mock fixture 만, 백엔드 미착수
- **후속 설계 — Pipeline / PipelineRun / PipelineAutomation 3 엔티티 분리** (027 설계 문서)
  - Pipeline 은 `(group, split)` 까지만 정적, DatasetVersion 은 run-time 해석
  - 사용자 명시 major.minor 버전 정책
  - 실구현은 별도 브랜치로 착수 예정

---

## 기술 스택

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async · asyncpg), Alembic, Pydantic v2, Celery
  - 패키지 관리: **uv** (pyproject.toml + uv.lock)
  - 린트 / 포매팅: **ruff**
- **DB**: PostgreSQL 16
- **Storage**: NAS 직접 마운트 + `StorageClient` 추상화 (S3 대비)
- **Frontend**: React 18, TypeScript, Vite, Ant Design 5, TanStack Query v5, Zustand,
  **React Flow (@xyflow/react)**
- **Infra**: Docker, Docker Compose, Nginx (리버스 프록시, 포트 18080)

---

## 개발 명령어 (Makefile)

```bash
# 서비스
make up                    # 전체 서비스 시작 (백그라운드)
make up-build              # 재빌드 후 시작
make down                  # 서비스 중단
make logs SERVICE=backend  # 특정 서비스 로그 확인
make health                # 헬스체크 (curl)

# 데이터베이스
make migrate               # alembic upgrade head
make migrate-down          # 한 버전 롤백
make migrate-status        # 현재 마이그레이션 버전
make db-reset              # 전체 초기화 (주의!)
make db-shell              # psql 콘솔 접속

# 백엔드
make backend-lint          # ruff check
make backend-format        # ruff format
make backend-test          # pytest -v

# 프론트엔드
make frontend-lint         # eslint
make frontend-build        # tsc + vite build

# 도움말
make help                  # 전체 명령어 목록
```

추가 개발 가이드 (아키텍처 / 네이밍 / 컨벤션) 는 [CLAUDE.md](CLAUDE.md) 참조.

---

## 문서

- **현행 설계서**: [`objective_n_plan_7th.md`](objective_n_plan_7th.md) (v7.9)
- **진행 중 핸드오프**: [`docs_for_claude/`](docs_for_claude/)
  - 026 — Automation 목업 완료
  - 027 — Pipeline / PipelineRun / PipelineAutomation 3 엔티티 분리 설계
  - 023 — Automation 기술 검토 (참조 원문)
- **완료 핸드오프 아카이브**: [`docs_history/handoffs/`](docs_history/handoffs/) (001 ~ 025)
- **노드 SDK 가이드**: [`docs/pipeline-node-sdk-guide.md`](docs/pipeline-node-sdk-guide.md)

---

## GitHub

Repository: https://github.com/seungkeolkim/data-model-management-platform
