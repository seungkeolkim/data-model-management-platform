# 데이터 관리 & 학습 자동화 플랫폼 — 3차 설계서

> **작업지시서 v3.0** | Phase 2 기준 (GUI 파이프라인 실행 + 추가 Manipulator)
> `objective_n_plan_2nd.md`의 Phase 2 진행 완료분 반영 + GUI 파이프라인 설계 구체화

---

## 1. 2차 대비 변경/추가된 설계

### 1-1. PipelineConfig DAG 구조 확정

2차 설계의 선형 `sources + post_merge_manipulators` 구조가
**DAG 기반 tasks 구조**로 개편 확정됨.

| 2차 설계 (폐기) | 3차 설계 (현행) |
|---|---|
| `sources: list[SourceConfig]` | `tasks: dict[str, TaskConfig]` |
| `post_merge_manipulators: list[ManipulatorConfig]` | DAG로 자유 조합 |
| `output_splits: list[str]` | `output.split: str` (단수) |

```yaml
# 3차 현행 구조
pipeline:
  name: "출력 그룹명"
  output:
    dataset_type: PROCESSED    # SOURCE | PROCESSED | FUSION
    annotation_format: COCO    # COCO | YOLO | null(자동)
    split: TRAIN               # TRAIN | VAL | TEST | NONE
  tasks:
    convert_a:
      operator: format_convert_to_coco
      inputs: ["source:<dataset_id>"]
      params: {}
    convert_b:
      operator: format_convert_to_coco
      inputs: ["source:<dataset_id>"]
      params: {}
    merge:
      operator: merge_datasets
      inputs: ["convert_a", "convert_b"]
      params: {}
```

**핵심:** `inputs`의 `source:` 접두사가 DB 데이터셋 참조, 태스크명이 이전 태스크 출력 참조.
실행 순서는 topological sort로 자동 결정.

### 1-2. 파일명 일괄 리네이밍 (004 핸드오프에서 확정)

| 이전 | 이후 |
|------|------|
| `executor.py` | `dag_executor.py` |
| `image_executor.py` | `image_materializer.py` |
| `manipulator.py` | `manipulator_base.py` |
| `models.py` | `pipeline_data_models.py` |
| `PipelineExecutor` | `PipelineDagExecutor` |
| `ImageExecutor` | `ImageMaterializer` |

### 1-3. merge_datasets multi-input 패턴

executor의 multi-input 처리 구조가 `accepts_multi_input` 클래스 속성 패턴으로 확정.

```python
class MergeDatasets(UnitManipulator):
    accepts_multi_input = True  # executor가 list[DatasetMeta]를 직접 전달

# dag_executor.py 분기:
if self._is_multi_input_manipulator(operator):
    result = self._apply_manipulator(input_metas_list, ...)  # list 직접 전달
elif len(input_metas) == 1:
    result = self._apply_manipulator(input_metas[0], ...)    # 단건
else:
    merged = self._merge_metas(input_metas)                  # 기존 폴백
    result = self._apply_manipulator(merged, ...)
```

향후 multi-input manipulator 추가 시 executor 수정 불필요.

### 1-4. 파이프라인 검증 시스템

실행 전 config 검증 + Web UI 오류 표시를 위한 시스템 신규 도입.

```
POST /api/v1/pipelines/validate
→ { is_valid, error_count, warning_count, issues[] }

issues[]: { severity, code, message, field }
```

정적 검증 7항목(lib/) + DB 검증 4항목(app/) = 총 11개 검증 규칙.

---

## 2. 현재 구현 상태 (2026-04-06)

### 완료된 것

