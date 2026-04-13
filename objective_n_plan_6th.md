# 데이터 관리 & 학습 자동화 플랫폼 — 6차 설계서

> **작업지시서 v6.0** | Phase 2 마무리 / Step 2(학습 자동화) 진입 준비 기준
> 기준일: 2026-04-13
> 이전 설계서: `docs_history/objective_n_plan_5th.md` (v5.2까지의 변경 누적)
> 통합 핸드오프: `docs_for_claude/013-consolidated-handoff.md`

5차 설계서의 v5.1 ~ v5.2에서 누적된 변경을 전부 "현행 기준"으로 재정리한 버전. 4차→5차 diff / v5 패치 노트는 삭제하고, **현 시점의 설계와 앞으로 할 일**만 남겼다.

---

## 1. 로드맵 위치

| Step | 범위 | 상태 |
|------|------|------|
| **Step 1** | 데이터셋 관리 (Phase 0~3) | Phase 0/1/2-a/2-b 완료, Phase 2 마무리 단계, Phase 3 예정 |
| **Step 2** | 학습 자동화 (단일/다중 GPU) | 진입 준비 (TrainingExecutor/GPUResourceManager 골격만 예정) |
| **Step 3** | K8S 클러스터화, GPU 스케줄링 | 미착수 |
| **Step 4** | Label Studio, Synthetic Data, MLOps (Auto Labeling, Offline Testing, Auto Deploy 등) | 미착수 |
| **Step 5** | Generative Model 도입 MLOps | 미착수 |

Step 1 세부 Phase:

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 0 | 인프라, DB 스키마, /health | 완료 |
| Phase 1 | 데이터셋 등록/관리 GUI | 완료 |
| Phase 2 | Manipulator + Celery 파이프라인 + GUI 에디터 | **진행 중** (핵심 완료, 확장/고도화 잔여) |
| Phase 2-a | EDA 자동화 | 완료 |
| Phase 2-b | 샘플 뷰어 + Lineage 시각화 | 완료 |
| Phase 3 | 2차 수용 준비 & UX 정리 (Training/GPU 인터페이스 골격, 알림 signal, Manipulator 관리/시스템 상태 페이지, UX 일관성) | 예정 — Step 2 진입 전 필수 |

---

## 2. 현재 구현 상태 (2026-04-13 기준 baseline)

### 2-1. 백엔드

- **FastAPI + async SQLAlchemy(asyncpg) + Alembic**. 모든 API `/api/v1` 접두사.
- **Celery worker** — sync 세션(`SyncSessionLocal`, psycopg2) 사용. 파이프라인 실행 + RAW 등록 모두 비동기.
- **Broker/Backend = PostgreSQL** (Redis 미사용).
- **`lib/` 순수 로직 패키지** (DB/FastAPI 무의존) + `app/` 래퍼. `lib/ → app/` import 절대 금지.

### 2-2. 데이터 모델 (핵심 도메인)

- **DatasetGroup** — 논리적 묶음. `dataset_type` (RAW/SOURCE/PROCESSED/FUSION), `annotation_format`, `task_types` (JSONB), `deleted_at` (soft delete).
- **Dataset** — 그룹 하위 split × version. `(group_id, split, version)` 유니크. `metadata_` JSONB에 `class_info` 저장 (`validation_alias="metadata_"`, 출력 키는 `metadata`).
- **Manipulator** — `params_schema` (JSONB)로 GUI 동적 폼 생성.
- **DatasetLineage** — 파이프라인 변환 이력 엣지 (parent→child, transform_config 스냅샷).
- **PipelineExecution** — 실행 이력 + Celery 태스크 추적.

### 2-3. 파이프라인 (통일포맷 기반)

**내부 데이터 모델은 포맷 무관(format-agnostic) 통일포맷**:
- `Annotation.category_name: str` (정수 ID 없음)
- `DatasetMeta.categories: list[str]` (이름 목록)
- 포맷별 ID는 **IO 경계(파서/라이터)에서만** 처리

