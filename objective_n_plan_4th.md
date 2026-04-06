# 데이터 관리 & 학습 자동화 플랫폼 — 4차 설계서

> **작업지시서 v4.0** | Phase 2 기준 (GUI 파이프라인 에디터 완성 + 안정화)
> `objective_n_plan_3rd.md`의 GUI 에디터 구현 완료 + 파이프라인 안정화 반영
> 이전 설계서: `docs_history/objective_n_plan_3rd.md`

---

## 1. 3차 대비 변경/추가된 설계

### 1-1. ComfyUI 스타일 GUI 파이프라인 에디터 구현 완료

3차 설계의 "미완료" 항목이었던 GUI 기반 DAG 위자드가 React Flow 기반 전체화면 노드 에디터로 완성됨.

| 3차 설계 (미완료) | 4차 (현행) |
|---|---|
| YAML 텍스트 입력 (MVP) | 삭제 — GUI 에디터가 MVP |
| GUI 기반 DAG 위자드 (최종) | React Flow 노드 에디터 완성 |
| 파이프라인 실행 상태 UI | ExecutionStatusModal polling 완성 |

**핵심 기술 결정:**
- `@xyflow/react` v12.6+ 사용
- Zustand store(`nodeDataMap`)가 노드 도메인 데이터의 단일 진실 소스
- React Flow는 시각 상태(위치, 연결)만 관리
- 노드 컴포넌트는 `usePipelineEditorStore((s) => s.nodeDataMap[id])`로 직접 구독
- 노드 내부 폼 요소에 `className="nopan nodrag"` 적용 (`onMouseDown stopPropagation`은 Ant Design Select 차단하므로 금지)

### 1-2. 누락 이미지 스킵 처리

annotation에는 존재하지만 실제 파일이 없는 이미지를 파이프라인 중단 대신 경고와 함께 건너뛴다.
`MaterializeResult` dataclass로 `materialized_count`, `skipped_files`, `skipped_count` 반환.
Phase B 후 `output_meta.image_records`에서 스킵 이미지를 필터링하여 annotation도 정합성 유지.

### 1-3. processing.log — 파이프라인 실행 로그 영구 보관

파이프라인 실행 전 과정을 출력 디렉토리에 `processing.log`로 기록.
`_ProcessingLogBufferHandler`(logging.Handler 서브클래스)로 `lib` 네임스페이스 로그를 메모리 버퍼링, 실행 완료 후 파일 작성.

### 1-4. COCO 포맷 merge 시 공식 비순차 category_id 보존

COCO 80클래스 공식 ID 체계(1~90, 비순차)를 merge 시에도 보존.
- `merge_datasets.py` — `_build_unified_categories_preserve_ids()` (COCO용)
- `dag_executor.py` — `_merge_metas()`도 동일 로직 적용
- YOLO는 기존대로 0-based 순차 (`_build_unified_categories_sequential()`)

### 1-5. YOLO data.yaml 위치 변경 — annotations/ → 데이터셋 루트

data.yaml을 `annotations/` 밖, `images/`와 같은 레벨인 데이터셋 루트에 배치.
`classes.txt` 생성 제거 (data.yaml과 중복).

**적용 범위:** 원천 데이터 등록(`storage.py`), 파이프라인 출력(`dag_executor.py`), 파일 읽기(`dataset_service.py`) 모두 통일.

**결과 디렉토리 구조:**
```
source/coco136/train/v1.0.0/
├── data.yaml          ← 데이터셋 루트
├── processing.log
├── images/
│   └── *.jpg
└── annotations/
    └── *.txt          ← 순수 라벨 파일만 (또는 instances.json)
```

---

## 2. 현재 구현 상태 (2026-04-06)

### 완료된 것