| 항목 | 설명 |
|---|---|
| 데이터 모델 | `DatasetMeta`, `Annotation`, `ImageRecord`, `ImagePlan`, `DatasetPlan` |
| UnitManipulator ABC | `transform_annotation()` + `build_image_manipulation()` |
| 포맷 변환 manipulator | `format_convert_to_coco`, `format_convert_to_yolo` |
| **merge_datasets manipulator** | 복수 소스 병합, 파일명 충돌 해결, 카테고리 통합 |
| COCO↔YOLO 80클래스 매핑 | 표준 매핑 + 미지 클래스 순차 할당 |
| IO 계층 | `parse_coco_json`, `write_coco_json`, `parse_yolo_dir`, `write_yolo_dir` |
| **DAG 실행 엔진** | `PipelineDagExecutor.run()` — topological sort + multi-input 지원 |
| 이미지 실체화 | `ImageMaterializer` — 복사 지원, 변환 stub |
| **Celery 비동기 실행** | `run_pipeline` 태스크, 상태 머신(PENDING→RUNNING→DONE/FAILED) |
| **실행 API** | `POST /execute`(202), `GET /{id}/status`, `GET /` |
| **검증 API** | `POST /validate` — 정적 + DB 검증, 오류 사유 반환 |
| 코드 분리 | `lib/` 패키지, `app/` re-export 래퍼 |
| **pytest 202개** | 전부 통과 |

### 미완료 (Phase 2 남은 작업)

#### 프론트엔드 (우선순위: 최고)

1. **파이프라인 실행 UI — YAML 텍스트 입력 (MVP)**
   - YAML 텍스트 에디터 페이지
   - "검증" 버튼 → `POST /validate` → 결과(issues) 표시
   - "실행" 버튼 → `POST /execute` → 202 → polling으로 상태 추적
   - 실행 이력 목록 (GET /api/v1/pipelines)

2. **파이프라인 실행 UI — GUI 기반 DAG 위자드 (최종)**
   - 소스 데이터셋 선택 (DB 조회, READY 상태만)
   - operator 선택 + params 입력 (params_schema 기반 동적 폼)
   - DAG 노드/엣지 시각적 구성
   - PipelineConfig JSON 자동 생성 → validate → execute

3. **파이프라인 실행 상태 UI**
   - 실행 진행 화면 (polling)
   - 실행 이력 목록
   - Lineage 보기 연동

#### 백엔드

4. **추가 Manipulator 구현** (lib/manipulators/ 하위)
   - `remap_class_name` — category name 변경
   - `filter_keep_by_class` — 특정 class 있는 이미지만 유지
   - `filter_remove_by_class` — 특정 class 있는 이미지 제거
   - `sample_n_images` — N장 샘플 추출
   - `format_convert_visdrone_to_coco` — VisDrone 포맷 변환

5. **DB seed 정비**
   - manipulators 테이블에 merge_datasets 등 seed 레코드 추가
   - params_schema 정의 (GUI 동적 폼 생성용)

6. **진행률 업데이트** (선택)
   - dag_executor에 progress callback 추가
   - 이미지 실체화 단계별 DB 업데이트

---

## 3. 파이프라인 실행 상세 설계 (확정)

### 3-1. 실행 흐름

```
[사용자] → YAML 입력 또는 GUI 위자드 → PipelineConfig 생성
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
    → 성공: Dataset(READY) + PipelineExecution(DONE) + Lineage
    → 실패: Dataset(ERROR) + PipelineExecution(FAILED)
    ↓
[Polling] GET /api/v1/pipelines/{id}/status
    → { status, current_stage, processed_count, error_message, ... }
```

### 3-2. PipelineConfig 스키마 (현행)

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

### 3-3. 검증 코드 체계

정적 검증 (`lib/pipeline/pipeline_validator.py`):

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `INVALID_DATASET_TYPE` | ERROR | dataset_type ∉ {SOURCE, PROCESSED, FUSION} |
| `RAW_NOT_ALLOWED_AS_OUTPUT` | ERROR | RAW 출력 불가 |
| `INVALID_SPLIT` | ERROR | split ∉ {TRAIN, VAL, TEST, NONE} |
| `INVALID_ANNOTATION_FORMAT` | ERROR | format ∉ {COCO, YOLO} |
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

Pydantic 레벨 검증 (PipelineConfig model_validator):

