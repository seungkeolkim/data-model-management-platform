# Manipulator 확장 + 샘플 뷰어 YOLO 지원 + GUI 고도화 — 핸드오프

> 브랜치: `feature/data-manipulate-pipeline-gui-detection`
> 작업 기간: 2026-04-08
> 이전 핸드오프: `007-async-register-filter-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. Manipulator 확장 (4종 → 7종)

기존 4종(format_convert_to_coco, format_convert_to_yolo, merge_datasets, filter_final_classes)에서 3종 추가 + 1종 리네이밍.

**새로 구현:**

| manipulator | 카테고리 | 설명 |
|---|---|---|
| `filter_keep_images_containing_class_name` | IMAGE_FILTER | 지정 class를 포함한 이미지만 유지 (OR 로직) |
| `filter_remove_images_containing_class_name` | IMAGE_FILTER | 지정 class를 포함한 이미지 제거 (OR 로직) |
| `sample_n_images` | SAMPLE | N장 랜덤 샘플 추출 (seed 재현 가능) |

**리네이밍:**
- `filter_final_classes` → `filter_remain_selected_class_names_only_in_annotation`
- `FILTER` 카테고리 → `ANNOTATION_FILTER`

**핵심 파일:**
- `backend/lib/manipulators/filter_keep_images_containing_class_name.py`
- `backend/lib/manipulators/filter_remove_images_containing_class_name.py`
- `backend/lib/manipulators/sample_n_images.py`
- `backend/lib/manipulators/filter_remain_selected_class_names_only_in_annotation.py` (리네이밍)
- `backend/lib/manipulators/__init__.py` — MANIPULATOR_REGISTRY 7종 등록

**네이밍 규칙 확립:**
- 패턴: `{동작}_{대상}_{조건}` — 예: `filter_keep_images_containing_class_name`
- IMAGE_FILTER: 이미지 단위 필터 (이미지 전체를 유지/제거)
- ANNOTATION_FILTER: annotation 단위 필터 (이미지는 유지, annotation만 필터)

### 2. YOLO 샘플 뷰어 bbox 정규화 지원

YOLO 데이터셋의 샘플 뷰어에서 annotation bbox가 표시되지 않던 문제를 해결.

**원인:** `skip_image_sizes=True`로 캐시 생성 시 이미지 크기를 읽지 않아 YOLO 좌표→COCO 좌표 변환이 불가능했음 (bbox=None).

**해결 방식:**
- 백엔드: YOLO 파서에서 이미지 크기 없을 때 정규화된 좌표(0~1)를 COCO 형식 `[x,y,w,h]`로 저장
- 백엔드: `sample_index.json` 캐시에 `bbox_normalized: bool` 플래그 추가
- 프론트엔드: `bbox_normalized=true`이면 `img.naturalWidth`/`img.naturalHeight`로 실시간 변환

**핵심 파일:**
- `backend/lib/pipeline/io/yolo_io.py` — 정규화 좌표 저장 로직
- `backend/app/services/dataset_service.py` — `bbox_normalized` 플래그 생성
- `backend/app/schemas/dataset.py` — `SampleListResponse.bbox_normalized` 필드 추가
- `frontend/src/components/dataset-viewer/SampleViewerTab.tsx` — 프론트엔드 좌표 변환

### 3. GUI 노드 팔레트 고도화

파이프라인 에디터의 노드 팔레트와 캔버스 노드 스타일을 통합 관리하도록 개선.

**변경 사항:**
- `nodeStyles.ts` 신규 생성 — 카테고리별 색상/이모지, manipulator별 고유 이모지 중앙 관리
- 팔레트 버튼에 카테고리 색상 적용 (borderColor, color)
- 캔버스 노드와 팔레트 버튼의 색상/이모지 일치
- 카테고리별 차별화된 색상: ANNOTATION_FILTER(#eb2f96), IMAGE_FILTER(#cf1322), FORMAT_CONVERT(#1677ff), SAMPLE(#722ed1)

**핵심 파일:**
- `frontend/src/components/pipeline/nodeStyles.ts` — 스타일 정의 (공유)
- `frontend/src/components/pipeline/NodePalette.tsx` — 팔레트 스타일 적용
- `frontend/src/components/pipeline/nodes/OperatorNode.tsx` — 캔버스 노드 스타일 적용
- `frontend/src/components/pipeline/nodes/DataLoadNode.tsx`, `SaveNode.tsx`, `MergeNode.tsx` — 특수 노드 스타일 적용

### 4. 기타 개선

- **데이터셋 뷰어 탭 접근성:** READY가 아닌 데이터셋도 뷰어/EDA 탭 클릭 가능 (Alert 표시)
- **데이터셋 목록 클릭 우선순위:** `onRow` onClick에서 button/popover 등 인터랙티브 요소 클릭 시 row 클릭 무시
- **IMAGE_FILTER params 입력방식:** multiselect → textarea (줄바꿈 구분)으로 변경
- **filter_invalid_class_name 제거:** filter_remove_images_containing_class_name과 중복되어 삭제

---

## DB 변경 사항

스키마 변경 없음. Seed 데이터만 변경 (manipulator 이름/카테고리/description/params_schema).

- `002_seed_manipulators.py` — FILTER→ANNOTATION_FILTER, 이름 리네이밍, IMAGE_FILTER textarea 변경, filter_invalid_class_name 삭제

---

## 다음 세션에서 할 것

### 추가 manipulator 구현 (seed만 존재, 코드 미구현)
- `remap_class_name` (REMAP) — class name 매핑 테이블 적용
- `rotate_180` (AUGMENT) — 180도 회전
- `change_compression` (AUGMENT) — JPEG 압축률 변경
- `mask_region_by_class` (AUGMENT) — 특정 class 영역 마스킹
- `format_convert_visdrone_to_coco/yolo` (FORMAT_CONVERT) — VisDrone 포맷 변환
- `shuffle_image_ids` (SAMPLE) — 이미지 ID 셔플

### GUI 에디터 고도화
- PropertiesPanel에서 노드 params 편집 UX 개선
- 파이프라인 실행 결과 상세 보기