```
[디스크] ──parse──▶ [통일포맷 DatasetMeta] ──write──▶ [디스크]
 COCO/YOLO          category_name 기반                COCO/YOLO
```

- **COCO writer**: 표준 80클래스 `NAME_TO_COCO_ID` (1~90 비순차) + 커스텀은 91+
- **YOLO writer**: 알파벳순 정렬 → 0-based index

### 2-4. MANIPULATOR_REGISTRY (12종)

| 카테고리 | 구현 |
|----------|------|
| FORMAT_CONVERT (4종, 모두 no-op) | `format_convert_to_coco`, `format_convert_to_yolo`, `format_convert_visdrone_to_coco`, `format_convert_visdrone_to_yolo` |
| MERGE | `merge_datasets` (name 기반 union) |
| ANNOTATION_FILTER | `filter_remain_selected_class_names_only_in_annotation` |
| IMAGE_FILTER | `filter_keep_images_containing_class_name`, `filter_remove_images_containing_class_name` |
| REMAP | `remap_class_name` |
| AUGMENT (이미지 변환) | `rotate_image` (90/180/270°), `mask_region_by_class` |
| SAMPLE | `sample_n_images` (seed 재현) |

**Phase B 이미지 변환 파이프라인 연결 완료** — manipulator가 `record.extra["image_manipulation_specs"]`에 누적 → `ImageMaterializer._transform_and_save()`에서 PIL 체인 적용 → 한 번만 저장. EXIF/포맷 보존, 그레이스케일 자동 RGB 변환.

**DB seed만 존재, 코드 미구현 (GUI는 클릭 시 경고)**: `change_compression` (AUGMENT), `shuffle_image_ids` (SAMPLE).

### 2-5. GUI 파이프라인 에디터

- **React Flow + Zustand (`nodeDataMap`가 단일 소스)**
- **4종 커스텀 노드**: DataLoadNode / OperatorNode / MergeNode / SaveNode
- **Merge 외 노드는 입력 엣지 1개로 강제** (onConnect 차단)
- **JSON 불러오기** — PipelineConfig JSON → DAG 복원 (topological auto-layout)
- **실행 상세 Drawer** (공유 컴포넌트) — 파이프라인 이력 + 데이터셋 상세에서 동일 컴포넌트 재사용, Config JSON 확인/복사

### 2-6. 비동기 실행 체계

**RAW 등록 & 파이프라인 실행 모두 Celery 비동기**:
- API 즉시 **202 응답** → 클라이언트는 안내 모달만 표시
- 상태는 데이터셋 목록 / 실행 이력 Drawer에서 확인
- **재시도 없음** (`max_retries=0`), 실패 시 부분 디렉토리 `shutil.rmtree` 정리
- **큐**: 파이프라인 `"pipeline"` (prefetch=1, soft 24h / hard 25h), 등록 `"default"`

### 2-7. 버전 정책

`{major}.{minor}` 형식 (3단계 semver 폐기):

| 구분 | 증가 조건 |
|------|-----------|
| **major** | 사용자가 명시적으로 파이프라인 실행 또는 RAW 수동 등록 |
| **minor** | automation 자동 실행 (§6 미구현) |

- 삭제된 버전도 `_next_version()`은 전체 조회로 연속성 보존 (soft delete)
- 파이프라인 출력 그룹의 `task_types`는 소스 그룹들의 **교집합**으로 자동 부여

---

## 3. RAW 데이터셋 등록 플로우

사전 조건: 사용자가 등록할 데이터를 `LOCAL_UPLOAD_BASE` 경로에 복사.

**3단계 위자드**:
1. 태스크 타입 선택 (다중)
2. 파일 선택 — 서버 파일 브라우저(`GET /api/v1/filebrowser/list`)로 이미지 디렉토리 1개 + 어노테이션 파일 1개 이상
3. 어노테이션 포맷 + 그룹명 입력

**등록 실행 (비동기)**:

```
[프론트] POST /api/v1/dataset-groups/{id}/register
[백엔드 API]
    → DatasetGroup 생성 or 기존 그룹 추가
    → Dataset(status=PROCESSING) 즉시 생성
    → Celery register_dataset dispatch
    → 202 { dataset_id, task_id }
[Celery Worker]
    → 이미지/어노테이션/메타 파일 복사 (copy, move 아님)
    → 클래스 정보 자동 추출 (best-effort — 실패해도 등록은 진행)
    → Dataset READY or ERROR
```

**등록 원칙 (절대 규칙)**:
- **RAW만 사람이 직접 등록** 가능
- SOURCE / PROCESSED / FUSION은 **파이프라인을 통해서만 생성** — 사람의 직접 파일 수정 및 DB 조작 금지

---

## 4. 파이프라인 실행 상세

### 4-1. 실행 흐름

```
[사용자] GUI 노드 에디터 → graphToPipelineConfig() → PipelineConfig
    ↓ 클라이언트 사전 검증 (사이클/SaveNode 유무/연결 완전성)
[검증] POST /api/v1/pipelines/validate → 정적 + DB 검증
    ↓ is_valid == true
[실행] POST /api/v1/pipelines/execute → 202 { execution_id }
    ↓ ExecutionSubmittedModal — "데이터셋 목록에서 확인"
[Celery Worker]
    → PipelineExecution(RUNNING) + Dataset(PROCESSING)
    → PipelineDagExecutor.run(config, target_version)
      · Phase A: Annotation DAG 처리 (topological sort, multi-input 지원)
      · Phase B: Image 실체화 (누락 이미지 스킵, 변환 체인 적용)
      · processing.log 작성
    → 성공: Dataset(READY) + PipelineExecution(DONE) + Lineage 엣지 생성
    → 실패: Dataset(ERROR) + PipelineExecution(FAILED) + error_message (2000자 truncate)
```

### 4-2. PipelineConfig 스키마

```python
class PipelineConfig(BaseModel):
    name: str
    description: str | None
    output: OutputConfig
    tasks: dict[str, TaskConfig]

class TaskConfig(BaseModel):
    operator: str                          # MANIPULATOR_REGISTRY 키
    inputs: list[str]                      # "source:<dataset_id>" | 태스크명
    params: dict[str, Any]

class OutputConfig(BaseModel):
    dataset_type: str = "SOURCE"           # SOURCE | PROCESSED | FUSION
    annotation_format: str = Field(...)    # COCO | YOLO (필수)
    split: str = "NONE"
```

### 4-3. 검증 코드 체계

**정적 검증** (`lib/pipeline/pipeline_validator.py`, DB 무관):

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `INVALID_DATASET_TYPE` | ERROR | dataset_type ∉ {SOURCE, PROCESSED, FUSION} |
| `RAW_NOT_ALLOWED_AS_OUTPUT` | ERROR | RAW 출력 불가 |
| `INVALID_SPLIT` | ERROR | split ∉ {TRAIN, VAL, TEST, NONE} |
| `INVALID_ANNOTATION_FORMAT` | ERROR | format ∉ {COCO, YOLO} |
| `UNKNOWN_OPERATOR` | ERROR | MANIPULATOR_REGISTRY 미등록 |
| `MERGE_MIN_INPUTS` | ERROR | merge_datasets 입력 < 2 |
| `MULTI_INPUT_WITHOUT_MERGE` | WARNING | 비-merge operator에 다중 입력 |

**DB 검증** (`app/services/pipeline_service.py`):

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `SOURCE_DATASET_NOT_FOUND` | ERROR | DB에 없는 dataset_id |
| `SOURCE_DATASET_GROUP_DELETED` | ERROR | 소프트 삭제된 그룹 |
| `SOURCE_DATASET_NOT_READY` | ERROR | READY가 아닌 상태 |
| `SOURCE_DATASET_NO_ANNOTATIONS` | WARNING | annotation 미등록 |

