# 데이터 관리 & 학습 자동화 플랫폼 — 5차 설계서

> **작업지시서 v5.0** | Phase 2 기준 (비동기 등록 + 필터 manipulator + UI 개선)
> `objective_n_plan_4th.md`의 비동기 등록 전환 + filter_final_classes + UI 개선 반영
> 이전 설계서: `docs_history/objective_n_plan_4th.md`

---

## 1. 4차 대비 변경/추가된 설계

### 1-1. 데이터셋 등록 Celery 비동기 전환

4차까지 동기 방식이었던 RAW 데이터셋 등록을 Celery 비동기 태스크로 전환. 대용량 데이터셋 등록 시 API 타임아웃 문제를 근본적으로 해결.

| 4차 (이전) | 5차 (현행) |
|---|---|
| API가 파일 복사 완료까지 동기 대기 | API 즉시 202 응답, Celery worker가 파일 복사 |
| 프론트: fire-and-forget + 타임아웃 환경변수 | 프론트: 정상 await (즉시 응답), 안내 모달 |
| 타임아웃 위험 (대용량 데이터셋) | 타임아웃 없음 (비동기 처리) |

**변경된 등록 흐름:**

```
[사용자] → 등록 API 호출
    → Dataset(status=PROCESSING) 즉시 DB 생성
    → Celery 태스크 dispatch (register_dataset)
    → API 즉시 202 응답
    ↓
[Celery Worker]
    → 파일 복사 (이미지 + 어노테이션 + 메타 파일)
    → 클래스 정보 자동 추출 (best-effort)
    → 성공: Dataset READY
    → 실패: Dataset ERROR + 부분 디렉토리 정리
```

**핵심 구현:**
- `backend/app/tasks/register_tasks.py` — 동기 DB 세션(`SyncSessionLocal`) 사용
- 에러 발생 시 부분 생성 디렉토리를 `shutil.rmtree`로 정리
- 클래스 정보 추출 실패는 등록을 중단하지 않음 (best-effort)

### 1-2. ExecutionStatusModal → ExecutionSubmittedModal

파이프라인 실행 후 polling 모달을 제거하고, 단순 확인 모달로 변경.

| 4차 (이전) | 5차 (현행) |
|---|---|
| ExecutionStatusModal — 2초 polling | ExecutionSubmittedModal — 확인 모달만 |
| store에 executionStatus/setExecutionStatus | 제거됨 (executionId만 유지) |
| 모달에서 실행 완료까지 대기 | "데이터셋 목록에서 확인하세요" 안내 |

실행 상태는 데이터셋 목록 페이지의 status 컬럼에서 확인한다.

### 1-3. filter_final_classes manipulator 구현

MANIPULATOR_REGISTRY 4종째. 지정 class 이름의 annotation만 유지하고 나머지를 제거.

**핵심 특성:**
- annotation 레벨만 처리 — 이미지 파일은 건드리지 않음
- annotation이 전부 제거된 이미지도 `image_records`에 유지 (빈 이미지로 남김)
- `keep_class_names`는 줄바꿈 구분 문자열 (GUI textarea)
- categories에 없는 class 이름은 경고 로그 후 무시

### 1-4. 필터 카테고리 분리 — FILTER / IMAGE_FILTER

기존 FILTER 카테고리를 동작 범위에 따라 두 카테고리로 분리.

| 카테고리 | GUI 라벨 | 동작 | 색상 | 해당 manipulator |
|----------|----------|------|------|------------------|
| **FILTER** | "Annotation 필터" | annotation만 제거, 이미지 유지 | `#eb2f96` | `filter_final_classes` |
| **IMAGE_FILTER** | "Image 필터" | 이미지 자체를 유지/제거 | `#f5222d` | `filter_keep_by_class`, `filter_remove_by_class`, `filter_invalid_class_name` |

### 1-5. NodePalette / OperatorNode UI 개선

**NodePalette:**
- description의 괄호 부분을 Tooltip으로 분리 — 버튼은 짧고 깔끔, hover 시 상세 설명
- 노드 라벨도 괄호 제거한 짧은 이름 사용

**OperatorNode:**
- store 직접 구독으로 변경 → params 변경이 노드에 실시간 반영 (이전에는 갱신 안 됨)
- textarea params는 줄바꿈→쉼표 축약 표시 (예: "person, car, truck")

---

## 2. 현재 구현 상태 (2026-04-07)

