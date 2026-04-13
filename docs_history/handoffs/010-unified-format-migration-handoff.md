# 통일포맷(Unified Format) 마이그레이션 — 핸드오프

> 브랜치: `feature/data-manipulate-pipeline-gui-detection-as`
> 작업 기간: 2026-04-09
> 이전 핸드오프: `009-manipulator-image-transform-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. 통일포맷 마이그레이션 (7 Stage 전체 완료)

COCO+YOLO 이종 포맷 데이터셋을 merge할 때 "포맷 불일치" 오류가 발생하는 근본 문제를 해결.
파이프라인 내부 데이터 모델을 포맷 무관(format-agnostic) 통일포맷으로 전환했다.

#### Stage 1: 데이터 모델 변경

| 변경 전 | 변경 후 |
|---------|---------|
| `Annotation.category_id: int` | `Annotation.category_name: str` |
| `DatasetMeta.categories: list[dict]` (`[{"id": 1, "name": "person"}]`) | `DatasetMeta.categories: list[str]` (`["person", "car"]`) |
| `DatasetMeta.annotation_format: str` | 필드 삭제 (포맷은 IO 경계에서만 의미 가짐) |

#### Stage 2: IO 파서 (로드 시 통일포맷 변환)

- **COCO 파서**: `category_id(int)` → `category_name(str)` 변환, categories를 `list[str]`로 반환
- **YOLO 파서**: `class_id(int)` → 클래스명 해석 (classes.txt / data.yaml / COCO 표준 80클래스 fallback)
- YOLO `image_sizes` 미제공 시 bbox를 normalized 좌표 그대로 저장 (기존: None)

#### Stage 3: IO 라이터 (저장 시 포맷별 ID 부여)

- **COCO writer**: `NAME_TO_COCO_ID` 표준 80클래스 매핑, 커스텀 클래스는 91번부터 순차 할당
- **YOLO writer**: categories를 알파벳순 정렬 → 0-based index 부여

#### Stage 4: DAG Executor 정리

- `_validate_input_formats()` 삭제 — 포맷 검증이 불필요해짐
- `_merge_metas()` 내부의 annotation_format 기반 로직 제거
- `PipelineResult.output_format` 신규 필드 (기존 `output_meta.annotation_format` 대체)

#### Stage 5: Manipulator 일괄 수정

7개 manipulator를 name 기반으로 전환:
- `filter_remain_selected_class_names_only_in_annotation`: `ann.category_id in keep_ids` → `ann.category_name in keep_names`
- `filter_keep_images_containing_class_name`: 동일 패턴
- `filter_remove_images_containing_class_name`: 동일 패턴
- `mask_region_by_class`: 동일 패턴
- `remap_class_name`: category dict 조작 → 문자열 리스트 조작
- `format_convert_to_coco/yolo`: no-op으로 전환 (deep copy만 반환)
- `merge_datasets`: `_build_unified_categories`, `_remap_annotations` 삭제 → 단순 name union

#### Stage 6: App 레이어 (DB 연동 + 프론트엔드)

**백엔드:**
- `pipeline_tasks.py`: `result.output_meta.annotation_format` → `result.output_format`
- `pipeline_service.py`: `config.output.annotation_format.upper()` (null 불가)
- `dataset_service.py`: sample_index.json `schema_version=2` 도입, category_name 기반 캐시
- `schemas/dataset.py`: `SampleAnnotationItem.category_id` 제거, `categories: list[str]`, `ClassDistributionItem.category_id` 제거
- `OutputConfig.annotation_format`: `str | None = None` → `str = Field(...)` (필수)

**프론트엔드:**
- `types/dataset.ts`: `SampleAnnotationItem.category_id` 제거, `categories: string[]`
- `SampleViewerTab.tsx`: `getCategoryColor(cat.id)` → `getCategoryColor(cat)`, `enabledCategoryIds` → `enabledCategoryNames`
- `EdaTab.tsx`: `key={item.category_id}` → `key={item.category_name}`

#### Stage 7: 정리 및 검증

- `test_cross_format_merge_preserves_annotations` 추가 (COCO+YOLO 기원 merge 검증)
- 전체 183 tests 통과
- 실제 COCO+YOLO 크로스포맷 merge 파이프라인 실행 성공 확인

### 2. VisDrone 포맷 변환 no-op 구현

`format_convert_visdrone_to_coco`, `format_convert_visdrone_to_yolo`를 no-op으로 구현하고 MANIPULATOR_REGISTRY에 등록. (총 12개)

### 3. GUI 포맷 변환 비활성화

- FORMAT_CONVERT 카테고리 전체를 회색 비활성 스타일로 표시
- 클릭 시 안내 모달: "통일포맷 도입으로 포맷 변환이 자동 수행됩니다"
- `change_compression`, `shuffle_image_ids` 클릭 시 "미구현 상태" 경고 모달

### 4. Save 노드 포맷 선택 변경

- "자동 (입력 포맷 유지)" 옵션 제거 — 통일포맷에서는 입력 포맷 개념이 없음
- COCO / YOLO만 선택 가능, 기본값 COCO

---

## 핵심 설계 결정

### 통일포맷 원칙

```
[디스크]  ──parse──▶  [통일포맷 DatasetMeta]  ──write──▶  [디스크]
 COCO/YOLO              category_name 기반               COCO/YOLO
 포맷별 ID              포맷 구분 없음                    저장 시 ID 부여