| 검증 | 설명 |
|------|------|
| `_validate_task_references` | inputs가 정의된 태스크 또는 source: 참조인지 |
| `_validate_no_cycle` | DAG 순환 참조 감지 (Kahn's) |
| 자기 참조 금지 | 태스크가 자기 자신을 input으로 |

### 3-4. 상태 전이 (확정)

**PipelineExecution:** `PENDING → RUNNING → DONE | FAILED`
**Dataset:** `PENDING → PROCESSING → READY | ERROR`

### 3-5. Celery 설정 (확정)

- Broker/Backend: PostgreSQL (Redis 미사용)
- Worker: backend과 동일 이미지, `backend_venv` 볼륨 공유
- 전용 큐 `"pipeline"`, prefetch=1
- timeout: soft 24h / hard 25h, 재시도 없음

---

## 4. MANIPULATOR_REGISTRY (현재)

```python
MANIPULATOR_REGISTRY = {
    "format_convert_to_coco": FormatConvertToCoco,     # PER_SOURCE, COCO 출력
    "format_convert_to_yolo": FormatConvertToYolo,     # PER_SOURCE, YOLO 출력
    "merge_datasets": MergeDatasets,                    # POST_MERGE, multi-input
}
```

추가 예정:
- `remap_class_name` — category name 변경
- `filter_keep_by_class` / `filter_remove_by_class` — 클래스 기반 필터
- `sample_n_images` — 랜덤 샘플링
- `format_convert_visdrone_to_coco` — VisDrone 전용 변환

---

## 5. 장기 TODO

| 항목 | 설명 | 시점 |
|---|---|---|
| 네이밍 점검 | `_write_data_yaml` 등 general한 함수명 리네이밍 | 별도 세션 |
| YOLO yaml path | data.yaml에 이미지 경로 미포함 → 학습 시 path 주입 필요 | Step 2 (학습 자동화) |
| ImageManipulationSpec 체인 | spec 누적 로직 구현 | 이미지 변환 manipulator 구현 시 |
| S3StorageClient | 3차 K8S 전환 시 구현 | Step 3 |
| React Flow Lineage 시각화 | DatasetLineage 데이터는 이미 생성됨 | Phase 2-b |
| EDA 자동화 | `app/tasks/eda_tasks.py` skeleton만 존재 | Phase 2-a |
| 테스트 자동화 | Integration/Regression/E2E 테스트 추가 | Celery 안정화 후 |

---

## 6. 핵심 파일 맵 (현행)

### lib/ (순수 로직, DB 무의존)

| 파일 | 역할 |
|------|------|
| `lib/pipeline/config.py` | PipelineConfig, TaskConfig, OutputConfig (Pydantic) |
| `lib/pipeline/dag_executor.py` | PipelineDagExecutor — DAG 실행 엔진 |
| `lib/pipeline/image_materializer.py` | ImageMaterializer — 이미지 복사/변환 |
| `lib/pipeline/pipeline_data_models.py` | DatasetMeta, ImageRecord, Annotation 등 |
| `lib/pipeline/manipulator_base.py` | UnitManipulator ABC |
| `lib/pipeline/pipeline_validator.py` | 검증 결과 모델 + 정적 검증 |
| `lib/pipeline/storage_protocol.py` | StorageProtocol (typing.Protocol) |
| `lib/pipeline/io/` | COCO/YOLO 파서·라이터 |
| `lib/manipulators/__init__.py` | MANIPULATOR_REGISTRY |
| `lib/manipulators/format_convert.py` | FormatConvertToCoco, FormatConvertToYolo |
| `lib/manipulators/merge_datasets.py` | MergeDatasets |

### app/ (FastAPI + DB + Celery)

| 파일 | 역할 |
|------|------|
| `app/api/v1/pipelines/router.py` | POST /validate, POST /execute, GET /status |
| `app/services/pipeline_service.py` | 검증 + 제출 + 상태 조회 서비스 |
| `app/tasks/pipeline_tasks.py` | Celery run_pipeline 태스크 |
| `app/schemas/pipeline.py` | API 스키마 (re-export + 응답 모델) |
| `app/core/storage.py` | LocalStorageClient (StorageProtocol 만족) |
