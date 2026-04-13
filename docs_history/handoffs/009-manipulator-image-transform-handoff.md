# Manipulator 확장 (remap/rotate/mask) + 이미지 변환 파이프라인 — 핸드오프

> 브랜치: `feature/data-manipulate-pipeline-gui-detection`
> 작업 기간: 2026-04-08
> 이전 핸드오프: `008-manipulator-sample-viewer-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. 신규 Manipulator 3종 (7종 → 10종)

| manipulator | 카테고리 | 설명 | 이미지 변환 |
|---|---|---|---|
| `remap_class_name` | REMAP | categories의 class name을 매핑 테이블로 변경 | ❌ |
| `rotate_image` | AUGMENT | 90°/180°/270° 시계방향 회전 (bbox 자동 변환) | ✅ |
| `mask_region_by_class` | AUGMENT | 지정 class bbox 영역을 black/white로 마스킹 | ✅ |

### 2. 이미지 변환 파이프라인 연결 (Phase B)

기존에 stub이었던 이미지 변환 인프라를 완전히 연결:

**변환 명세 누적 (Phase A):**
- `transform_annotation()` 내에서 `record.extra["image_manipulation_specs"]`에 spec dict를 누적
- 이미지 필터로 제거된 record는 자연스럽게 specs도 사라짐 → 불필요한 계산 없음

**변환 명세 추출 (Phase B):**
- `dag_executor._build_image_plans()`: `record.extra`에서 specs 추출 → `ImagePlan.specs`에 전달
- `ImageManipulationSpec` import 추가

**이미지 실체화 (Phase B):**
- `ImageMaterializer._transform_and_save()`: 변환 대상은 복사 없이 소스를 PIL로 열어 변환 체인 적용 → 한 번만 저장
- `_apply_image_operation()`: Image 객체를 받아 변환된 Image를 반환하는 파이프라인 방식으로 변경
- 지원 operation: `rotate_image` (PIL transpose), `mask_region` (ImageDraw.rectangle)
- 원본 포맷/EXIF 보존, 그레이스케일 이미지 자동 RGB 변환

**핵심 파일:**
- `backend/lib/pipeline/dag_executor.py` — `_build_image_plans` specs 추출
- `backend/lib/pipeline/image_materializer.py` — `_transform_and_save`, `_apply_rotate`, `_apply_mask_region`
- `backend/lib/manipulators/rotate_image.py` — 회전 manipulator
- `backend/lib/manipulators/mask_region_by_class.py` — 마스킹 manipulator
- `backend/lib/manipulators/remap_class_name.py` — class name 변경 manipulator

### 3. GUI 개선

- **DAG 노드 params 표시 개선:**
  - `select` 타입: 노드 본문에서 인라인 드롭다운으로 직접 편집 (rotate_image 각도, mask fill color)
  - `key_value` 타입: 줄바꿈 "old → new" 형식으로 전체 표시 (remap_class_name)
  - 일반 params: "label: value" 형식으로 한 줄씩 표시 (paramsSchema에서 label 참조)
- **노드 생성 시 default 값 자동 채움:** `buildDefaultParams(paramsSchema)` — seed=42 등 기본값이 처음부터 보임
- **Lineage 탭, pipeline.png에도 동일한 params 표시 적용** (object → "old → new", 줄바꿈)
- **AUGMENT 카테고리 라벨:** "증강" → "Image 변형"

### 4. 검증 강화

- **REQUIRED_PARAMS 클래스 변수:** 모든 manipulator에 추가 (remap: mapping, filter: class_names, sample: n)
- **`_validate_required_params()`:** 필수 파라미터가 비어있으면 ERROR 수준 → 실행 차단
- **remap_class_name 중복 검사:** 변경 후 class name이 겹치면 RuntimeError → 파이프라인 비정상 종료

---

## 발견된 이슈

- **COCO 2017 val에 그레이스케일(L모드) 이미지 10장 존재** — PIL ImageDraw가 RGB tuple을 거부. `img.convert("RGB")` 방어코드 추가
- **rotate_180 리네이밍:** DB seed `rotate_180` → `rotate_image`로 변경. 90°/270°도 지원

---

## 다음 세션 작업 계획

### 1. 잔여 manipulator 구현

| 이름 | 카테고리 | 설명 |
|---|---|---|
| `change_compression` | AUGMENT | JPEG 압축률 변경 |
| `format_convert_visdrone_to_coco` | FORMAT_CONVERT | VisDrone → COCO 변환 |
| `format_convert_visdrone_to_yolo` | FORMAT_CONVERT | VisDrone → YOLO 변환 |
| `shuffle_image_ids` | SAMPLE | 이미지 ID 셔플 |

### 2. 추가 manipulator (신규)

- **IoU 기반 겹치는 annotation 제거:** annotation 간 IoU를 계산하여 일정 임계값 이상 겹치는 annotation 제거
- **IoU 기반 마스킹:** 겹치는 영역을 마스킹 처리

### 3. 샘플 추출 시점 검토

`sample_n_images`의 DAG 내 위치에 따라 결과가 달라질 수 있음:
- 필터 전 샘플링 vs 필터 후 샘플링
- merge 전 per-source 샘플링 vs merge 후 전체 샘플링
- GUI에서 권장 위치를 안내하거나, 검증 단계에서 경고를 띄울지 검토 필요

### 4. 파이프라인 실행 전 정합성 검사

현재 검증은 기본적인 수준 (operator 존재, merge 입력 수, required params). 추가 필요:
- **연결 가능성 검증:** DAG에 연결되지 않은 고립 노드 탐지
- **입출력 제약 검증:** annotation format 호환성 (COCO 전용 manipulator에 YOLO 입력 등)
- **순환 참조 탐지:** DAG 사이클 검출
- **scope 검증:** PER_SOURCE manipulator가 merge 후에 배치되었는지 등
