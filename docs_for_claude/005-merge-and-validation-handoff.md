# merge_datasets + 파이프라인 검증기 — 핸드오프

> 브랜치: `feature/additional-manipulators`
> 작업 기간: 2026-04-06
> 이전 핸드오프: `004-celery-pipeline-execution-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. merge_datasets Manipulator 구현

복수 소스 데이터셋을 하나로 병합하는 manipulator.

**핵심 파일:** `lib/manipulators/merge_datasets.py`

**처리 순서:**
1. 입력 검증 (list, 2개 이상, 포맷 동일)
2. 파일명 충돌 감지 → 충돌 파일만 prefix 적용
3. 카테고리 통합 (이름 기준 union, ID 순차 재번호)
4. annotation category_id remap
5. 이미지 레코드 병합 (image_id 순차 재번호, 출처 정보 extra에 보존)

**파일명 prefix 규칙:**
- 충돌 없는 파일: 원본 이름 유지
- 충돌 파일: `{dataset_name}_{md5(dataset_id)[:4]}_{원본파일명}`
- dataset_name: `DatasetMeta.extra["dataset_name"]`에서 가져옴

**ImageRecord.extra 출처 정보 (모든 병합 레코드에 저장):**
```python
{
    "source_dataset_id": "<원본 dataset_id>",
    "source_storage_uri": "<원본 storage_uri>",
    "original_file_name": "<원본 파일명>",
}
```

**DatasetMeta.extra 매핑 테이블 (rename된 파일만 기록):**
```python
{
    "file_name_mapping": {
        "<dataset_id_A>": {"000001.jpg": "coco8_a1b2_000001.jpg"},
        "<dataset_id_B>": {"000001.jpg": "visdrone_c3d4_000001.jpg"},
    },
    "source_dataset_ids": ["<dataset_id_A>", "<dataset_id_B>"],
}
```

**테스트:** `tests/test_merge_datasets.py` (37개)

### 2. DAG Executor multi-input 리팩터링

**핵심 변경:** `lib/pipeline/dag_executor.py`

- `accepts_multi_input` 클래스 속성 패턴 도입 — executor가 multi-input manipulator를 자동 감지
- 3-way 분기: multi-input manipulator bypass → 단일 입력 → 기존 `_merge_metas()` 폴백
- `_validate_input_formats()` 추가 — multi-input 태스크의 annotation_format 일치 검증
- `_build_image_plans()` 리팩터 — `record.extra`의 source 정보로 경로 구성, `storage.exists()` 호출 제거

**ImageMaterializer 변경:** `lib/pipeline/image_materializer.py`
- `if not src_path.exists(): return` 삭제 → `try/except FileNotFoundError` + raise로 대체

**dataset_name 주입:**
- `app/tasks/pipeline_tasks.py`: DatasetGroup.name → `meta.extra["dataset_name"]`
- `run_pipeline_yaml.py`: SQL JOIN으로 group_name 조회 → 동일하게 주입

**테스트:** `tests/test_dag_executor_merge.py` (12개)

### 3. 파이프라인 설정 검증기

실행 전에 설정의 유효성을 검사하고, 문제별 사유 메시지를 반환하는 시스템.

**핵심 파일:** `lib/pipeline/pipeline_validator.py`

**반환 구조:**
```python
PipelineValidationResult:
    is_valid: bool        # ERROR가 없으면 True
    error_count: int
    warning_count: int
    issues: list[PipelineValidationIssue]

PipelineValidationIssue:
    severity: "error" | "warning"
    code: str             # 기계 판독용 (예: "UNKNOWN_OPERATOR")
    message: str          # 한글 사유 메시지
    field: str            # 문제 위치 (예: "tasks.merge.operator")