| 항목 | 설명 |
|---|---|
| 데이터 모델 | `DatasetMeta`, `Annotation`, `ImageRecord`, `ImagePlan`, `DatasetPlan` |
| UnitManipulator ABC | `transform_annotation()` + `build_image_manipulation()` |
| 포맷 변환 manipulator | `format_convert_to_coco`, `format_convert_to_yolo` |
| merge_datasets manipulator | 복수 소스 병합, 파일명 충돌 해결, **COCO ID 보존** |
| COCO<->YOLO 80클래스 매핑 | 표준 매핑 + 미지 클래스 순차 할당 |
| IO 계층 | `parse_coco_json`, `write_coco_json`, `parse_yolo_dir`, `write_yolo_dir` |
| DAG 실행 엔진 | `PipelineDagExecutor.run()` — topological sort + multi-input 지원 |
| 이미지 실체화 | `ImageMaterializer` — 복사 지원, **누락 이미지 스킵**, 변환 stub |
| Celery 비동기 실행 | `run_pipeline` 태스크, 상태 머신(PENDING->RUNNING->DONE/FAILED) |
| 실행 API | `POST /execute`(202), `GET /{id}/status`, `GET /` |
| 검증 API | `POST /validate` — 정적 + DB 검증 |
| 코드 분리 | `lib/` 패키지, `app/` re-export 래퍼 |
| **GUI 파이프라인 에디터** | React Flow 노드 에디터 4종 노드, Zustand store |
| **Graph->PipelineConfig 변환** | `graphToPipelineConfig()` + 클라이언트 사전 검증 |
| **실행 상태 모달** | ExecutionStatusModal — polling + skipped 정보 |
| **실행 이력 페이지** | PipelineHistoryPage — 태스크 타입 선택 모달 |
| **processing.log** | 파이프라인 실행 로그 영구 보관 |
| **data.yaml 루트 배치** | YOLO 메타 파일 표준 위치 통일 |
| pytest 전체 통과 | 테스트 전부 통과 |

### 미완료 (Phase 2 남은 작업)

#### 즉시 필요

1. **DB 초기화 + 데이터 재등록** — data.yaml 위치 변경으로 기존 데이터 호환 안 됨
2. **실행 완료 모달에 skipped 정보 표시** — 현재 GUI에서 skipped 수를 확인할 수 없음
3. **MergeNode params_schema 기반 폼** — 현재 merge는 params 없이 동작하지만 향후 확장 대비

#### 백엔드 확장

4. **추가 Manipulator 구현** (lib/manipulators/ 하위)
   - `remap_class_name` — category name 변경
   - `filter_keep_by_class` / `filter_remove_by_class` — 클래스 기반 필터
   - `sample_n_images` — N장 샘플 추출
   - `format_convert_visdrone_to_coco` — VisDrone 포맷 변환

5. **DB seed 정비** — 14종 seed 중 3종만 코드 구현됨, 나머지 구현 필요

#### GUI 고도화

6. **엣지 연결 규칙 검증** — 현재 아무 노드나 연결 가능, 타입 호환성 체크 필요
7. **노드 삭제 기능** — 현재 캔버스에서 노드 삭제 미구현
8. **검증 결과 노드별 하이라이트** — validate API 결과를 개별 노드에 매핑

---

## 3. 파이프라인 실행 상세 설계 (확정, 변경 없음)

### 3-1. 실행 흐름

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
[Celery Worker]
    → PipelineExecution(RUNNING) → Dataset(PROCESSING)
    → PipelineDagExecutor.run(config, target_version)
    → Phase A: Annotation 처리 (DAG topological sort)
    → Phase B: Image 실체화 (누락 이미지 스킵)
    → Annotation 작성 + processing.log 생성
    → 성공: Dataset(READY) + PipelineExecution(DONE) + Lineage
    → 실패: Dataset(ERROR) + PipelineExecution(FAILED)
    ↓
[Polling] GET /api/v1/pipelines/{id}/status — 2초 간격
    → { status, current_stage, processed_count, error_message, skipped_image_count, ... }