### 4-4. 상태 전이

- **PipelineExecution**: `PENDING → RUNNING → DONE | FAILED`
- **Dataset**: `PENDING → PROCESSING → READY | ERROR`
- 각 전이마다 즉시 commit (polling/목록 가시성 확보)

### 4-5. 출력 디렉토리 구조

**COCO**:
```
source/output_name/train/1.0/
├── processing.log
├── images/ *.jpg
└── annotations/instances.json
```

**YOLO**:
```
source/output_name/train/1.0/
├── data.yaml             ← 데이터셋 루트 (path/train/val 키 없음)
├── processing.log
├── images/ *.jpg
└── annotations/*.txt     ← 순수 라벨만 (classes.txt 없음)
```

---

## 5. GUI 파이프라인 에디터 설계

### 5-1. 4종 노드

| 노드 | 입력 | 출력 | 역할 |
|------|------|------|------|
| **DataLoadNode** | 0 | 1 | 3단계 캐스케이드(그룹→Split→버전) → `source:<datasetId>` |
| **OperatorNode** | 1 (최대) | 1 | 범용 operator, params 실시간 반영 |
| **MergeNode** | N (동적) | 1 | 연결 엣지 수에 따라 핸들 증가 |
| **SaveNode** | 1 (최대) | 0 | name, dataset_type, split, format 인라인 폼 |

**입력 엣지 수 제한**: `onConnect`가 대상 노드 타입 확인 → Merge 외 노드에 기존 엣지가 있으면 `Modal.warning` + 차단.

### 5-2. 노드 팔레트 카테고리

```typescript
const CATEGORY_META = {
  FORMAT_CONVERT:    { label: '포맷 변환',       color: '#1677ff' },  // 비활성, "자동 처리" 안내
  ANNOTATION_FILTER: { label: 'Annotation 필터', color: '#eb2f96' },
  IMAGE_FILTER:      { label: 'Image 필터',      color: '#cf1322' },
  SAMPLE:            { label: '샘플링',           color: '#722ed1' },
  REMAP:             { label: '리매핑',           color: '#fa8c16' },
  AUGMENT:           { label: 'Image 변형',       color: '#13c2c2' },
  MERGE:             { label: '병합',             color: '#9254de' },
}
```

- 공통 스타일은 `frontend/src/components/pipeline/nodeStyles.ts`에서 관리
- NodePalette description의 괄호 `(도움말)`은 Tooltip으로 자동 분리

### 5-3. React Flow + Zustand 동기화 규칙 (절대 준수)

```tsx
// (1) 노드 컴포넌트는 반드시 store 직접 구독 (node.data prop 금지)
const nodeData = usePipelineEditorStore((s) => s.nodeDataMap[id] ?? null)

// (2) 폼 영역엔 className만 (onMouseDown stopPropagation 금지)
<div className="nopan nodrag">
  <Select ... />
</div>

// (3) useEffect dependency엔 객체 참조 말고 실질 값
useEffect(() => { ... }, [statusValue, processedCount])
```

### 5-4. 페이지 구조

- `/pipelines` — 실행 이력 (AppLayout, 사이드바), 태스크 타입 선택 모달 (DETECTION만 활성)
- `/pipelines/editor?taskType=DETECTION` — 전체화면 에디터 (AppLayout 밖)

---

## 6. Automation 시나리오 (미구현, v6 주요 TODO)

원천 SOURCE 버전이 올라가면 downstream 파이프라인이 **사전 등록된 config로 자동 재실행**되며, 출력 데이터셋의 **minor 버전이 증가**.

```
[SOURCE A 1.0 → 2.0]
        ↓ (원천 버전업 감지)
[사전 등록된 downstream 파이프라인] 자동 실행 (is_automation=True)
        ↓
[출력 Dataset] 1.0 → 1.1 (minor 증가)
        ↓ 이 출력이 또 다른 파이프라인의 입력이면 연쇄
```