### 완료된 것

| 항목 | 설명 |
|---|---|
| 데이터 모델 | `DatasetMeta`, `Annotation`, `ImageRecord`, `ImagePlan`, `DatasetPlan` |
| UnitManipulator ABC | `transform_annotation()` + `build_image_manipulation()` |
| 포맷 변환 manipulator | `format_convert_to_coco`, `format_convert_to_yolo` |
| merge_datasets manipulator | 복수 소스 병합, 파일명 충돌 해결, **COCO ID 보존** |
| **filter_final_classes** | 지정 class annotation만 유지, 이미지 유지 |
| COCO<->YOLO 80클래스 매핑 | 표준 매핑 + 미지 클래스 순차 할당 |
| IO 계층 | `parse_coco_json`, `write_coco_json`, `parse_yolo_dir`, `write_yolo_dir` |
| DAG 실행 엔진 | `PipelineDagExecutor.run()` — topological sort + multi-input 지원 |
| 이미지 실체화 | `ImageMaterializer` — 복사 지원, **누락 이미지 스킵**, 변환 stub |
| Celery 비동기 실행 | 파이프라인: `run_pipeline`, **등록: `register_dataset`** |
| 실행 API | `POST /execute`(202), `GET /{id}/status`, `GET /` |
| 검증 API | `POST /validate` — 정적 + DB 검증 |
| 코드 분리 | `lib/` 패키지, `app/` re-export 래퍼 |
| GUI 파이프라인 에디터 | React Flow 노드 에디터 4종 노드, Zustand store |
| Graph->PipelineConfig 변환 | `graphToPipelineConfig()` + 클라이언트 사전 검증 |
| **실행 제출 모달** | ExecutionSubmittedModal — polling 제거, 확인 모달 |
| 실행 이력 페이지 | PipelineHistoryPage — 태스크 타입 선택 모달 |
| processing.log | 파이프라인 실행 로그 영구 보관 |
| data.yaml 루트 배치 | YOLO 메타 파일 표준 위치 통일 |
| **비동기 데이터셋 등록** | Celery register_dataset 태스크 |
| **필터 카테고리 분리** | FILTER(Annotation 필터) / IMAGE_FILTER(Image 필터) |
| **NodePalette Tooltip** | 괄호→Tooltip 분리, 노드 라벨 축약 |
| **OperatorNode 실시간 params** | store 직접 구독, textarea 축약 표시 |
| 노드 삭제 | 캔버스에서 노드 삭제 동작 확인됨 |
| pytest 전체 통과 | 테스트 전부 통과 |

### 미완료 (Phase 2 남은 작업)

#### 즉시 필요

1. **MergeNode params_schema 기반 폼** — 현재 merge는 params 없이 동작하지만 향후 확장 대비 (보류 가능)

#### 백엔드 확장

2. **추가 Manipulator 구현** (lib/manipulators/ 하위)
   - `remap_class_name` — category name 변경
   - `filter_keep_by_class` — 특정 class 포함 이미지만 유지 (IMAGE_FILTER)
   - `filter_remove_by_class` — 특정 class 포함 이미지 제거 (IMAGE_FILTER)
   - `filter_invalid_class_name` — regex/blacklist 매칭 이미지 제거 (IMAGE_FILTER)
   - `sample_n_images` — N장 랜덤 샘플 추출
   - `format_convert_visdrone_to_coco` — VisDrone 포맷 변환

3. **DB seed 정비** — 16종 seed 중 4종만 코드 구현됨, 나머지 구현 필요

#### GUI 고도화

4. **엣지 연결 규칙 검증** — 현재 아무 노드나 연결 가능, 타입 호환성 체크 필요
5. **검증 결과 노드별 하이라이트** — validate API 결과를 개별 노드에 매핑

---

## 3. RAW 데이터셋 등록 플로우 (5차 업데이트)

사전 조건: 사용자가 등록할 데이터를 `LOCAL_UPLOAD_BASE` 경로에 미리 복사해 둔다.

3단계 위자드 UI:
1. **태스크 타입 선택** — 다중 선택 (DETECTION, SEGMENTATION 등)
2. **파일 선택** — 서버 파일 브라우저로 이미지 디렉토리 + 어노테이션 파일 선택
3. **어노테이션 포맷 + 그룹명 입력 → 등록**

**등록 실행 흐름 (비동기):**

