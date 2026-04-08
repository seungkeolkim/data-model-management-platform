# ML Platform — 데이터 관리 & 학습 자동화 플랫폼

데이터셋 관리, 파이프라인 처리, 모델 학습 자동화를 위한 통합 플랫폼.  
**Phase 1 (Dataset 등록/관리 GUI)** 구현 완료 상태.

---

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/seungkeolkim/data-model-management-platform.git
cd data-model-management-platform

# 2. 환경 파일 복사 및 수정
cp .env.example .env
# .env에서 아래 항목 반드시 설정:
#   LOCAL_STORAGE_BASE  ← 데이터셋 NAS 마운트 경로 (개발: ./data/datasets)
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
- **API 문서 (Swagger)**: http://localhost/api/docs
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
│   │   ├── tasks/          # Celery 태스크 (Phase 2)
│   │   └── pipeline/       # 파이프라인 인터페이스 (Phase 2)
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
│   ├── check_env.sh        # 환경 사전 검사 (.env 필수값 + NAS 경로 확인)
│   └── init_db.sh          # DB 마이그레이션 (직접 실행)
│
├── data/                   # 개발용 로컬 데이터 (NAS 대체)
│   ├── datasets/
│   └── eda/
│
├── .env.example            # 환경변수 예시 (반드시 .env로 복사 후 수정)
├── config.ini              # 비민감 설정 (NAS 디렉토리 규칙 등)
├── docker-compose.yml
├── environment.yml         # conda 환경 설정
└── Makefile                # 개발 편의 명령어
```

---

## 설정 파일

### `.env` (민감 정보 — git에 포함되지 않음)

```ini
POSTGRES_USER=mlplatform
POSTGRES_PASSWORD=...           # ← 변경 필수
POSTGRES_DB=mlplatform
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_EXTERNAL_PORT=15432      # ← 호스트에서 DB 접근 시 포트

LOCAL_STORAGE_BASE=/mnt/nas/datasets  # ← NAS 마운트 경로 변경 필수

SECRET_KEY=...                  # ← 변경 필수
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

```
{LOCAL_STORAGE_BASE}/
├── raw/{group_name}/{split}/{version}/
│   ├── images/
│   └── annotation.json
├── source/...
├── processed/...
└── fusion/...

```

데이터셋 등록 시 **`storage_uri`** 는 `LOCAL_STORAGE_BASE` 기준 상대경로로 입력합니다.  
예) `LOCAL_STORAGE_BASE=./data/datasets` → storage_uri: `raw/my_coco/train/v1.0.0`

---

## API 엔드포인트 (현재 활성)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 (DB + 스토리지 상태) |
| GET | `/api/v1/dataset-groups` | 데이터셋 그룹 목록 (페이지네이션, 검색) |
| POST | `/api/v1/dataset-groups` | 그룹 직접 생성 |
| GET | `/api/v1/dataset-groups/{id}` | 그룹 상세 조회 |
| PATCH | `/api/v1/dataset-groups/{id}` | 그룹 수정 |
| DELETE | `/api/v1/dataset-groups/{id}` | 그룹 삭제 |
| POST | `/api/v1/dataset-groups/validate-path` | NAS 경로 검증 (COCO 정합성 포함) |
| POST | `/api/v1/dataset-groups/register` | 데이터셋 등록 (GUI 3단계 플로우) |
| GET | `/api/v1/datasets` | Dataset 목록 |
| GET | `/api/v1/datasets/{id}` | Dataset 단건 조회 |
| DELETE | `/api/v1/datasets/{id}` | Dataset 삭제 |
| GET | `/api/v1/manipulators` | Manipulator 목록 |

---

## 데이터 모델 (현재)

### DatasetGroup (그룹 단위)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | PK |
| `name` | String | 그룹명 (예: my_coco_2024) |
| `dataset_type` | String | `RAW` \| `SOURCE` \| `PROCESSED` \| `FUSION` |
| `annotation_format` | String | `COCO` \| `YOLO` \| `ATTR_JSON` \| `CLS_FOLDER` \| `CUSTOM` \| `NONE` |
| `task_types` | JSONB | `["DETECTION", "SEGMENTATION", ...]` |
| `modality` | String | `RGB` \| `THERMAL` \| `DEPTH` \| `MULTISPECTRAL` |
| `description` | Text | 설명 |
| `created_at` / `updated_at` | Timestamp | 생성/수정 시각 |

