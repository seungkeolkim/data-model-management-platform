# 파이프라인 & Manipulator 시스템 — 다음 세션 핸드오프

> 브랜치: `feature/create-source-datasetgroup-by-type-conv`
> 작업 기간: 2026-04-02 ~ 2026-04-03

---

## 현재 완료된 것

### 1. 코드 분리: `backend/lib/` 패키지 신설

순수 로직(DB/FastAPI 무의존)을 `backend/lib/`로 분리 완료.
`backend/app/pipeline/`, `backend/app/manipulators/`는 re-export 래퍼로 전환.

```
backend/lib/
├── __init__.py
├── pipeline/
│   ├── config.py           ← PipelineConfig, SourceConfig, ManipulatorConfig (Pydantic)
│   ├── executor.py          ← PipelineExecutor, PipelineResult, load_source_meta_from_storage
│   ├── image_executor.py    ← ImageExecutor (이미지 복사/변환)
│   ├── manipulator.py       ← UnitManipulator ABC
│   ├── models.py            ← DatasetMeta, Annotation, ImageRecord, ImagePlan 등
│   ├── storage_protocol.py  ← StorageProtocol (typing.Protocol)
│   └── io/
│       ├── class_mapping.py ← COCO↔YOLO 80클래스 매핑 테이블
│       ├── coco_io.py       ← COCO JSON 파서/라이터
│       └── yolo_io.py       ← YOLO txt 파서/라이터 + data.yaml 생성
└── manipulators/
    ├── __init__.py          ← MANIPULATOR_REGISTRY
    └── format_convert.py    ← FormatConvertToCoco, FormatConvertToYolo
```

**의존 관계:**
- `lib/` → pydantic, PIL (선택), 표준 라이브러리만 사용
- `lib/` → `app/` 절대 import 없음
- `app/` → `lib/` import하여 사용 + re-export

**StorageProtocol:**
- `lib/pipeline/storage_protocol.py`에 typing.Protocol로 정의
- `resolve_path`, `exists`, `makedirs`, `build_dataset_uri`, `get_images_path`, `get_annotations_dir`
- `app.core.storage.StorageClient`가 이 프로토콜을 자동 만족 (runtime_checkable 확인됨)

**PipelineExecutor 생성자:**
```python
PipelineExecutor(storage: StorageProtocol, images_dirname: str = "images")
```
- `images_dirname`은 기존 `app_config.images_dirname` 대체 (DI)

### 2. 포맷 변환 Manipulator 구현

| Manipulator | 방향 | 테스트 |
|---|---|---|
| `format_convert_to_coco` | YOLO → COCO | ✅ CLI + pytest |
| `format_convert_to_yolo` | COCO → YOLO | ✅ CLI + pytest |

- COCO 80클래스 매핑 테이블 기반 자동 리매핑
- 역변환 roundtrip 검증 완료 (coco8, coco128)
- YOLO data.yaml 자동 생성 (names dict 형태)

### 3. 파이프라인 실행 엔진 (CLI 테스트용)

`PipelineExecutor.run(config)` → `PipelineResult`:
1. Phase A: annotation 로드 → per-source manipulator → merge → post-merge
2. Phase B: 이미지 복사 계획(ImagePlan) 생성 → ImageExecutor 실행 → annotation 파일 작성

`_load_source_meta()`는 NotImplementedError — 서브클래스에서 오버라이드 필요.
CLI 테스트에서는 `CliPipelineExecutor` 서브클래스로 파일 기반 로드.

### 4. annotation_meta_file 지원

- DB `datasets` 테이블에 `annotation_meta_file` 컬럼 추가 (마이그레이션 005)
- 등록 위자드에서 메타 파일(data.yaml 등) 선택 가능
- 상세 페이지에서 메타 파일 교체/추가 가능 (PUT endpoint)
- 포맷 무관하게 DB 저장 (나중에 포맷 변경 시 활용 가능)

---

## 아직 안 된 것 (TODO)

### A. DB 연동 파이프라인 실행 (Phase 2 핵심)

**현재**: CLI에서 하드코딩된 소스 정보로 실행 → 파일만 생성
**필요**: GUI에서 소스 선택 → 파이프라인 실행 → DB에 DatasetGroup + Dataset + Lineage 자동 생성

구현 필요 항목:
1. `_load_source_meta()` DB 연동 구현 (Dataset ORM에서 storage_uri, annotation_files 조회)
2. 파이프라인 실행 후 DB에 결과 저장:
   - DatasetGroup 생성 (output_group_name, dataset_type, annotation_format)
   - Dataset 생성 (split, version, storage_uri, status=READY)
   - DatasetLineage 엣지 생성 (parent→child, transform_config 스냅샷)
   - PipelineExecution 레코드 생성