```
[프론트] 등록 버튼 클릭
    → POST /api/v1/dataset-groups/{id}/register
    ↓
[백엔드 API]
    → DatasetGroup 생성 (또는 기존 그룹에 추가)
    → Dataset(status=PROCESSING) 즉시 생성
    → Celery register_dataset 태스크 dispatch
    → 202 응답 반환 { dataset_id, task_id }
    ↓
[프론트] 202 응답 수신
    → 성공 안내 모달 표시
    → "데이터셋 목록에서 상태를 확인하세요"
    ↓
[Celery Worker] (비동기, 프론트와 무관)
    → 이미지 폴더 복사 → 어노테이션 파일 복사 → 메타 파일 복사
    → 클래스 정보 자동 추출 (best-effort, 실패해도 등록은 정상 진행)
    → Dataset status: PROCESSING → READY (또는 ERROR)
```

**에러 처리:**
- 파일 복사 실패 시 Dataset을 ERROR 상태로 전이
- 부분 생성된 디렉토리는 `shutil.rmtree`로 정리
- 데이터셋 목록에서 ERROR 상태 확인 가능

---

## 4. 파이프라인 실행 상세 설계 (변경 사항 반영)

### 4-1. 실행 흐름 (5차 업데이트)

```
[사용자] → GUI 노드 에디터 → graphToPipelineConfig() → PipelineConfig 생성
    ↓
[클라이언트 사전 검증] — 사이클 감지, SaveNode 유무, 연결 완전성
    ↓
[검증] POST /api/v1/pipelines/validate
    → is_valid == false → issues 표시 → 수정 유도
    → is_valid == true  → 실행 진행
    ↓
[실행] POST /api/v1/pipelines/execute → 202 { execution_id }
    ↓
[프론트] ExecutionSubmittedModal 표시
    → "데이터셋 목록에서 상태를 확인하세요"
    → "계속 편집" 또는 "데이터셋 목록으로 이동"
    ↓
[Celery Worker] (비동기)
    → PipelineExecution(RUNNING) → Dataset(PROCESSING)
    → PipelineDagExecutor.run(config, target_version)
    → Phase A: Annotation 처리 (DAG topological sort)
    → Phase B: Image 실체화 (누락 이미지 스킵)
    → Annotation 작성 + processing.log 생성
    → 성공: Dataset(READY) + PipelineExecution(DONE) + Lineage
    → 실패: Dataset(ERROR) + PipelineExecution(FAILED)
```

### 4-2. PipelineConfig 스키마 (변경 없음)

```python
class PipelineConfig(BaseModel):
    name: str                              # 출력 DatasetGroup 이름
    description: str | None
    output: OutputConfig                   # dataset_type, annotation_format, split
    tasks: dict[str, TaskConfig]           # DAG 태스크 정의

class TaskConfig(BaseModel):
    operator: str                          # MANIPULATOR_REGISTRY 키
    inputs: list[str]                      # "source:<dataset_id>" 또는 태스크명
    params: dict[str, Any]

class OutputConfig(BaseModel):
    dataset_type: str = "SOURCE"           # SOURCE | PROCESSED | FUSION
    annotation_format: str | None = None   # None이면 마지막 태스크 포맷 유지
    split: str = "NONE"
```

### 4-3. 검증 코드 체계 (변경 없음)

정적 검증 (`lib/pipeline/pipeline_validator.py`):

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `INVALID_DATASET_TYPE` | ERROR | dataset_type != {SOURCE, PROCESSED, FUSION} |
| `RAW_NOT_ALLOWED_AS_OUTPUT` | ERROR | RAW 출력 불가 |
| `INVALID_SPLIT` | ERROR | split != {TRAIN, VAL, TEST, NONE} |
| `INVALID_ANNOTATION_FORMAT` | ERROR | format != {COCO, YOLO} |
| `UNKNOWN_OPERATOR` | ERROR | MANIPULATOR_REGISTRY 미등록 |
| `MERGE_MIN_INPUTS` | ERROR | merge_datasets 입력 < 2 |
| `MULTI_INPUT_WITHOUT_MERGE` | WARNING | 비-merge operator에 다중 입력 |

DB 검증 (`app/services/pipeline_service.py`):

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `SOURCE_DATASET_NOT_FOUND` | ERROR | DB에 없는 dataset_id |
| `SOURCE_DATASET_GROUP_DELETED` | ERROR | 소프트 삭제된 그룹 |
| `SOURCE_DATASET_NOT_READY` | ERROR | READY가 아닌 상태 |
| `SOURCE_DATASET_NO_ANNOTATIONS` | WARNING | annotation 미등록 |

