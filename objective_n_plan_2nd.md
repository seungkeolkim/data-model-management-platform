# 데이터 관리 & 학습 자동화 플랫폼 — 2차 설계서

> **작업지시서 v2.0** | Phase 2 기준 (Manipulator 시스템 & 파이프라인 실행)
> `objective_n_plan_1st.md`의 Phase 2 구체화 + 1차 구현 과정에서 확정된 설계 변경 반영

---

## 1. 1차 대비 변경된 설계

### 1-1. 코드 구조 변경: `backend/lib/` 도입

1차 설계서의 `app/pipeline/`, `app/manipulators/` 구조에서 **순수 로직을 `lib/`로 분리**하는 방향으로 변경.

| 1차 설계 (기존) | 2차 설계 (현행) | 비고 |
|---|---|---|
| `app/pipeline/models.py` | `lib/pipeline/models.py` | 순수 dataclass |
| `app/pipeline/manipulator.py` | `lib/pipeline/manipulator.py` | ABC, DB 무의존 |
| `app/pipeline/executor.py` | `lib/pipeline/executor.py` | StorageProtocol로 DI |
| `app/pipeline/image_executor.py` | `lib/pipeline/image_executor.py` | StorageProtocol로 DI |
| `app/pipeline/io/` | `lib/pipeline/io/` | 파서/라이터 순수 함수 |
| `app/manipulators/` | `lib/manipulators/` | manipulator 구현체 |
| `app/schemas/pipeline.py` (config 부분) | `lib/pipeline/config.py` | PipelineConfig 등 |
| — | `lib/pipeline/storage_protocol.py` | **신규** |

**`app/pipeline/`, `app/manipulators/`** 는 re-export 래퍼로 유지 (기존 import 호환).

**원칙**: `lib/` → `app/` import 금지. `app/` → `lib/` import만 허용.

### 1-2. StorageProtocol 도입

1차에서는 `PipelineExecutor`가 `app.core.storage.StorageClient`를 직접 import했으나,
lib/app 분리를 위해 **`typing.Protocol`** 기반 `StorageProtocol`을 도입.

```python
# lib/pipeline/storage_protocol.py
class StorageProtocol(Protocol):
    def resolve_path(self, relative_path: str) -> Path: ...
    def exists(self, relative_path: str) -> bool: ...
    def makedirs(self, relative_path: str) -> None: ...
    def build_dataset_uri(self, dataset_type, name, split, version) -> str: ...
    def get_images_path(self, storage_uri: str) -> Path: ...
    def get_annotations_dir(self, storage_uri: str) -> Path: ...
```

`app.core.storage.StorageClient`가 이 Protocol을 자동 만족 (structural subtyping).

### 1-3. PipelineExecutor 의존성 주입

| 1차 설계 | 2차 설계 |
|---|---|
| 모듈 레벨 `settings = get_settings()` | 제거 |
| 모듈 레벨 `app_config = get_app_config()` | 제거 |
| `_build_image_plans`에서 `app_config.images_dirname` 사용 | 생성자 파라미터 `images_dirname` |

```python
# 2차
executor = PipelineExecutor(
    storage=get_storage_client(),
    images_dirname=get_app_config().images_dirname,
)
```

### 1-4. annotation_meta_file 컬럼 추가

1차 설계서에 없던 `datasets.annotation_meta_file` (String(500), nullable) 추가.
YOLO의 data.yaml 같은 클래스 매핑 메타 파일을 DB에 기록.

- 포맷 무관하게 저장 (COCO여도 meta 있으면 저장)
- 상세 페이지에서 교체/추가 가능 (PUT endpoint)
- 마이그레이션: `005_add_annotation_meta_file.py`

### 1-5. 1차 설계 대비 미구현 → 불필요 확인된 항목

| 1차 설계 항목 | 상태 | 비고 |
|---|---|---|
| `pipeline/planner.py` | 불필요 | executor에서 직접 ImagePlan 생성 |
| `pipeline/registry.py` | 불필요 | `manipulators/__init__.py`의 MANIPULATOR_REGISTRY로 대체 |
| Materialized View | 미사용 | 쿼리 성능 충분, 필요시 도입 |

---

## 2. 현재 구현 상태 (2026-04-03)

### 완료된 것

| 항목 | 설명 |
|---|---|
| 데이터 모델 | `DatasetMeta`, `Annotation`, `ImageRecord`, `ImagePlan`, `DatasetPlan` |
| UnitManipulator ABC | `transform_annotation()` + `build_image_manipulation()` |
| 포맷 변환 manipulator | `format_convert_to_coco`, `format_convert_to_yolo` |
| COCO↔YOLO 80클래스 매핑 | 표준 매핑 + 미지 클래스 순차 할당 |
| IO 계층 | `parse_coco_json`, `write_coco_json`, `parse_yolo_dir`, `write_yolo_dir` |
| 파이프라인 실행 엔진 | `PipelineExecutor.run()` — Phase A + Phase B |
| 이미지 실행기 | `ImageExecutor` — 복사 지원, 변환 stub |
| YOLO data.yaml 생성 | `_write_data_yaml()` — names dict 형태 |
| CLI 테스트 | `test_pipeline_cli.py` — YOLO→COCO, COCO→YOLO |
| 코드 분리 | `lib/` 패키지 신설, `app/` re-export 래퍼 |
| pytest 81개 | IO, 매핑, 변환, roundtrip 전부 통과 |

### 미완료 (Phase 2 남은 작업)

#### 백엔드

1. **DB 연동 파이프라인 실행**
   - `_load_source_meta()` DB 조회 구현
   - 실행 후 DatasetGroup + Dataset + Lineage + PipelineExecution DB 생성
   - 파이프라인 실행 API (`POST /api/v1/pipelines/execute`)
   - 파이프라인 상태 조회 API (`GET /api/v1/pipelines/{id}`)