3. 파이프라인 실행 API 엔드포인트 (`POST /api/v1/pipelines/execute`)
4. 파이프라인 상태 조회 API

### B. Celery 태스크 통합

- `run_pipeline_task` Celery 태스크 생성
- 파이프라인을 단일 long-running task로 감싸기
- ImageExecutor의 progress_callback으로 진행률 DB 업데이트
- pipeline_executions 테이블에 진행률 저장
- 프론트 polling으로 진행 상태 표시

### C. 추가 Manipulator 구현

설계문서 기준 남은 manipulator 목록 (lib/manipulators/ 하위에 추가):

| 구현 우선순위 | name | 설명 | scope |
|---|---|---|---|
| 높음 | `remap_class_name` | category name 변경 | PER_SOURCE, POST_MERGE |
| 높음 | `filter_keep_by_class` | 특정 class 있는 이미지만 유지 | PER_SOURCE, POST_MERGE |
| 높음 | `filter_remove_by_class` | 특정 class 있는 이미지 제거 | PER_SOURCE, POST_MERGE |
| 중간 | `sample_n_images` | N장 샘플 추출 | PER_SOURCE, POST_MERGE |
| 중간 | `merge_datasets` | 복수 소스 병합 (이미지명 충돌 자동 해결) | POST_MERGE |
| 중간 | `format_convert_visdrone_to_coco` | VisDrone → COCO | PER_SOURCE |
| 낮음 | `rotate_180` | 180도 회전 (이미지 변환 포함) | PER_SOURCE |
| 낮음 | `change_compression` | JPEG quality 조정 | PER_SOURCE |
| 낮음 | `mask_region_by_class` | 특정 class 영역 masking | PER_SOURCE |

### D. 파이프라인 GUI (Phase 2 프론트엔드)

3단계 마법사:
1. 출력 설정 (그룹명, 타입, 포맷, split)
2. 소스 선택 + per-source manipulator 설정
3. post-merge manipulator 설정 + 실행

### E. ImageManipulationSpec 누적 로직

현재 `build_image_manipulation()` 체인이 구조만 있고 실제 spec 누적 로직 미구현.
이미지 변환 manipulator (rotate, compress 등) 구현 시 함께 작업 필요.

### F. 네이밍 점검 (장기 TODO)

- `_write_data_yaml` → YOLO 전용임을 명확히 하는 이름으로 변경
- `lib/pipeline/io/` 내 함수명 전반적 점검
- 리네이밍 전용 세션에서 일괄 처리 예정

---

## 테스트 현황

```
backend/tests/
├── conftest.py                       ← pytest 픽스처 (DatasetMeta 등)
├── test_coco_io.py                   ← COCO JSON 파서/라이터 단위 테스트
├── test_yolo_io.py                   ← YOLO txt 파서/라이터 단위 테스트
├── test_yolo_yaml.py                 ← YOLO yaml 파싱 단위 테스트
├── test_class_mapping.py             ← 클래스 매핑 테이블 + remap 단위 테스트
├── test_format_convert.py            ← FormatConvertToCoco/ToYolo 단위 테스트
├── test_pipeline_cli.py              ← 파이프라인 실행 CLI 통합 테스트
├── test_real_data_roundtrip.py       ← 실제 데이터 roundtrip 테스트
├── convert_real_data.py              ← 실데이터 변환 스크립트
└── convert_with_yaml_roundtrip.py    ← yaml 기반 roundtrip 변환 스크립트
```

총 81개 테스트 통과 (2026-04-03 기준).

---

## 주의사항

1. **lib/에 app/ import 절대 금지** — 이 원칙이 깨지면 분리 의미 없음
2. **PipelineExecutor 생성 시 images_dirname 전달 필요** — app 레이어에서 `get_app_config().images_dirname` 읽어서 전달
3. **re-export 래퍼 유지** — `app/pipeline/`, `app/manipulators/`의 re-export 파일은 기존 코드 호환용. 새 코드에서는 `lib.*` 직접 import 권장
4. **YOLO data.yaml에 path 미포함** — 학습(Phase 2) 시 path 주입 필요할 수 있음
5. **StorageProtocol 확장 시** — `lib/pipeline/storage_protocol.py`와 `app/core/storage.py` 양쪽에 메서드 추가 필요