### 4-4. 상태 전이 (변경 없음)

**PipelineExecution:** `PENDING -> RUNNING -> DONE | FAILED`
**Dataset:** `PENDING -> PROCESSING -> READY | ERROR`

### 4-5. Celery 설정 (5차 업데이트)

- Broker/Backend: PostgreSQL (Redis 미사용)
- Worker: backend과 동일 이미지, `backend_venv` 볼륨 공유
- 파이프라인 큐: `"pipeline"`, prefetch=1, timeout: soft 24h / hard 25h
- **등록 큐: `"default"`**, max_retries=0
- 재시도 없음 (양쪽 모두)

---

## 5. GUI 파이프라인 에디터 설계 (5차 업데이트)

### 5-1. 4종 커스텀 노드 (변경 없음)

| 노드 | 입력 핸들 | 출력 핸들 | 역할 |
|------|-----------|-----------|------|
| **DataLoadNode** | 없음 | 1개 | 3단계 캐스케이드 선택 (그룹->Split->버전) -> `source:<datasetId>` |
| **OperatorNode** | 1개 | 1개 | 범용 operator (카테고리별 색상/아이콘, **params 실시간 반영**) |
| **MergeNode** | N개 (동적) | 1개 | merge_datasets, 연결 엣지 수에 따라 핸들 자동 증가 |
| **SaveNode** | 1개 | 없음 | 출력 설정 (name, dataset_type, split, format) 인라인 폼 |

### 5-2. 노드 데이터 구조 (변경 없음)

```typescript
// DataLoadNode — source 참조만 생성, PipelineConfig tasks에 미포함
{ type: 'dataLoad', datasetId: string | null, datasetLabel: string }

// OperatorNode — tasks에 1:1 매핑
{ type: 'operator', operator: string, category: string, label: string,
  params: Record<string,any>, paramsSchema: object | null }

// MergeNode — tasks에 1:1 매핑
{ type: 'merge', operator: 'merge_datasets', params: {} }

// SaveNode — PipelineConfig top-level name/output에 매핑
{ type: 'save', name: string, description: string, datasetType: string,
  annotationFormat: string | null, split: string }
```

### 5-3. 페이지 구조 (변경 없음)

- `/pipelines` — 실행 이력 페이지 (AppLayout 내부, 사이드바 있음)
  - 태스크 타입 선택 모달 (DETECTION만 활성, 나머지 "준비 중")
- `/pipelines/editor?taskType=DETECTION` — 전체화면 에디터 (AppLayout 밖)

### 5-4. 노드 팔레트 카테고리 (5차 업데이트)

```typescript
const CATEGORY_META = {
  FORMAT_CONVERT: { label: '포맷 변환',       icon: <SwapOutlined />,          color: '#1677ff' },
  FILTER:         { label: 'Annotation 필터', icon: <FilterOutlined />,        color: '#eb2f96' },
  IMAGE_FILTER:   { label: 'Image 필터',      icon: <FilterOutlined />,        color: '#f5222d' },
  SAMPLE:         { label: '샘플링',           icon: <ScissorOutlined />,       color: '#722ed1' },
  REMAP:          { label: '리매핑',           icon: <RetweetOutlined />,       color: '#fa8c16' },
  AUGMENT:        { label: '증강',             icon: <ThunderboltOutlined />,   color: '#13c2c2' },
  MERGE:          { label: '병합',             icon: <MergeCellsOutlined />,    color: '#9254de' },
}
```

description의 괄호 부분(`"버튼 텍스트 (도움말)"`)은 Tooltip으로 자동 분리된다.

### 5-5. React Flow + Zustand 상태 동기화 패턴 (변경 없음)

```tsx
// 노드 컴포넌트에서 반드시 store 직접 구독 (node.data prop 사용 금지)
const nodeData = usePipelineEditorStore(
  (s) => (s.nodeDataMap[id] as DataLoadNodeData) ?? null,
)
```

```tsx
// 폼 영역에 className만 적용 (onMouseDown stopPropagation 금지)
<div className="nopan nodrag" style={{ padding: '8px 12px' }}>
  <Select ... />
  <Input ... />
</div>
```

---

## 6. MANIPULATOR_REGISTRY (현재 10종 구현)

### 코드 구현 완료