**구현 필요 요소**:
- 파이프라인 **템플릿 저장** 모델 (현재는 1회성 execution만 존재)
- 원천 → downstream 의존 그래프 (DatasetLineage 역방향 탐색)
- `is_automation` 플래그 → `_next_version()`이 minor 증가로 분기
- 트리거 지점 (등록/파이프라인 완료 시 downstream 탐색 & dispatch)

---

## 7. TODO 전체 목록 (Step / Phase 별)

### 7-1. Step 1 Phase 2 — 액션 아이템 + 잔여 백로그

앞쪽 5개는 v5.2/v6에서 신규로 잡은 최우선 액션, 그 아래는 이전 설계서부터 이월된 잔여 / 백로그 항목.

| 순위 | 영역 | 항목 | 설명 |
|------|------|------|------|
| 1 | 액션 | **노드 추가 SDK화** | DataLoad/Operator/Merge/Save + Manipulator 인터페이스 일원화. 신규 노드 추가를 한 파일 수정으로 완결시키는 구조로 전환 |
| 1-a | 액션 | **노드 추가 가이드 문서** | SDK화 완료 후 "새 노드 만드는 법" md (`docs_for_claude/` 또는 developer docs) |
| 2 | 액션 | **Classification 데이터 입력** | 현재 Detection only. Classification 전용 등록/파서/manipulator/뷰어 설계 및 구현 |
| 3 | 액션 | **Automation 실구현** | §6 시나리오. 파이프라인 템플릿, downstream 탐색, `is_automation`→minor 증가 |
| 4 | 액션 | **버전 정책 점검** | `{major}.{minor}` 운영 검증. 수동/자동 동시 발생 충돌 처리 |
| — | Manipulator | 미구현 2종 | `change_compression`, `shuffle_image_ids` |
| — | Manipulator | 신규 후보 | IoU 기반 겹치는 annotation 제거, IoU 기반 마스킹 |
| — | Manipulator UX | `sample_n_images` DAG 내 위치 | 필터 전/후, merge 전/후 배치에 따른 결과 차이 — 안내 또는 검증 경고 |
| — | GUI | 검증 결과 노드별 하이라이트 | validate `issue_field` → 개별 노드 매핑 |
| — | GUI | MergeNode params_schema 폼 | 확장 대비, 보류 가능 |
| — | 인프라 / 품질 | 네이밍 점검 | `_write_data_yaml` 등 general 함수명 리네이밍 |
| — | 인프라 / 품질 | 뷰어/EDA 전수 검증 | 통일포맷 `schema_version=2` 캐시 재생성 확인 |
| — | 인프라 / 품질 | 테스트 자동화 | Integration / Regression / E2E (Celery 안정화 후) |
| — | 인프라 / 품질 | DB seed 정합성 재확인 | 코드 구현 12종과 대조 |
| — | Step 2 연계 | YOLO `data.yaml` path 주입 | `path/train/val` 키 주입 (학습 시 경로 필요) |

### 7-2. Step 1 Phase 3 — 2차 수용 준비 & UX 정리 (예정)

1차 설계서 §13 기준. Step 2 진입 전 필수 Phase.

| 영역 | 항목 |
|------|------|
| 백엔드 골격 | `TrainingExecutor` 추상 인터페이스 (submit_job / get_job_status / cancel_job) |
| 백엔드 골격 | `GPUResourceManager` 추상 인터페이스 (get_available_gpus / reserve_gpus / release_gpus) |
| 백엔드 골격 | 알림 Celery signal 골격 + SMTP 환경변수 구조 |
| 프론트엔드 | GNB 확정 (모델 학습 메뉴 "준비 중" 표시) |
| 프론트엔드 | Manipulator 관리 페이지 |
| 프론트엔드 | 시스템 상태 페이지 |
| 프론트엔드 | 전체 UX 정리 (빈 상태 안내, 에러 토스트, 로딩 상태 일관성) |

### 7-3. Step 2 — 학습 자동화 (단일/다중 GPU 서버)