2. **Celery 태스크 통합**
   - `docker-compose.yml` celery-worker 활성화
   - `app/tasks/pipeline_task.py` 생성
   - ImageExecutor progress_callback → DB 진행률 업데이트
   - 프론트 polling 연동

3. **추가 Manipulator 구현** (lib/manipulators/ 하위)
   - `remap_class_name` — category name 변경
   - `filter_keep_by_class` — 특정 class 있는 이미지만 유지
   - `filter_remove_by_class` — 특정 class 있는 이미지 제거
   - `sample_n_images` — N장 샘플 추출
   - `merge_datasets` — 복수 소스 병합 + 이미지명 충돌 해결
   - `format_convert_visdrone_to_coco` — VisDrone 포맷 변환

4. **ImageManipulationSpec 누적 로직**
   - 현재 구조만 있고 체인 누적 미구현
   - 이미지 변환 manipulator (rotate, compress) 구현 시 함께 작업

#### 프론트엔드

5. **파이프라인 설정 마법사 UI**
   - Step 1: 출력 설정 (그룹명, dataset_type, annotation_format, split)
   - Step 2: 소스 선택 + per-source manipulator 설정
   - Step 3: post-merge manipulator 설정 + 확인/실행

6. **파이프라인 실행 상태 UI**
   - 실행 진행 화면 (진행률 polling)
   - 실행 이력 목록
   - Lineage 보기 버튼 활성화

---

## 3. 파이프라인 실행 상세 설계

### 3-1. 실행 흐름

```
[사용자] → GUI 파이프라인 마법사 → PipelineConfig 생성
    ↓
[API] POST /api/v1/pipelines/execute
    ↓
[서비스] config 검증 → PipelineExecution 생성 (PENDING)
    ↓
[Celery] run_pipeline_task.delay(execution_id)
    ↓
[PipelineExecutor]
    Phase A: annotation 처리 (빠름)
        1. 소스별 annotation 로드 (_load_source_meta)
        2. per-source manipulator 순차 적용
        3. 다중 소스 merge
        4. post-merge manipulator 순차 적용
    ↓
    Phase B: 이미지 실체화 (느림)
        5. ImagePlan 생성
        6. ImageExecutor 실행 (progress_callback → DB)
        7. annotation 파일 작성
    ↓
[DB] DatasetGroup + Dataset + Lineage 생성
     PipelineExecution.status = DONE
```

### 3-2. PipelineConfig 스키마

```python
class PipelineConfig(BaseModel):
    sources: list[SourceConfig]            # 1개 이상
    post_merge_manipulators: list[ManipulatorConfig]
    output_group_name: str
    output_dataset_type: str               # SOURCE | PROCESSED | FUSION
    output_annotation_format: str | None   # None이면 소스 포맷 유지
    output_splits: list[str]               # ["TRAIN"], ["TRAIN", "VAL"] 등
    description: str | None

class SourceConfig(BaseModel):
    dataset_id: str                        # 기존 Dataset UUID
    manipulators: list[ManipulatorConfig]

class ManipulatorConfig(BaseModel):
    manipulator_name: str                  # MANIPULATOR_REGISTRY 키
    params: dict[str, Any]
```

### 3-3. DB 연동 _load_source_meta 구현 방향

```python
class DbPipelineExecutor(PipelineExecutor):
    def __init__(self, storage, images_dirname, db_session):
        super().__init__(storage, images_dirname)
        self.db_session = db_session

    def _load_source_meta(self, dataset_id: str) -> DatasetMeta:
        dataset = self.db_session.get(Dataset, dataset_id)
        return load_source_meta_from_storage(
            storage=self.storage,
            storage_uri=dataset.storage_uri,
            annotation_format=dataset.annotation_format,
            annotation_files=dataset.annotation_files,
            annotation_meta_file=dataset.annotation_meta_file,
            dataset_id=dataset_id,
        )
```

### 3-4. Lineage 엣지 생성

파이프라인 실행 1회당:
- 소스 N개 → 출력 1개
- N개의 lineage 엣지 생성: `(parent=source_dataset_id, child=output_dataset_id)`
- 각 엣지에 `transform_config` JSONB: 해당 소스에 적용된 manipulator 설정 스냅샷

---

## 4. Manipulator 구현 가이드

### 새 Manipulator 추가 절차

1. `lib/manipulators/` 하위에 Python 파일 생성
2. `UnitManipulator` 상속, `name`, `transform_annotation` 구현
3. `lib/manipulators/__init__.py`의 `MANIPULATOR_REGISTRY`에 등록
4. DB `manipulators` 테이블에 seed 데이터 INSERT (params_schema 등)
5. pytest 작성

### Manipulator params_schema 규격

DB `manipulators.params_schema` (JSONB)로 GUI 동적 폼 자동 생성:

```json
{
  "class_names": {
    "type": "textarea",
    "label": "클래스 이름 목록",
    "description": "줄바꿈으로 구분",
    "required": false
  },
  "n_samples": {
    "type": "number",
    "label": "샘플 수",
    "default": 100,
    "min": 1,
    "required": true
  }
}
```

---

## 5. 장기 TODO

| 항목 | 설명 | 시점 |
|---|---|---|
| 네이밍 점검 | `_write_data_yaml` 등 general한 함수명 리네이밍 | 별도 세션 |
| YOLO yaml path | data.yaml에 이미지 경로 미포함 → 학습 시 path 주입 필요 | Phase 2 학습 |
| ImageManipulationSpec 체인 | spec 누적 로직 구현 | 이미지 변환 manipulator 구현 시 |
| S3StorageClient | 3차 K8S 전환 시 구현 | Step 3 |