### Dataset (split × version 단위)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | PK |
| `group_id` | UUID | FK → DatasetGroup |
| `split` | String | `TRAIN` \| `VAL` \| `TEST` \| `NONE` |
| `version` | String | `v1.0.0` 형식, 자동 증분 |
| `annotation_format` | String | 그룹 기본값 override 가능 |
| `storage_uri` | String | NAS 상대경로 |
| `status` | String | `PENDING` \| `PROCESSING` \| `READY` \| `ERROR` |
| `image_count` | Integer | 이미지 수 (자동 카운트) |
| `class_count` | Integer | 클래스 수 (validation 후 채워짐) |

---

## 개발 단계 (Roadmap)

| Phase | 기능 | 상태 |
|-------|------|------|
| **Phase 0** | 인프라, DB 스키마, `/health` | ✅ 완료 |
| **Phase 1** | Dataset 등록/관리 GUI | ✅ 완료 |
| **Phase 2** | Manipulator + Celery 파이프라인 + GUI 에디터 | 🔧 진행 중 (실행엔진/Celery/GUI 에디터/10종 manipulator 완료, 잔여 manipulator+검증 미완) |
| **Phase 2-a** | EDA 자동화 | ✅ 완료 |
| **Phase 2-b** | 샘플 뷰어 + Lineage 시각화 | ✅ 완료 |
| **Phase 3** | 학습 실행 자동화 | ⏳ |

---

## Phase 1 완료 내용

### 구현된 기능

- **데이터셋 등록 3단계 UI** (DatasetRegisterModal)
  1. **사용 목적 선택** — task_types 멀티 드롭다운 (Detection / Segmentation / Classification / Attribute / Zero-Shot)
  2. **NAS 경로 확인** — 경로 존재 여부 검증, 이미지 수·annotation 파일 존재 표시
  3. **Annotation Format 선택 + 그룹명 입력 → 등록**
- **Check Data Validation 버튼** — 팝업으로 경로·파일·COCO 정합성 결과 표시 (COCO 선택 시 annotation 수·클래스 목록 포함)
- **데이터셋 목록 페이지** — task_types·포맷·Split 태그·이미지 수·상태·등록일 표시, 검색 및 페이지네이션
- **Split 추가** — 기존 그룹에 TRAIN/VAL/TEST Split 추가 가능
- **환경변수 분리** — `LOCAL_STORAGE_BASE` 필수 환경변수화 (하드코딩 제거)

### 주요 설계 결정

- `DatasetGroup.dataset_type` = `"RAW"` 고정 (raw 등록 시). 이후 유형별 처리 분리 예정
- annotation 정합성 체크 코드(`_validate_coco_annotation`)는 구현되어 있으나 등록 단계에서는 강제하지 않음 — Check Data Validation 버튼으로 수동 확인 가능
- 버전은 `v1.0.0`부터 자동 증분 (`vX.Y.Z`, patch 단위)

---

## Phase 1 — 미결 사항 (결정 필요)

> 아래 항목들은 Phase 1 과정에서 설계 방향을 결정해야 할 오픈 이슈입니다.  
> 구현 전 팀 내 논의 및 확정이 필요합니다.

### 🔴 1. 데이터셋 유형별 등록/처리 흐름 분리

현재는 모든 등록이 동일한 3단계 플로우를 사용하지만,  
**RAW / SOURCE / PROCESSED / FUSION** 각 유형은 업로드 방식, 필수 파일 구조, 검증 방식이 다를 수 있습니다.

