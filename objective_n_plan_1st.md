# 데이터 관리 & 학습 자동화 플랫폼

> **작업지시서 v1.0** | 1차 개발 범위 기준

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [전체 로드맵](#2-전체-로드맵)
3. [설계 원칙](#3-설계-원칙)
4. [기술 스택](#4-기술-스택)
5. [시스템 아키텍처](#5-시스템-아키텍처)
6. [데이터 저장 구조](#6-데이터-저장-구조)
7. [DB Schema](#7-db-schema)
8. [백엔드 프로젝트 구조](#8-백엔드-프로젝트-구조)
9. [핵심 설계 — Pipeline 실행 구조](#9-핵심-설계--pipeline-실행-구조)
10. [Manipulator 목록](#10-manipulator-목록)
11. [데이터 등록 플로우](#11-데이터-등록-플로우)
12. [Frontend 구조](#12-frontend-구조)
13. [개발 Phase](#13-개발-phase)
14. [확장 포인트](#14-확장-포인트)

---

## 1. 프로젝트 개요

Ubuntu 환경에서 Docker Compose로 운영하는 **데이터 관리 및 학습 자동화 플랫폼**입니다.
Data Scientist가 쉽고 빠르게 모델 학습을 위한 의사결정 정보를 얻을 수 있도록 설계합니다.

| 항목 | 내용 |
|---|---|
| **운영 환경** | Ubuntu + Docker Compose |
| **확장 목표** | K8S(K3S) 클러스터 |
| **주요 Task** | Detection, Segmentation, Attr Classification, Zero-shot, 열화상 |
| **데이터 포맷** | COCO, YOLO, ATTR_JSON, CLS_FOLDER, CUSTOM |

---

## 2. 전체 로드맵

    1차 │ 데이터셋 관리                ← 현재 문서 범위
    2차 │ 학습 자동화 (단일 다중 GPU 서버)
    3차 │ 다중 GPU 서버 K8S 클러스터화, GPU 학습 스케줄링
    4차 │ Label Studio 연결, MLOps
        │ (학습 스케줄링, 데이터 자동 수집, Auto Labeling,
        │  Offline Testing, Auto Deploy 등)

---

## 3. 설계 원칙

- **지금은 단순하게, 이후엔 교체만으로 확장**  
  모든 핵심 컴포넌트는 추상화 인터페이스를 통해 접근.  
  구현체 교체 시 비즈니스 로직 수정 없음.

- **GUI를 통해서만 데이터 등록**  
  수동 DB 조작 금지. 모든 등록/수정은 플랫폼을 통해 수행하여 DB 정합성 보장.

- **임시 파일 생성 금지**  
  파이프라인 실행 시 중간 임시 파일 없이 Single-pass로 처리.

- **포맷 독립적 내부 표현**  
  내부 Annotation 구조체는 특정 포맷(COCO/YOLO)에 종속되지 않음.
  단, Detection Dataset의 경우 원천 데이터 이후 COCO 혹은 YOLO 포맷으로 고정.

- **단일 시스템 통합**  
  기능적으로 동일한 역할은 하나의 시스템으로 통합.  
  Redis 제거 → PostgreSQL 통합.

---

## 4. 기술 스택

### Infrastructure

| 항목 | 기술 | 비고 |
|---|---|---|
| OS | Ubuntu | 호스트 |
| Container | Docker + Docker Compose | 추후 K8S 확장 전제 |
| Reverse Proxy | Nginx | `/api`→FastAPI, `/`→React, `/static`→NAS |
| GPU | NVIDIA Container Toolkit | 2차 대비 설치 |

### Backend

| 항목 | 기술 | 비고 |
|---|---|---|
| Language | Python 3.11+ | |
| Framework | FastAPI | |
| ORM | SQLAlchemy 2.0 (async) | |
| Migration | Alembic | |
| Validation | Pydantic v2 | |
| Task Queue | Celery | Broker/Backend 모두 PostgreSQL |
| Image Processing | OpenCV, Pillow | 이미지 1장 단위 로드/변환/저장 |

### Database

| 항목 | 기술 | 비고 |
|---|---|---|
| RDBMS | PostgreSQL 16+ | 단일 DB로 모든 역할 통합 |
| 영속성 | Docker named volume 혹은 Data Dir 직접 Mount | `docker compose down` 상황에도 데이터 유지 |
| Celery Broker | PostgreSQL | `db+postgresql://` |
| Celery Backend | PostgreSQL | `db+postgresql://` |

> **명시적 미사용**
> - `Redis` → PostgreSQL로 완전 대체 (Celery broker/backend, 진행률 모두)
> - `MinIO` → NAS 직접 마운트 + StorageClient 추상화로 대체

### Storage

| 항목 | 기술 | 비고 |
|---|---|---|
| 실제 파일 | NAS 직접 마운트 | `/mnt/nas/datasets` |
| 추상화 | StorageClient 인터페이스 | 구현체 교체로 S3 전환 가능 |
| 1차 구현체 | LocalStorageClient | NAS 경로 직접 접근 |
| 3차 구현체 | S3StorageClient | MinIO or 클라우드 S3 |
| 파일 서빙 | Nginx static | NAS 경로 직접 마운트 |

### Frontend

| 항목 | 기술 | 비고 |
|---|---|---|
| Language | TypeScript | |
| Framework | React 18 | |
| Build Tool | Vite | |
| Server State | TanStack Query | API 상태관리, polling |
| Client State | Zustand | 필터 상태 등 |
| Table | TanStack Table | 서버사이드 정렬/필터/페이지네이션 |
| UI Components | Ant Design or shadcn/ui + Tailwind CSS | |
| Graph | React Flow | Lineage DAG (Phase 2-b) |
| Chart | ECharts | EDA 시각화 (Phase 2-a) |
| Routing | React Router v6 | |

### 2차 대비 (현재 미설치, 구조만 준비)

| 항목 | 기술 |
|---|---|
| 실험 추적 | MLflow |
| 메트릭 수집 | Prometheus |
| 모니터링 | Grafana |
| GPU 메트릭 | DCGM Exporter |
| 알림 | SMTP / SendGrid |

### 3차 대비 (현재 불필요, 설계 시 고려만)

| 항목 | 기술 |
|---|---|
| K8S 패키징 | Helm |
| ML 파이프라인 | Argo Workflows or Kubeflow Pipelines |
| GPU 스케줄링 | Volcano |
| 오토스케일링 | KEDA |
| 오브젝트 스토리지 | MinIO or 클라우드 S3 |

### 명시적 미사용 목록

| 항목 | 대체 | 이유 |
|---|---|---|
| Redis | PostgreSQL | Celery broker/backend 통합, 진행률도 DB 직접 업데이트 |
| MinIO | NAS + StorageClient | 파일 복사 비용 제거, 이중 스토리지 낭비 없음 |
| Flower | pipeline_executions 테이블 | 실행 이력 DB로 관리 |
| CRA | Vite | 빌드 속도 |
| Redux | Zustand | 보일러플레이트 최소화 |

---

## 5. 시스템 아키텍처

    [Client Browser]
          │
          ▼
    [Nginx]
      ├── /api/*     → FastAPI (Backend)
      ├── /static/*  → NAS 직접 서빙 (샘플 이미지 등)
      └── /*         → React (Frontend)

    [FastAPI]
      ├── REST API
      ├── SQLAlchemy (async) → PostgreSQL
      ├── StorageClient      → NAS (/mnt/nas/datasets)
      └── Celery.delay()     → PostgreSQL Queue

    [Celery Worker]
      ├── run_pipeline_task  → PipelineExecutor → ImageExecutor
      └── run_eda_task       → EDA 결과 → PostgreSQL (Phase 2-a)

    [PostgreSQL]
      ├── 메타데이터 (dataset_groups, datasets, lineage 등)
      ├── Celery broker / result backend
      └── pipeline_executions (진행률 포함)

    [NAS]
      └── /mnt/nas/datasets/{type}/{name}/{split}/{version}/

---

## 6. 데이터 저장 구조

### NAS 폴더 구조

    /mnt/nas/datasets/
      raw/
        {name}/
          {split}/
            {version}/
              images/
              annotation.json
      source/
        {name}/{split}/{version}/
          images/
          annotation.json
      processed/
        {name}/{split}/{version}/
          images/
          annotation.json
      fusion/
        {name}/{split}/{version}/
          images/
          annotation.json
      eda/
        {dataset_id}/          <- EDA 결과 이미지, JSON (Phase 2-a)

- `split` : `train` | `val` | `test` | `none`
- `version` : `v1.0.0` 형식, **split별 독립 increment**

### 버저닝 규칙

- split별로 version은 **완전 독립** 증가
- 동일 `(group_id, split)` 기준으로 신규 version 자동 increment
- 같은 pipeline 실행에서 train/val/test 생성 시 동일 버전 부여 **권장** (강제 아님)

예시 (정상적인 상태):

    coco_aug / train / v1.0.0   260219 생성
    coco_aug / val   / v1.0.0   260219 생성
    coco_aug / train / v1.0.1   260220 생성   <- val은 재가공 안 함
    coco_aug / val   / v1.0.1   260221 생성   <- train v1.0.1과 시점 달라도 무관

---

## 7. DB Schema

### dataset_groups

논리적 데이터셋 묶음. global 메타 정보 관리.

    id                   UUID        PK
    name                 VARCHAR     NOT NULL
    dataset_type         ENUM        RAW | SOURCE | PROCESSED | FUSION
    annotation_format    VARCHAR     COCO | YOLO | ATTR_JSON | CLS_FOLDER | CUSTOM | NONE
    task_types           JSONB       ["DETECTION","SEGMENTATION","ATTR_CLASSIFICATION",
                                      "ZERO_SHOT","CLASSIFICATION"]
    modality             VARCHAR     RGB | THERMAL | DEPTH | MULTISPECTRAL  (default: RGB)
    source_origin        VARCHAR     출처 URL or 설명
    description          TEXT        주의사항, 특징 등 global 설명
    extra                JSONB       기타 메타
    created_at           TIMESTAMP
    updated_at           TIMESTAMP

### datasets

split x version 단위 실제 파일. dataset_groups의 하위.

    id                   UUID        PK
    group_id             UUID        FK → dataset_groups
    split                ENUM        TRAIN | VAL | TEST | NONE
    version              VARCHAR     "v1.0.0"
    annotation_format    VARCHAR     group 기본값 상속, version별 override 가능
    storage_uri          VARCHAR     "processed/coco_aug/train/v1.0.0"
    status               ENUM        PENDING | PROCESSING | READY | ERROR
    image_count          INT         등록 or EDA 후 채워짐
    class_count          INT
    metadata             JSONB       EDA 결과, 클래스 분포 등
    created_at           TIMESTAMP
    updated_at           TIMESTAMP

    UNIQUE (group_id, split, version)

### dataset_lineage

datasets 단위 부모-자식 엣지.

    id                   UUID        PK
    parent_id            UUID        FK → datasets
    child_id             UUID        FK → datasets
    transform_config     JSONB       실행된 manipulator 구성 스냅샷
    created_at           TIMESTAMP

### manipulators

사전 등록된 가공 함수 목록. GUI 동적 폼 생성 기준.

    id                         UUID    PK
    name                       VARCHAR UNIQUE
    category                   ENUM    FILTER | AUGMENT | FORMAT_CONVERT |
                                       MERGE | SAMPLE | REMAP
    scope                      JSONB   ["PER_SOURCE"] | ["POST_MERGE"] |
                                       ["PER_SOURCE","POST_MERGE"]
    compatible_task_types      JSONB   ["DETECTION", ...]
    compatible_annotation_fmts JSONB   ["COCO", "YOLO", ...]
    output_annotation_fmt      VARCHAR format_convert류만 해당, 나머지 NULL
    params_schema              JSONB   GUI 동적 폼 생성용 파라미터 스펙
    description                TEXT
    status                     ENUM    ACTIVE | EXPERIMENTAL | DEPRECATED
    version                    VARCHAR
    created_at                 TIMESTAMP

### pipeline_executions

파이프라인 실행 이력.

    id                   UUID        PK
    output_dataset_id    UUID        FK → datasets
    config               JSONB       실행 시점 전체 PipelineConfig 스냅샷
    status               ENUM        PENDING | RUNNING | DONE | FAILED
    current_stage        VARCHAR     "annotation_processing" | "image_writing"
    processed_count      INT
    total_count          INT
    error_message        TEXT
    started_at           TIMESTAMP
    finished_at          TIMESTAMP
    created_at           TIMESTAMP

### 2차 대비 (빈 테이블로 Phase 0에서 미리 생성)

    objectives
      id, name, task_type, description

    recipes
      id, objective_id, model_type, base_config JSONB, description

    solutions
      id, name, recipe_id,
      train_dataset_id FK → datasets,
      val_dataset_id   FK → datasets,
      test_dataset_id  FK → datasets

    solution_versions
      id, solution_id, override_config JSONB,
      gpu_count, status, mlflow_run_id

    training_jobs
      id, solution_version_id,
      container_id, gpu_ids JSONB,
      started_at, finished_at,
      metrics JSONB

### Materialized View

    dataset_group_summary
      group_id, name, dataset_type, annotation_format,
      task_types, modality, description,
      splits: [
        { split, versions: [{ version, status, image_count, created_at }] }
      ]

    -- 등록 / 수정 / 삭제 / status 변경 시 REFRESH

---

## 8. 백엔드 프로젝트 구조

    app/
      api/v1/
        dataset_groups/     <- Phase 1
        datasets/           <- Phase 1
        lineage/            <- 라우터만 등록, Phase 2-b에서 구현
        pipelines/          <- Phase 2
        manipulators/       <- Phase 2
        eda/                <- 라우터만 등록, Phase 2-a에서 구현
        training/           <- 라우터만 등록, 2차에서 구현
      core/
        config.py           <- pydantic-settings, 환경변수 전체 관리
        database.py         <- async session
        storage.py          <- StorageClient 인터페이스 + LocalStorageClient
      models/               <- SQLAlchemy ORM
      schemas/              <- Pydantic
      services/             <- 비즈니스 로직
      tasks/                <- Celery tasks
      pipeline/
        models.py           <- DatasetMeta, ImageRecord, Annotation,
                               ImagePlan, ImageManipulationSpec, DatasetPlan
        manipulator.py      <- UnitManipulator 인터페이스
        executor.py         <- PipelineExecutor (annotation phase)
        image_executor.py   <- ImageExecutor (image 실체화 phase)
        planner.py          <- DatasetPlan 생성, rename 전략
        registry.py         <- manipulator 등록/조회
      manipulators/
        filters.py
        augmentations.py
        format_convert.py
        merge.py
        sampling.py

### 환경변수

    STORAGE_BACKEND=local
    LOCAL_STORAGE_BASE=/mnt/nas/datasets
    DATABASE_URL=postgresql+asyncpg://user:pass@postgres/mlplatform
    CELERY_BROKER_URL=db+postgresql://user:pass@postgres/mlplatform
    CELERY_RESULT_BACKEND=db+postgresql://user:pass@postgres/mlplatform

---

## 9. 핵심 설계 — Pipeline 실행 구조

### 파이프라인 2단계 실행 원칙

    Phase A — Annotation 처리 (이미지 미접촉, 경량)
      1. 소스 dataset의 annotation JSON만 로드
      2. per-source manipulator 체인 순차 적용 (transform_annotation 호출)
      3. MergeDatasets (복수 소스인 경우)
      4. post-merge manipulator 체인 적용
      5. 최종 DatasetMeta 확정

    ImagePlan 확정
      - 각 이미지별 src 경로, dst 경로, rename 규칙,
        적용할 ImageManipulationSpec 목록 결정
      - annotation 파일 선행 저장 (resume 가능 구조)

    Phase B — Image 실체화 (실제 I/O, 진행률 표시 기준)
      - is_copy_only → shutil.copy2()  (변환 없으면 빠른 경로)
      - 변환 있음   → load → spec 순서대로 적용 → save
      - 완료 시 datasets.status = READY, image_count 업데이트
      - EDA task 자동 체이닝 (Phase 2-a 구현 시 활성화, 미구현 시 skip)

### UnitManipulator 인터페이스

두 개의 함수로 구성:

    transform_annotation(input, params, context) → DatasetMeta
      - annotation 레벨 변환만 수행
      - 이미지 파일 I/O 절대 금지
      - 이미지 제거는 image_records에서 해당 항목 제거로 표현
      - PER_SOURCE : DatasetMeta 단건 입력
      - POST_MERGE : list[DatasetMeta] 입력 가능

    build_image_manipulation(image_record, params) → list[ImageManipulationSpec]
      - 이 manipulator가 해당 이미지에 적용할 변환 명세 반환
      - 변환 없으면 빈 list 반환 → Executor가 단순 copy 처리

### Annotation 내부 포맷 (포맷 독립)

    Annotation:
      annotation_type   BBOX | SEGMENTATION | LABEL | ATTRIBUTE
      category_id       int
      bbox              list | None
      segmentation      list | None
      label             str  | None
      attributes        dict | None    ex) {"head": "hat", "color": "red"}
      extra             dict           포맷별 추가 필드

### Celery 역할

    - 파이프라인 전체를 단일 long-running task로 감쌈
    - 각 Manipulator를 별도 task로 만들지 않음
    - 진행률은 pipeline_executions 테이블 직접 업데이트
    - 프론트는 3초 polling으로 조회

---

## 10. Manipulator 목록

### PER_SOURCE (가공 데이터 생성 시)

| name | 설명 | image 변환 |
|---|---|---|
| `rotate_180` | 180도 회전 | O |
| `change_compression` | JPEG quality 조정 | O |
| `mask_region_by_class` | 특정 class 영역 masking | O (EXPERIMENTAL) |
| `remap_class_name` | category_id 기준 class name 변경 | X |
| `filter_keep_by_class` | 특정 class 반드시 있는 이미지만 유지 (OR) | X |
| `filter_remove_by_class` | 특정 class 있는 이미지 제거 (OR) | X |
| `filter_invalid_class_name` | regex or blacklist 매칭 이미지 제거 | X |
| `sample_n_images` | N장 샘플 추출 (테스트용) | X |
| `format_convert_to_yolo` | COCO → YOLO | X |
| `format_convert_to_coco` | YOLO → COCO | X |
| `format_convert_visdrone_to_coco` | VisDrone → COCO | X |
| `format_convert_visdrone_to_yolo` | VisDrone → YOLO | X |

### POST_MERGE (fusion 데이터 생성 시)

| name | 설명 | image 변환 |
|---|---|---|
| `remap_class_name` | class name 변경 | X |
| `filter_keep_by_class` | 특정 class 있는 이미지만 유지 | X |
| `filter_remove_by_class` | 특정 class 있는 이미지 제거 | X |
| `filter_invalid_class_name` | regex or blacklist 이미지 제거 | X |
| `sample_n_images` | 데이터셋별 N장 샘플 | X |
| `merge_datasets` | 복수 소스 병합, 이미지명 중복 자동 해결 | X |
| `shuffle_image_ids` | 이미지 id 셔플 | X |
| `filter_final_classes` | 최종 annotation에 특정 class만 남기기 | X |

> `scope` 는 JSONB로 관리하며 `["PER_SOURCE", "POST_MERGE"]` 복수 허용.
> `mask_region_by_class` 는 `status: EXPERIMENTAL`, GUI 비활성 처리.

---

## 11. 데이터 등록 플로우

모든 데이터는 **GUI를 통해서만 등록**합니다. 수동 DB 조작 금지.

    1. 운영자가 NAS에 파일 업로드 + 압축 해제  (플랫폼 외부, 수동)

    2. GUI "데이터셋 등록" 진입

    3. 입력 항목:
         - dataset_type        RAW | SOURCE | PROCESSED | FUSION
         - annotation_format   COCO | YOLO | ATTR_JSON | ...
         - modality            RGB | THERMAL | ...
         - task_types          멀티셀렉트
         - NAS 경로            ex) raw/coco2017/train/v1.0.0
         - split / version
         - description, source_origin

    4. "경로 검증" 버튼
         → 백엔드가 NAS 경로 실재 여부, 파일 구조 확인

    5. "등록" 버튼
         → DB 메타데이터 저장
         → materialized view refresh
         → EDA task 자동 트리거 (Phase 2-a 구현 시)

---

## 12. Frontend 구조

### GNB

    - 데이터셋       <- 1차 완성
    - 모델 학습      <- "준비 중" 표시, 2차에서 활성화
    - 설정
        Manipulator 관리  (목록, params_schema 확인, status 변경)
        시스템 상태       (Celery worker, DB 연결)

### 데이터셋 목록 페이지

    - TanStack Table (서버사이드 정렬/필터/페이지네이션)
    - 필터 패널: dataset_type, task_types, annotation_format, modality, split, status
    - 정렬: 이름, 생성일, 이미지 수
    - group 단위 행, 펼치면 split x version 매트릭스
    - 각 행: status 배지, image_count, class_count, modality, task_types 태그
    - 버튼:
        파이프라인 실행  <- Phase 2 활성화
        샘플 보기        <- Phase 2-b 활성화 (현재 비활성 슬롯)
        EDA 보기         <- Phase 2-a 활성화 (현재 비활성 슬롯)
        Lineage 보기     <- Phase 2 활성화 (pipeline 실행 시 엣지 자동 생성)

### 데이터셋 상세 페이지 탭 구성

| 탭 | 구현 시점 | 내용 |
|---|---|---|
| 기본 정보 | Phase 1 | group 정보, split x version 목록, 경로, 포맷 |
| 샘플 보기 | Phase 2-b | 이미지 그리드, BBox/seg/attr 오버레이 (포맷별 분기) |
| EDA | Phase 2-a | 클래스 분포 bar, BBox scatter, 해상도 분포, 샘플 갤러리 |
| Lineage | Phase 2-b | React Flow DAG, split 필터 토글 |

### 파이프라인 설정 마법사 (Phase 2)

    Step 1: 출력 dataset 기본 정보
            - group 선택 or 신규 생성
            - split, version 자동 제안 (increment)
            - task_types, annotation_format, modality

    Step 2: 소스 dataset 선택 + per-source 가공 설정
            - task_types / annotation_format / modality 기준 자동 필터된 목록
            - 체크박스로 소스 선택
            - 소스별 manipulator 목록 (compatible 기준 자동 필터)
            - 체크박스 + params_schema 기반 동적 폼 렌더링

    Step 3: post-merge 가공 설정
            - post-merge manipulator 선택 + 파라미터
            - 소스들의 예상 이미지 수 합산 표시

---

## 13. 개발 Phase

### Phase 0 — 기반 인프라 & 프로젝트 뼈대 (1~2주) `필수`

    - docker-compose.yml 전체 서비스 정의
        postgresql (named volume), backend, frontend+nginx
        celery-worker (주석처리, Phase 2에서 활성화)
    - DB 스키마 전체 확정 + Alembic 초기 마이그레이션
        (2차 대비 빈 테이블 포함)
    - Materialized View 생성
    - StorageClient 인터페이스 + LocalStorageClient 구현
    - 환경변수 구조 확정
    - /health 엔드포인트 (DB 연결 상태 반환)

**완료 기준**: `docker compose up` 으로 전체 기동, `/health` 정상 응답

---

### Phase 1 — Dataset 등록 / 조회 GUI (2~3주) `필수`

    Backend:
      - dataset_groups CRUD
      - datasets CRUD (NAS 경로 검증, 버전 자동 increment)
      - 목록 조회 API (필터, 정렬, 서버사이드 페이지네이션)
      - materialized view refresh

    Frontend:
      - 데이터셋 목록 페이지 (TanStack Table, 필터/정렬)
      - 데이터셋 등록 폼
      - 데이터셋 상세 페이지 (기본 정보 탭)
      - 비활성 슬롯: 샘플 보기 탭, EDA 탭, Lineage 탭

**완료 기준**: 등록 → 목록 필터/정렬 조회 → 상세 확인 플로우 동작

---

### Phase 2 — Manipulator 시스템 & 파이프라인 실행 (3~4주) `필수`

    Backend:
      - pipeline/ 전체 구현
          models.py, manipulator.py, executor.py,
          image_executor.py, planner.py, registry.py
      - manipulators/ MVP 전체 구현
      - 파이프라인 실행 API (config 검증, lineage 엣지 생성, Celery 제출)
      - 파이프라인 상태 조회 API
      - Celery task: run_pipeline_task

    Frontend:
      - 파이프라인 설정 마법사 (3 step)
      - 실행 진행 화면 (진행률 polling)
      - 실행 이력 목록
      - Lineage 보기 버튼 활성화

**완료 기준**: GUI에서 소스 선택 + 가공 설정 → 실행 → 새 dataset 생성, Lineage 엣지 자동 기록

---

### Phase 2-a — EDA 자동화 (2주) `선택`

    Backend:
      - EDA Celery task (annotation 기반 통계 계산)
      - datasets.metadata JSONB에 결과 저장
      - NAS eda/{dataset_id}/ 에 샘플 이미지 저장
      - EDA 수동 재실행 API

    Frontend:
      - 상세 페이지 EDA 탭 슬롯 활성화
          ECharts: 클래스 분포 bar, BBox scatter, 해상도 분포
          샘플 이미지 갤러리
      - 목록 행 인라인 EDA 요약 활성화

---

### Phase 2-b — 샘플 보기 & Lineage 시각화 (2주) `선택`

    Backend:
      - lineage 조회 API (재귀 CTE, upstream/downstream 전체)
      - 샘플 이미지 조회 API (랜덤 N장, 클래스 필터)

    Frontend:
      - 상세 페이지 샘플 보기 탭 슬롯 활성화
          이미지 그리드, 클릭 시 오버레이
          annotation_format에 따라 BBOX / seg / attr 렌더링 분기
      - 상세 페이지 Lineage 탭 슬롯 활성화
          React Flow DAG
          노드 색상: dataset_type별 구분
          엣지 레이블: manipulator 요약
          split 필터 토글

---

### Phase 3 — 2차 수용 준비 & UX 정리 (1~2주) `필수`

    Backend:
      - TrainingExecutor 추상 인터페이스 (골격만)
          submit_job / get_job_status / cancel_job
      - GPUResourceManager 추상 인터페이스 (골격만)
          get_available_gpus / reserve_gpus / release_gpus
      - 알림 Celery signal 골격, SMTP 환경변수 구조

    Frontend:
      - GNB 확정 (모델 학습 메뉴 "준비 중")
      - Manipulator 관리 페이지
      - 시스템 상태 페이지
      - 전체 UX 정리
          빈 상태 안내, 에러 토스트, 로딩 상태 일관성

---

### 전체 일정

| Phase | 기간 | 구분 |
|---|---|---|
| Phase 0 | 1~2주 | 필수 |
| Phase 1 | 2~3주 | 필수 |
| Phase 2 | 3~4주 | 필수 |
| Phase 2-a | 2주 | 선택 |
| Phase 2-b | 2주 | 선택 |
| Phase 3 | 1~2주 | 필수 |
| **핵심만** | **7~11주** | |
| **전체** | **11~15주** | |

---

## 14. 확장 포인트

코딩 시 아래 인터페이스는 반드시 유지해야 합니다.

### StorageClient

    1차: LocalStorageClient  (NAS 직접 접근)
    3차: S3StorageClient     (구현체 교체만으로 전환, 비즈니스 로직 수정 없음)

### TrainingExecutor (Phase 3 골격 작성)

    2차: DockerTrainingExecutor      (단일 서버 GPU)
    3차: KubernetesTrainingExecutor  (K8S Pod 기반)

### GPUResourceManager (Phase 3 골격 작성)

    2차: 단일 서버 nvidia-smi 기반
    3차: K8S 리소스 API 기반 클러스터

### UnitManipulator

    새 manipulator 추가 = 함수 구현 + DB INSERT 만으로 완결
    기존 코드 수정 없음

### DB 스키마

    2차 대비 테이블 Phase 0에서 미리 생성 완료
    training/ API 라우터 Phase 0에서 등록, 2차에서 구현

### Annotation 내부 포맷

    BBOX / SEGMENTATION / LABEL / ATTRIBUTE 포맷 독립 구조
    Detection 외 task 추가 시 Manipulator 구현만 추가