```

**정적 검증 (DB 불필요, lib/ 레이어):**

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `INVALID_DATASET_TYPE` | ERROR | output.dataset_type 유효값 (SOURCE/PROCESSED/FUSION) |
| `RAW_NOT_ALLOWED_AS_OUTPUT` | ERROR | RAW는 파이프라인 출력 불가 |
| `INVALID_SPLIT` | ERROR | output.split 유효값 |
| `INVALID_ANNOTATION_FORMAT` | ERROR | annotation_format 유효값 (COCO/YOLO) |
| `UNKNOWN_OPERATOR` | ERROR | MANIPULATOR_REGISTRY 미등록 |
| `MERGE_MIN_INPUTS` | ERROR | merge_datasets 입력 < 2 |
| `MULTI_INPUT_WITHOUT_MERGE` | WARNING | 단일 입력 operator에 다중 입력 |

**DB 검증 (app/ 레이어):**

| 코드 | 수준 | 검증 내용 |
|------|------|-----------|
| `SOURCE_DATASET_NOT_FOUND` | ERROR | dataset_id가 DB에 없음 |
| `SOURCE_DATASET_GROUP_DELETED` | ERROR | 소속 그룹이 소프트 삭제됨 |
| `SOURCE_DATASET_NOT_READY` | ERROR | 상태가 READY가 아님 |
| `SOURCE_DATASET_NO_ANNOTATIONS` | WARNING | annotation 파일 미등록 |

**API 엔드포인트:**
```
POST /api/v1/pipelines/validate
Body: PipelineConfig (JSON)
Response: { is_valid, error_count, warning_count, issues[] }
```

**테스트:** `tests/test_pipeline_validator.py` (29개)

### 4. 네이밍 컨벤션 수정

- `backend/app/core/storage.py`: `cfg` → `app_config` (전체)
- `backend/app/services/dataset_service.py`: `p` → `validated_path`

### 5. E2E 검증 (merge 파이프라인)

`pipelines/merge_coco8_val.yaml`로 실제 테스트 완료:
- coco8 VAL (YOLO→COCO) + coco8_v2 VAL (YOLO→COCO) → merge → PROCESSED
- 동일 파일명 4개씩 → 8개 전부 rename + 정상 복사 확인
- 실행 명령: `cd backend && python3 run_pipeline_yaml.py pipelines/merge_coco8_val.yaml`

---

## 전체 테스트 현황

총 **202개** 테스트 전부 통과.

| 테스트 파일 | 테스트 수 | 설명 |
|-------------|-----------|------|
| test_merge_datasets.py | 37 | merge manipulator 단위 테스트 |
| test_dag_executor_merge.py | 12 | executor multi-input 통합 테스트 |
| test_pipeline_validator.py | 29 | 검증기 단위 테스트 |
| test_pipeline_config.py | 28 | DAG config 파싱/검증 |
| test_coco_io.py | 12 | COCO IO |
| test_format_convert.py | 10 | 포맷 변환 |
| test_yolo_io.py | 22 | YOLO IO |
| test_yolo_yaml.py | 12 | YOLO YAML 파싱 |
| 기타 | 40 | 매핑 테이블, roundtrip 등 |

---

## 커밋 히스토리 (이번 세션)

```
514dfa0 feat: 파이프라인 설정 검증기 구현 (정적 + DB 검증, validate API 엔드포인트)
f86370c feat: merge_datasets manipulator 구현 + DAG executor multi-input 지원 + 네이밍 컨벤션 수정
```

---

## 다음 세션 작업 (Phase 2 GUI 파이프라인)

### 목표
Web UI에서 파이프라인 DAG를 조합하고 실행하여 실제 데이터셋을 생성하는 것.

### 단계적 접근

**Step 1: YAML 텍스트 입력 방식 (MVP)**
- 프론트엔드에 YAML 텍스트 에디터 페이지 추가
- 사용자가 YAML을 직접 작성/붙여넣기
- "검증" 버튼 → `POST /api/v1/pipelines/validate` → 결과 표시
- "실행" 버튼 → `POST /api/v1/pipelines/execute` → 202 → polling
- 실행 상태 표시 (PENDING → RUNNING → DONE/FAILED)
- 실행 이력 목록 (GET /api/v1/pipelines)

**Step 2: GUI 기반 DAG 구성 위자드 (최종)**
- 소스 데이터셋 선택 (DB 조회)
- operator 선택 + params 입력 (params_schema 기반 동적 폼)
- DAG 노드/엣지 시각적 구성 (React Flow 등)
- 내부적으로 PipelineConfig JSON 생성
- 동일한 validate → execute 흐름

### 필요한 구현 (프론트엔드)

| 항목 | 설명 |
|------|------|
| 파이프라인 페이지 | 새 메뉴/라우트 추가 |
| YAML 에디터 컴포넌트 | CodeMirror/Monaco 또는 textarea |
| 검증 결과 표시 | issues 배열을 severity별 색상으로 표시 |
| 실행 상태 polling | execution_id 기반 주기적 GET |
| 실행 이력 목록 | GET /api/v1/pipelines 테이블 |

### 필요한 구현 (백엔드, 추가 작업)

| 항목 | 설명 |
|------|------|
| 추가 manipulator seed | DB manipulators 테이블에 merge_datasets 레코드 INSERT |
| manipulator 목록 API | GET /api/v1/manipulators (GUI 동적 폼 생성용) |
| source dataset 목록 API | 파이프라인 소스로 사용 가능한 dataset 조회 (READY 상태) |

### 주의사항

1. 검증 API는 이미 구현됨 — 프론트에서 호출만 하면 됨
2. execute API도 이미 구현됨 — Celery 연동 완료
3. 현재 MANIPULATOR_REGISTRY: `format_convert_to_coco`, `format_convert_to_yolo`, `merge_datasets`
4. 추가 manipulator (filter, sample, remap 등)는 GUI 작업 이후 순차 추가 예정
5. `lib/` → `app/` import 금지 원칙 유지