**검토 포인트**:
- RAW: 사용자가 직접 NAS에 파일 배치 후 경로 등록 (현재 방식)
- SOURCE: RAW로부터 전처리 파이프라인 실행 결과물 → 자동 생성이 자연스러운가?
- PROCESSED: 파이프라인(Manipulator) 실행 결과물 → DB 자동 기록 vs 수동 등록?
- FUSION: 여러 SOURCE 병합 결과 → 병합 전 선택 UI 필요
- 유형별로 등록 Modal을 분리할지, 공통 플로우에 조건 분기를 넣을지?

**영향 범위**: `DatasetRegisterModal`, `DatasetGroupService.register_dataset`, 스토리지 경로 규칙

---

### 🔴 2. 데이터셋 유형별 DB 테이블 분리 여부

현재는 `dataset_groups` 단일 테이블에 `dataset_type` 컬럼으로 구분합니다.  
유형별로 필요한 메타데이터 필드가 크게 다를 경우 테이블 분리가 필요할 수 있습니다.

**검토 포인트**:
- **단일 테이블 (현재 방식)**: `extra JSONB`로 유형별 추가 필드 수용 — 단순하지만 스키마가 느슨해짐
- **유형별 테이블 분리**: `raw_datasets`, `source_datasets`, `processed_datasets`, `fusion_datasets` — 명시적이지만 조인 쿼리 복잡도 증가
- **상속(ORM Polymorphism)**: `dataset_groups` 기본 테이블 + 유형별 서브 테이블 (joined table inheritance) — SQLAlchemy 지원, 확장성 좋음
- Lineage가 모든 유형을 연결해야 하므로 공통 참조 가능한 구조 필요

**의사결정 기준**: 유형별 추가 필드가 얼마나 많은가? Lineage 참조 방식은?

---

### 🟡 3. DatasetGroup의 Split 관리 방식

현재 한 그룹(DatasetGroup) 아래에 TRAIN/VAL/TEST Split이 각각 별도 `Dataset` 레코드로 존재합니다.

**검토 포인트**:
- Split 추가 시 그룹의 `annotation_format`, `task_types` 등을 재사용할지, Split마다 override 가능하게 할지
- TRAIN + VAL + TEST가 항상 세트로 등록되는 경우 vs 단계적으로 추가되는 경우 — UI 플로우 차이
- Split 간 이미지 중복 방지 정책 (같은 이미지가 TRAIN/VAL에 동시에 들어가는 것을 막을지)
- Split이 없는 단일 데이터셋(`split=NONE`)의 용도와 처리 방식 명확화
- 버전(`v1.0.0`) 관리 — Split 단위 버전 vs 그룹 단위 버전 통합 여부

---

### 🟡 4. 데이터셋 목록/상세 화면 표시 방식

현재 목록은 그룹 단위로 표시하고, Split은 태그로 압축해서 보여줍니다.

**검토 포인트**:
- **그룹 중심 뷰 (현재)**: 그룹 → Split 드릴다운 — 계층 구조 명확, 그룹 수가 많을 때 유리
- **Split 중심 뷰**: 각 Split을 독립 행으로 표시 — 이미지 수·상태를 직접 비교하기 쉬움
- **유형별 탭**: RAW / SOURCE / PROCESSED / FUSION 탭으로 분리 — 유형이 확정되면 자연스러운 분리
- 상세 페이지: 이미지 샘플 썸네일 표시 여부, annotation 미리보기 여부
- 검색/필터 강화: task_type 필터, annotation_format 필터, 날짜 범위 필터 등

---

## 기술 스택

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery
- **DB**: PostgreSQL 16
- **Storage**: NAS 직접 마운트 (StorageClient 추상화 — 향후 S3 전환 가능)
- **Frontend**: React 18, TypeScript, Vite, Ant Design 5, TanStack Query v5, Zustand
- **Infra**: Docker, Docker Compose, Nginx

---

## 개발 명령어 (Makefile)

```bash
make up                    # 서비스 시작
make down                  # 서비스 중단
make logs SERVICE=backend  # 로그 확인
make migrate               # DB 마이그레이션
make db-shell              # PostgreSQL 콘솔
make health                # 헬스체크
make backend-lint          # 백엔드 린트
make help                  # 전체 명령어 목록
```

---

## GitHub

Repository: https://github.com/seungkeolkim/data-model-management-platform