```

### 3-2. PipelineConfig 스키마 (변경 없음)

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

### 3-3. 검증 코드 체계 (변경 없음)

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

### 3-4. 상태 전이 (변경 없음)

**PipelineExecution:** `PENDING -> RUNNING -> DONE | FAILED`
**Dataset:** `PENDING -> PROCESSING -> READY | ERROR`

### 3-5. Celery 설정 (변경 없음)

- Broker/Backend: PostgreSQL (Redis 미사용)
- Worker: backend과 동일 이미지, `backend_venv` 볼륨 공유
- 전용 큐 `"pipeline"`, prefetch=1
- timeout: soft 24h / hard 25h, 재시도 없음

---

## 4. GUI 파이프라인 에디터 설계 (신규)

### 4-1. 4종 커스텀 노드

| 노드 | 입력 핸들 | 출력 핸들 | 역할 |
|------|-----------|-----------|------|
| **DataLoadNode** | 없음 | 1개 | 3단계 캐스케이드 선택 (그룹->Split->버전) -> `source:<datasetId>` |
| **OperatorNode** | 1개 | 1개 | 범용 operator (카테고리별 색상/아이콘) |
| **MergeNode** | N개 (동적) | 1개 | merge_datasets, 연결 엣지 수에 따라 핸들 자동 증가 |
| **SaveNode** | 1개 | 없음 | 출력 설정 (name, dataset_type, split, format) 인라인 폼 |

### 4-2. 노드 데이터 구조

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

### 4-3. Graph -> PipelineConfig 변환

`utils/pipelineConverter.ts` — `graphToPipelineConfig()` + `validateGraphStructure()`

1. SaveNode 1개 찾기 (0개 또는 2개 이상이면 에러)
2. 엣지에서 각 노드의 입력 소스 결정
3. DataLoadNode는 task가 아님 -> 하위 노드 inputs에 `source:<datasetId>`로 변환
4. OperatorNode/MergeNode -> `task_<nodeId>` 이름의 task로 변환
5. SaveNode -> `config.name`, `config.output` 매핑

### 4-4. 페이지 구조

- `/pipelines` — 실행 이력 페이지 (AppLayout 내부, 사이드바 있음)
  - 태스크 타입 선택 모달 (DETECTION만 활성, 나머지 "준비 중")
- `/pipelines/editor?taskType=DETECTION` — 전체화면 에디터 (AppLayout 밖)

### 4-5. DataLoadNode 3단계 캐스케이드 선택

1. **데이터셋 그룹** — DETECTION 태스크 타입 + READY 데이터셋 있는 그룹만 표시
2. **Split** — 선택된 그룹의 READY 데이터셋에서 존재하는 split 추출
3. **버전** — 선택된 그룹+split의 READY 데이터셋 버전 목록

속성 패널 연동: 3단계 선택 완료 시 우측 PropertiesPanel에 데이터 타입, 어노테이션 포맷, 이미지 수, 클래스 수, 클래스 매핑 테이블 표시.

### 4-6. React Flow + Zustand 상태 동기화 패턴

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

```tsx
// useEffect 내 store 동기화 — 무한 루프 방지
const statusValue = statusData?.status
const processedCount = statusData?.processed_count
useEffect(() => {
  if (statusData) setExecutionStatus(statusData)
}, [statusValue, processedCount, setExecutionStatus])
```

---

## 5. MANIPULATOR_REGISTRY (현재)

### 코드 구현 완료 (3종)

```python
MANIPULATOR_REGISTRY = {
    "format_convert_to_coco": FormatConvertToCoco,     # PER_SOURCE, COCO 출력
    "format_convert_to_yolo": FormatConvertToYolo,     # PER_SOURCE, YOLO 출력
    "merge_datasets": MergeDatasets,                    # POST_MERGE, multi-input
}
```

### DB Seed 등록 완료 (14종, 코드 미구현)

| 이름 | 카테고리 | 상태 |
|------|----------|------|
| `filter_keep_by_class` | FILTER | seed만, 코드 미구현 |
| `filter_remove_by_class` | FILTER | seed만, 코드 미구현 |
| `filter_invalid_class_name` | FILTER | seed만, 코드 미구현 |
| `filter_final_classes` | FILTER | seed만, 코드 미구현 |
| `remap_class_name` | REMAP | seed만, 코드 미구현 |
| `rotate_180` | AUGMENT | seed만, 코드 미구현 |
| `change_compression` | AUGMENT | seed만, 코드 미구현 |
| `mask_region_by_class` | AUGMENT | seed만, EXPERIMENTAL |
| `format_convert_visdrone_to_coco` | FORMAT_CONVERT | seed만, 코드 미구현 |
| `format_convert_visdrone_to_yolo` | FORMAT_CONVERT | seed만, 코드 미구현 |
| `sample_n_images` | SAMPLE | seed만, 코드 미구현 |
| `shuffle_image_ids` | SAMPLE | seed만, 코드 미구현 |

---

## 6. 출력 디렉토리 구조 (확정)

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

## 7. 장기 TODO

| 항목 | 설명 | 시점 |
|---|---|---|
| 네이밍 점검 | `_write_data_yaml` 등 general한 함수명 리네이밍 | 별도 세션 |
| YOLO yaml path | data.yaml에 이미지 경로 미포함 -> 학습 시 path 주입 필요 | Step 2 (학습 자동화) |
| ImageManipulationSpec 체인 | spec 누적 로직 구현 | 이미지 변환 manipulator 구현 시 |
| S3StorageClient | 3차 K8S 전환 시 구현 | Step 3 |
| React Flow Lineage 시각화 | DatasetLineage 데이터는 이미 생성됨 | Phase 2-b |
| EDA 자동화 | `app/tasks/eda_tasks.py` skeleton만 존재 | Phase 2-a |
| 테스트 자동화 | Integration/Regression/E2E 테스트 추가 | Celery 안정화 후 |
| 엣지 연결 규칙 검증 | 노드 타입 호환성 체크 | 다음 GUI 개선 세션 |
| 노드 삭제 기능 | 캔버스에서 노드 삭제 미구현 | 다음 GUI 개선 세션 |
| 검증 결과 노드별 하이라이트 | validate API 결과를 노드에 매핑 | 다음 GUI 개선 세션 |

---

## 8. 핵심 파일 맵 (현행)

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
| `lib/manipulators/__init__.py` | MANIPULATOR_REGISTRY (3종) |
| `lib/manipulators/format_convert.py` | FormatConvertToCoco, FormatConvertToYolo |
| `lib/manipulators/merge_datasets.py` | MergeDatasets — COCO ID 보존/YOLO 순차 분기 |

### app/ (FastAPI + DB + Celery)

| 파일 | 역할 |
|------|------|
| `app/api/v1/pipelines/router.py` | POST /validate, POST /execute, GET /status |
| `app/api/v1/manipulators/router.py` | GET /manipulators — GUI 노드 팔레트용 |
| `app/services/pipeline_service.py` | 검증 + 제출 + 상태 조회 서비스 |
| `app/services/dataset_service.py` | 데이터셋 CRUD + 메타 파일 경로 해석 (루트 기준) |
| `app/tasks/pipeline_tasks.py` | Celery run_pipeline 태스크 (skipped_image_count 포함) |
| `app/schemas/pipeline.py` | API 스키마 (re-export + 응답 모델) |
| `app/core/storage.py` | LocalStorageClient — copy_annotation_meta_file은 데이터셋 루트로 |
| `app/models/all_models.py` | ORM 모델 전체 |

### frontend/

| 파일 | 역할 |
|------|------|
| `types/pipeline.ts` | 파이프라인 에디터 TypeScript 타입 전체 |
| `api/pipeline.ts` | 파이프라인/manipulator/datasets API 함수 |
| `stores/pipelineEditorStore.ts` | Zustand 에디터 상태 (nodeDataMap 중심) |
| `utils/pipelineConverter.ts` | graph<->PipelineConfig 변환 + 클라이언트 사전 검증 |
| `pages/PipelineEditorPage.tsx` | 전체화면 에디터 (React Flow 캔버스) |
| `pages/PipelineHistoryPage.tsx` | 실행 이력 + 태스크 타입 선택 모달 |
| `components/pipeline/nodes/DataLoadNode.tsx` | 3단계 캐스케이드 선택 노드 |
| `components/pipeline/nodes/OperatorNode.tsx` | 범용 operator 노드 |
| `components/pipeline/nodes/MergeNode.tsx` | 다중 입력 merge 노드 |
| `components/pipeline/nodes/SaveNode.tsx` | 출력 설정 싱크 노드 |
| `components/pipeline/NodePalette.tsx` | 좌측 노드 팔레트 (API 동적 로드) |
| `components/pipeline/EditorToolbar.tsx` | 상단 툴바 |
| `components/pipeline/PropertiesPanel.tsx` | 우측 속성 패널 |
| `components/pipeline/DynamicParamForm.tsx` | params_schema 기반 동적 폼 (7 타입) |
| `components/pipeline/ExecutionStatusModal.tsx` | 실행 상태 polling 모달 |
| `components/pipeline/PipelineJsonPreview.tsx` | JSON 프리뷰 디버그 패널 |

### 검증 완료된 파이프라인 시나리오

| 시나리오 | 결과 |
|----------|------|
| coco128(YOLO) -> format_convert_to_coco -> Save | 126장 (2장 스킵), COCO 출력 |
| coco128(YOLO) + coco4 -> 각각 COCO 변환 -> merge -> Save | 130장 (2장 스킵), COCO 출력 |
| coco_val -> format_convert_to_yolo -> Save | YOLO 출력, data.yaml 루트 배치 확인 |