| 항목 | 설명 |
|------|------|
| Detection / Attribute Classification 모델 학습 | Docker 컨테이너 기반, config 동적 주입 (Step 2 진입점) |
| `DockerTrainingExecutor` 구현 | TrainingExecutor 인터페이스의 1차 구현체 (단일 서버 GPU) |
| GPUResourceManager — 단일 서버 | `nvidia-smi` 기반 자원 관리 |
| MLflow 실험 추적 통합 | 학습 실험의 파라미터/메트릭/아티팩트 추적 |
| Prometheus / Grafana / DCGM Exporter | 메트릭 수집 + 대시보드 + GPU 메트릭 |
| 알림 | SMTP / SendGrid 연동 (학습 완료/실패) |

### 7-4. Step 3 — K8S 클러스터화 + GPU 학습 스케줄링

| 항목 | 설명 |
|------|------|
| `S3StorageClient` | LocalStorageClient 대체 (구현체 교체만) |
| `KubernetesTrainingExecutor` | Pod 기반 학습 실행 |
| GPUResourceManager — K8S | K8S 리소스 API 기반 클러스터 자원 관리 |
| Helm 패키징 | K8S 배포 표준화 |
| Argo Workflows 또는 Kubeflow Pipelines | ML 파이프라인 오케스트레이션 |
| Volcano | GPU 스케줄러 |
| KEDA | 오토스케일링 |
| MinIO / 클라우드 S3 | 오브젝트 스토리지 |

### 7-5. Step 4 — Label Studio + Synthetic Data + MLOps

| 항목 | 설명 |
|------|------|
| Label Studio 연결 | 외부 라벨링 도구 통합 |
| AI 생성 Synthetic Train Data | 합성 학습 데이터 생성 파이프라인 |
| Auto Labeling | 모델 기반 자동 라벨링 |
| Offline Testing | 배포 전 오프라인 평가 |
| Auto Deploy | 학습 완료 → 배포 자동화 |
| 학습 스케줄링 자동화 | 주기적/트리거 기반 재학습 |
| 데이터 자동 수집 파이프라인 | 외부 소스 → 플랫폼 자동 취합 |

### 7-6. Step 5 — Generative Model MLOps

| 항목 | 설명 |
|------|------|
| Generative Model 도입 MLOps 일체 | 생성 모델 학습/배포/평가/관리 전반 |

---

## 8. 핵심 파일 맵

### 8-1. lib/ (순수 로직, DB 무의존)

| 파일 | 역할 |
|------|------|
| `lib/pipeline/config.py` | PipelineConfig / TaskConfig / OutputConfig, topological_order |
| `lib/pipeline/dag_executor.py` | PipelineDagExecutor — DAG 실행 + processing.log |
| `lib/pipeline/image_materializer.py` | ImageMaterializer — 이미지 복사/변환 + 누락 스킵 (MaterializeResult) |
| `lib/pipeline/pipeline_data_models.py` | DatasetMeta, ImageRecord, Annotation (통일포맷) |
| `lib/pipeline/manipulator_base.py` | UnitManipulator ABC + REQUIRED_PARAMS + accepts_multi_input |
| `lib/pipeline/pipeline_validator.py` | 정적 검증 + 검증 결과 모델 |
| `lib/pipeline/storage_protocol.py` | StorageProtocol (typing.Protocol) |
| `lib/pipeline/io/coco_io.py` | COCO JSON 파서/라이터 |
| `lib/pipeline/io/yolo_io.py` | YOLO 디렉토리 파서/라이터 + data.yaml 생성 |
| `lib/pipeline/io/coco_yolo_class_mapping.py` | COCO 80클래스 매핑 테이블 |
| `lib/manipulators/__init__.py` | MANIPULATOR_REGISTRY (12종) |
| `lib/manipulators/*.py` | 개별 구현 |

### 8-2. app/ (FastAPI + DB + Celery)