```

1. **파싱 시점**: 포맷별 ID → category_name(str)으로 변환
2. **파이프라인 내부**: 모든 manipulator가 name 기반으로 동작, 포맷 무관
3. **저장 시점**: Save 노드의 annotation_format에 따라 포맷별 ID 부여
   - COCO: 표준 80클래스는 `NAME_TO_COCO_ID` (1~90, 비순차), 커스텀은 91+
   - YOLO: 알파벳순 정렬 → 0-based

### 자연스러운 클래스 병합

categories가 `list[str]`이므로 동일 이름은 자동 dedup된다:
- `["person", "car"]` + `["person", "truck"]` → `["person", "car", "truck"]`
- `remap_class_name`으로 "pedestrian" → "person" 변경 시 자연 병합

### 캐시 호환성

`sample_index.json`에 `schema_version` 필드 도입:
- v1 (구 포맷): `category_id` 기반 → 감지 시 자동 재생성
- v2 (통일포맷): `category_name` 기반

---

## 변경된 파일 목록 (32개)

### lib/ (핵심 로직)
- `lib/pipeline/pipeline_data_models.py` — Annotation, DatasetMeta 모델 변경
- `lib/pipeline/config.py` — OutputConfig.annotation_format 필수화
- `lib/pipeline/dag_executor.py` — _validate_input_formats 삭제, PipelineResult.output_format
- `lib/pipeline/pipeline_validator.py` — None format 허용 제거
- `lib/pipeline/io/coco_io.py` — 파서/라이터 통일포맷 전환
- `lib/pipeline/io/yolo_io.py` — 파서/라이터 통일포맷 전환
- `lib/manipulators/__init__.py` — VisDrone 추가 (12개)
- `lib/manipulators/format_convert.py` — 4종 no-op (coco, yolo, visdrone×2)
- `lib/manipulators/merge_datasets.py` — name union, ID 리매핑 삭제
- `lib/manipulators/filter_*.py` (3개) — name 기반 필터링
- `lib/manipulators/mask_region_by_class.py` — name 기반
- `lib/manipulators/remap_class_name.py` — str list 조작

### app/ (서비스 레이어)
- `app/schemas/dataset.py` — category_id 제거, categories: list[str]
- `app/services/dataset_service.py` — schema_version=2, category_name 기반 캐시
- `app/services/pipeline_service.py` — annotation_format.upper()
- `app/tasks/pipeline_tasks.py` — output_format, class_mapping enumerate

### frontend/
- `src/types/dataset.ts` — category_id 제거
- `src/components/dataset-viewer/SampleViewerTab.tsx` — name 기반
- `src/components/dataset-viewer/EdaTab.tsx` — name 기반
- `src/components/pipeline/NodePalette.tsx` — FORMAT_CONVERT 비활성, 미구현 모달
- `src/components/pipeline/nodes/SaveNode.tsx` — 자동 옵션 제거, 기본값 COCO

### tests/ (14개)
- `tests/conftest.py`, `tests/test_coco_io.py`, `tests/test_yolo_io.py`, `tests/test_yolo_yaml.py`
- `tests/test_format_convert.py`, `tests/test_merge_datasets.py`, `tests/test_dag_executor_merge.py`
- `tests/test_class_mapping.py`, `tests/test_pipeline_config.py`, `tests/test_pipeline_validator.py`
- `tests/test_pipeline_cli.py`
- `run_pipeline_yaml.py`

---

## 검증 완료된 시나리오

| 시나리오 | 결과 |
|----------|------|
| COCO(coco2017 val) + YOLO(coco128) → filter → sample → merge → Save(COCO) | ✅ 136장, 이전 "포맷 불일치" 오류 해결 |
| 전체 pytest 183개 | ✅ 전부 통과 |
| 샘플 뷰어 API (schema_version=2 캐시) | ✅ 정상 응답 |
| EDA 통계 API | ✅ category_name 기반 |
| Lineage 그래프 | ✅ 기존과 동일 |

---

## 다음 세션 작업 후보

### 정합성/사용성 검증
1. **기존 데이터셋 샘플 뷰어/EDA 전수 확인** — 모든 READY 데이터셋에서 뷰어 정상 동작 확인
2. **파이프라인 재실행** — 기존에 성공했던 파이프라인을 통일포맷으로 재실행 검증
3. **YOLO 출력 검증** — Save(YOLO)로 파이프라인 실행 후 data.yaml + 라벨 정확성

### 미구현 manipulator
4. `change_compression` — 이미지 JPEG 압축률 변경 (AUGMENT)
5. `shuffle_image_ids` — 이미지 ID 랜덤 셔플 (SAMPLE)

### GUI 개선
6. 엣지 연결 규칙 검증 — 노드 타입 호환성 체크
7. 검증 결과 노드별 하이라이트