```python
MANIPULATOR_REGISTRY = {
    "format_convert_to_coco": FormatConvertToCoco,                                           # FORMAT_CONVERT
    "format_convert_to_yolo": FormatConvertToYolo,                                           # FORMAT_CONVERT
    "merge_datasets": MergeDatasets,                                                          # MERGE
    "filter_remain_selected_class_names_only_in_annotation": FilterRemainSelectedClassNamesOnlyInAnnotation,  # ANNOTATION_FILTER
    "filter_keep_images_containing_class_name": FilterKeepImagesContainingClassName,          # IMAGE_FILTER
    "filter_remove_images_containing_class_name": FilterRemoveImagesContainingClassName,      # IMAGE_FILTER
    "remap_class_name": RemapClassName,                                                       # REMAP
    "rotate_image": RotateImage,                                                              # AUGMENT (이미지 변형)
    "mask_region_by_class": MaskRegionByClass,                                                # AUGMENT (이미지 변형)
    "sample_n_images": SampleNImages,                                                         # SAMPLE
}
```

### DB Seed 등록 완료 (코드 미구현)

| 이름 | 카테고리 | 상태 |
|------|----------|------|
| `change_compression` | AUGMENT | seed만, 코드 미구현 |
| `format_convert_visdrone_to_coco` | FORMAT_CONVERT | seed만, 코드 미구현 |
| `format_convert_visdrone_to_yolo` | FORMAT_CONVERT | seed만, 코드 미구현 |
| `shuffle_image_ids` | SAMPLE | seed만, 코드 미구현 |

---

## 7. 출력 디렉토리 구조 (변경 없음)

### COCO 포맷 출력
```
source/output_name/train/v1.0.0/
├── processing.log          ← 파이프라인 실행 로그
├── images/
│   └── *.jpg
└── annotations/
    └── instances.json      ← COCO JSON
```

### YOLO 포맷 출력
```
source/output_name/train/v1.0.0/
├── data.yaml               ← 클래스 정의 (데이터셋 루트)
├── processing.log          ← 파이프라인 실행 로그
├── images/
│   └── *.jpg
└── annotations/
    └── *.txt               ← YOLO 라벨 파일만 (classes.txt 없음)
```

---

## 8. 장기 TODO

| 항목 | 설명 | 시점 |
|---|---|---|
| 네이밍 점검 | `_write_data_yaml` 등 general한 함수명 리네이밍 | 별도 세션 |
| YOLO yaml path | data.yaml에 이미지 경로 미포함 -> 학습 시 path 주입 필요 | Step 2 (학습 자동화) |
| ~~ImageManipulationSpec 체인~~ | ~~spec 누적 로직 구현~~ | ✅ 완료 (record.extra에 누적, _build_image_plans에서 추출) |
| S3StorageClient | 3차 K8S 전환 시 구현 | Step 3 |
| React Flow Lineage 시각화 | DatasetLineage 데이터는 이미 생성됨 | Phase 2-b |
| EDA 자동화 | `app/tasks/eda_tasks.py` skeleton만 존재 | Phase 2-a |
| 테스트 자동화 | Integration/Regression/E2E 테스트 추가 | Celery 안정화 후 |
| 엣지 연결 규칙 검증 | 노드 타입 호환성 체크 | 다음 GUI 개선 세션 |
| 검증 결과 노드별 하이라이트 | validate API 결과를 노드에 매핑 | 다음 GUI 개선 세션 |

---

## 9. 핵심 파일 맵 (현행)

### lib/ (순수 로직, DB 무의존)

| 파일 | 역할 |
|------|------|
| `lib/pipeline/config.py` | PipelineConfig, TaskConfig, OutputConfig (Pydantic) |
| `lib/pipeline/dag_executor.py` | PipelineDagExecutor — DAG 실행 + processing.log + COCO ID 보존 |
| `lib/pipeline/image_materializer.py` | ImageMaterializer — 이미지 복사 + 누락 스킵 (MaterializeResult) |
| `lib/pipeline/pipeline_data_models.py` | DatasetMeta, ImageRecord, Annotation 등 |
| `lib/pipeline/manipulator_base.py` | UnitManipulator ABC |
| `lib/pipeline/pipeline_validator.py` | 검증 결과 모델 + 정적 검증 |
| `lib/pipeline/storage_protocol.py` | StorageProtocol (typing.Protocol) |
| `lib/pipeline/io/coco_io.py` | COCO JSON 파서/라이터 |
| `lib/pipeline/io/yolo_io.py` | YOLO 디렉토리 파서/라이터 (data.yaml 별도) |
| `lib/pipeline/io/coco_yolo_class_mapping.py` | COCO 80클래스 표준 매핑 테이블 |
| `lib/manipulators/__init__.py` | MANIPULATOR_REGISTRY (4종) |
| `lib/manipulators/format_convert.py` | FormatConvertToCoco, FormatConvertToYolo |
| `lib/manipulators/merge_datasets.py` | MergeDatasets — COCO ID 보존/YOLO 순차 분기 |
| `lib/manipulators/filter_final_classes.py` | FilterFinalClasses — annotation 레벨 class 필터 |