| 파일 | 역할 |
|------|------|
| `app/api/v1/pipelines/router.py` | POST /validate, POST /execute, GET /status, GET / |
| `app/api/v1/dataset_groups/router.py` | 데이터셋 등록 (202 즉시 응답) |
| `app/api/v1/datasets/router.py` | CRUD + PATCH + POST /validate |
| `app/api/v1/manipulators/router.py` | GET /manipulators (GUI 팔레트용) |
| `app/services/pipeline_service.py` | 검증 + 제출 + 상태 조회 + task_types 교집합 |
| `app/services/dataset_service.py` | CRUD + Celery 등록 dispatch + 소프트 삭제 |
| `app/tasks/pipeline_tasks.py` | Celery run_pipeline (skipped_image_count 포함) |
| `app/tasks/register_tasks.py` | Celery register_dataset (파일 복사 + 클래스 추출) |
| `app/tasks/celery_app.py` | Celery 앱 설정 |
| `app/core/storage.py` | LocalStorageClient, copy_annotation_meta_file → 데이터셋 루트 |
| `app/core/database.py` | async_engine + sync_engine 이중 구조 |
| `app/models/all_models.py` | 전체 ORM (pipeline_execution_id @property 포함) |

### 8-3. frontend/

| 파일 | 역할 |
|------|------|
| `types/pipeline.ts` | 에디터 TypeScript 타입 |
| `api/pipeline.ts` | 파이프라인/manipulator/datasets API |
| `stores/pipelineEditorStore.ts` | Zustand 에디터 상태 (nodeDataMap 중심) |
| `utils/pipelineConverter.ts` | graph↔PipelineConfig 변환 + 클라이언트 검증 + JSON→DAG 복원 |
| `pages/PipelineEditorPage.tsx` | 전체화면 에디터 (onConnect 입력 수 제한 포함) |
| `pages/PipelineHistoryPage.tsx` | 실행 이력 + 태스크 타입 선택 모달 |
| `components/pipeline/nodes/*` | DataLoadNode / OperatorNode / MergeNode / SaveNode |
| `components/pipeline/nodeStyles.ts` | 카테고리/manipulator 스타일 중앙 관리 |
| `components/pipeline/NodePalette.tsx` | 좌측 팔레트 (Tooltip 분리, FORMAT_CONVERT/미구현 비활성) |
| `components/pipeline/DynamicParamForm.tsx` | params_schema 기반 동적 폼 (7 타입) |
| `components/pipeline/ExecutionDetailDrawer.tsx` | 공유 실행 상세 Drawer (이력 + 데이터셋 상세 재사용) |
| `components/pipeline/ExecutionStatusModal.tsx` | ExecutionSubmittedModal (polling 없음) |

---

## 9. 작업 시 준수 원칙

### 9-1. 아키텍처
- **`lib/` → `app/` import 금지**
- **DB 세션 이중 구조 혼용 금지** (async = FastAPI, sync = Celery)
- **Celery hot reload 없음** — 코드 변경 시 `docker restart mlplatform-celery`
- **소프트 삭제 필터 누락 금지** — 단 `_next_version()`은 예외

### 9-2. 네이밍 / 스타일
- 한 글자·한 단어 함수/변수명 금지. 풀네임 + 한글 주석 필수
- Manipulator 네이밍 패턴: `{동작}_{대상}_{조건}`

### 9-3. GUI
- 노드 컴포넌트는 store 직접 구독 (node.data prop 금지)
- 폼 영역은 `className="nopan nodrag"` (onMouseDown stopPropagation 금지)
- useEffect dependency는 실질 값만

### 9-4. 통일포맷
- 파이프라인 내부는 `category_name: str` 기반. 포맷별 ID는 IO 경계에서만 처리
- `sample_index.json`은 `schema_version=2`. v1 감지 시 자동 재생성

### 9-5. 비동기
- 재시도 없음(`max_retries=0`)
- 실패 시 부분 생성 디렉토리는 `shutil.rmtree`로 정리