### app/ (FastAPI + DB + Celery)

| 파일 | 역할 |
|------|------|
| `app/api/v1/pipelines/router.py` | POST /validate, POST /execute, GET /status |
| `app/api/v1/dataset_groups/router.py` | 데이터셋 등록 (202 즉시 응답) |
| `app/api/v1/manipulators/router.py` | GET /manipulators — GUI 노드 팔레트용 |
| `app/services/pipeline_service.py` | 검증 + 제출 + 상태 조회 서비스 |
| `app/services/dataset_service.py` | 데이터셋 CRUD + Celery 등록 dispatch |
| `app/tasks/pipeline_tasks.py` | Celery run_pipeline 태스크 (skipped_image_count 포함) |
| `app/tasks/register_tasks.py` | Celery register_dataset 태스크 (파일 복사 + 클래스 추출) |
| `app/tasks/celery_app.py` | Celery 앱 설정 (pipeline_tasks + register_tasks) |
| `app/schemas/pipeline.py` | API 스키마 (re-export + 응답 모델) |
| `app/core/storage.py` | LocalStorageClient — copy_annotation_meta_file은 데이터셋 루트로 |
| `app/models/all_models.py` | ORM 모델 전체 |

### frontend/

| 파일 | 역할 |
|------|------|
| `types/pipeline.ts` | 파이프라인 에디터 TypeScript 타입 전체 |
| `api/pipeline.ts` | 파이프라인/manipulator/datasets API 함수 |
| `stores/pipelineEditorStore.ts` | Zustand 에디터 상태 (nodeDataMap 중심, executionId) |
| `utils/pipelineConverter.ts` | graph<->PipelineConfig 변환 + 클라이언트 사전 검증 |
| `pages/PipelineEditorPage.tsx` | 전체화면 에디터 (React Flow 캔버스) |
| `pages/PipelineHistoryPage.tsx` | 실행 이력 + 태스크 타입 선택 모달 |
| `components/pipeline/nodes/DataLoadNode.tsx` | 3단계 캐스케이드 선택 노드 |
| `components/pipeline/nodes/OperatorNode.tsx` | 범용 operator 노드 (store 직접 구독, params 실시간 반영) |
| `components/pipeline/nodes/MergeNode.tsx` | 다중 입력 merge 노드 |
| `components/pipeline/nodes/SaveNode.tsx` | 출력 설정 싱크 노드 |
| `components/pipeline/NodePalette.tsx` | 좌측 노드 팔레트 (카테고리별, Tooltip 도움말) |
| `components/pipeline/EditorToolbar.tsx` | 상단 툴바 |
| `components/pipeline/PropertiesPanel.tsx` | 우측 속성 패널 |
| `components/pipeline/DynamicParamForm.tsx` | params_schema 기반 동적 폼 (7 타입) |
| `components/pipeline/ExecutionStatusModal.tsx` | ExecutionSubmittedModal — 실행 제출 확인 모달 |
| `components/pipeline/PipelineJsonPreview.tsx` | JSON 프리뷰 디버그 패널 |

### 검증 완료된 파이프라인 시나리오

| 시나리오 | 결과 |
|----------|------|
| coco128(YOLO) -> format_convert_to_coco -> Save | 126장 (2장 스킵), COCO 출력 |
| coco128(YOLO) + coco4 -> 각각 COCO 변환 -> merge -> Save | 130장 (2장 스킵), COCO 출력 |
| coco_val -> format_convert_to_yolo -> Save | YOLO 출력, data.yaml 루트 배치 확인 |
| coco128(YOLO) -> format_convert_to_coco -> filter_final_classes -> Save | annotation 필터 검증 필요 |
