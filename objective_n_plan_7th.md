# 데이터 관리 & 학습 자동화 플랫폼 — 7차 설계서

> **작업지시서 v7.5** | filename-identity 전환 + cls_rotate_image / cls_add_head 실구현 + 신규 Classification 노드 3종 stub + Binary label type 결정
> 기준일: 2026-04-20
> 이전 설계서: `docs_history/objective_n_plan_6th.md`
> 통합 핸드오프: `docs_for_claude/021-cls-rotate-and-new-stubs-handoff.md` (001~020은 `docs_history/handoffs/`)
> 노드 SDK 규약: `docs/pipeline-node-sdk-guide.md` (2026-04-15 재작성본)

6차 설계서의 §7-1 최우선 액션(노드 SDK화 + 가이드)이 완료되어 baseline에 편입됐다.
v7.2 에서 Classification DAG + Celery runner + manipulator prefix 통일(det_/cls_)이 baseline 에 들어갔고,
v7.3 에서 `cls_merge_datasets` 실구현과 3125장 드롭 버그 수정 과정에서 드러난
image-level `unknown` 라벨 규약 갭을 §2-12 로 명문화했으며,
v7.4 에서 `null` = unknown / `[]` = explicit empty 규약을 확정했다 (§2-12).
v7.5 에서 classification 이미지 identity 를 SHA → filename 으로 전환하고 (§2-13),
cls_demote_head_to_single_label / cls_sample_n_images / **cls_rotate_image** / **cls_add_head** / **cls_set_head_labels_for_all_images** / **cls_crop_image** 실구현을 완료했다.
cls_crop_image 는 최초 stub 의 상하좌우 4-필드 구조에서 실사용 흐름에 맞춰 `direction(상단|하단)` + `crop_pct(1~99)` 2-필드 수직축 crop 으로 scope 를 축소 확정 (§5),
§6-1 에 이미지 변형 시 **postfix rename 규약** 을 명문화 (cls_rotate_image 로 확립),
§6-2 Binary label type 방법론을 **(c) 주 + (b) 보조로 결정 완료** 했다 (2026-04-20).
DynamicParamForm 에 `checkbox` / `text` 타입 렌더러를 추가 (cls_add_head multi_label 체크박스 수용).
정적 파이프라인 검증기에 **`cls_add_head` head_name 체인 내 중복 검출 규칙** 을 추가 (§2-11-2, 2026-04-20).

---

## 1. 로드맵 위치

| Step | 범위 | 상태 |
|------|------|------|
| **Step 1** | 데이터셋 관리 (Phase 0~3) | Phase 2 **거의 마무리** (노드 SDK·자동 발견 완료), Phase 3 미착수 |
| **Step 2** | 학습 자동화 (단일/다중 GPU) | 진입 준비 (Phase 3 선행 필요) |
| **Step 3** | K8S 클러스터화, GPU 스케줄링 | 미착수 |
| **Step 4** | Label Studio / Synthetic Data / MLOps | 미착수 |
| **Step 5** | Generative Model MLOps | 미착수 |

---

## 2. 현재 구현 상태 (2026-04-13 baseline)

### 2-1. 백엔드

- FastAPI + async SQLAlchemy (asyncpg) + Alembic + Pydantic v2
- Celery worker = sync 세션(`SyncSessionLocal`). Broker/Backend = PostgreSQL. Concurrency=4, 큐 `pipeline / eda / default`
- 스토리지: `LocalStorageClient` (S3 대비 추상화)
- `lib/` ↔ `app/` 격리 — `lib/` → `app/` import 금지

### 2-2. 데이터 모델

- `DatasetGroup` / `Dataset` / `DatasetLineage` / `Manipulator` / `PipelineExecution` / `Objective`
- `dataset_type`: RAW / SOURCE / PROCESSED / FUSION (강제 제약은 없음, 그룹 속성)
- `Dataset` 유니크: `(group_id, split, version)`, `version` = `{major}.{minor}`
- `annotation_files`는 JSONB. `metadata`(JSONB)에 `class_mapping` 등 저장

### 2-3. 파이프라인 (통일포맷 기반)

- `PipelineConfig` (Pydantic): `name` / `description` / `output` / `tasks: dict[str, TaskConfig]` / `schema_version: int | None`
- 내부 표현은 **통일포맷** — `Annotation.category_name: str`, `DatasetMeta.categories: list[str]`
- 포맷별 integer ID는 IO 경계(파서/라이터)에서만 처리
- DAG 실행: Phase A(annotation 처리 — topological 순) → Phase B(이미지 실체화 — copy vs transform 분기)
- Celery 태스크 1건 = 파이프라인 전체 1실행 (Phase B가 주 병목)

### 2-4. MANIPULATOR_REGISTRY — 자동 발견 (26종: det 12 실구현 + cls 14 실구현)

- `lib/manipulators/__init__.py`가 `pkgutil.iter_modules`로 하위 모듈 순회, `UnitManipulator` 구체 서브클래스를 자동 수집
- 인스턴스 `.name` property를 키로 사용. 중복 name 즉시 RuntimeError (seed 정합성 보호)
- 새 manipulator 추가 = **파일 1개 + seed 1건**. 레지스트리 수정 불요
- **네이밍 prefix 규약**: detection = `det_`, classification = `cls_`. prefix 는 `manipulator.name` 에만 붙고 `ImageManipulationSpec.operation` 문자열에는 **절대 붙이지 않음** (operator vs operation 별개 namespace).

**Detection 12종 (`det_` prefix, 전부 실구현 완료):**
- `det_format_convert_to_coco` / `det_format_convert_to_yolo` / `det_format_convert_visdrone_to_coco` / `det_format_convert_visdrone_to_yolo`
- `det_merge_datasets`
- `det_filter_keep_images_containing_class_name` / `det_filter_remove_images_containing_class_name` / `det_filter_remain_selected_class_names_only_in_annotation`
- `det_remap_class_name` / `det_rotate_image` / `det_mask_region_by_class` / `det_sample_n_images`

**Classification 14종 (`cls_` prefix, 전부 실구현 완료):**
- ✅ `cls_rename_head`, `cls_rename_class`, `cls_reorder_heads`, `cls_reorder_classes`, `cls_select_heads`, `cls_merge_datasets` (`accepts_multi_input=True`, §2-11), `cls_merge_classes` (head 내 class 병합), `cls_demote_head_to_single_label` (multi→single 강등), `cls_sample_n_images` (N장 랜덤 샘플), `cls_rotate_image` (90°/180°/270° 회전 + postfix rename, §6-1), `cls_add_head` (신규 head 를 head_schema 말단에 추가, 기존 이미지 labels=null), `cls_set_head_labels_for_all_images` (head labels 모든 이미지 일괄 overwrite — set_unknown checkbox / classes 입력, single-label+multi-class assert 사전 차단), `cls_crop_image` (상단/하단 수직축 단일 crop + `_crop_{up|down}_{pct:03d}` postfix, §6-1), `cls_filter_by_class` (특정 head 의 classes include/exclude + unknown 토글 단일 필터 — 기존 `cls_remove_images_without_label` 을 `mode=exclude, classes=[], include_unknown=True` 조합으로 흡수 통합, §2-12 null/[] 구분 규약 승계)

**multi→single 강등 노드**: `cls_demote_head_to_single_label` (실구현 완료, on_violation skip/fail).

**미구현 Detection 2종:** `det_change_compression`, `det_shuffle_image_ids` (014 §3-3 승계).

### 2-5. GUI 파이프라인 에디터 — SDK 기반

- React Flow + Zustand `nodeDataMap` 단일 소스. `useNodeData(nodeId)`로 NodeComponent가 직접 구독
- **5종 NodeKind**: `dataLoad` / `operator` / `merge` / `save` / `placeholder`
- 노드 스펙은 `frontend/src/pipeline-sdk/definitions/<kind>Definition.tsx` 한 파일:
  - `paletteItems` — 팔레트 항목
  - `NodeComponent` — 캔버스 렌더링
  - `PropertiesComponent` — 우측 속성 패널
  - `validate` — 클라이언트 측 검증
  - `toConfigContribution` — graph → PipelineConfig 조각 기여
  - `matchFromConfig` — PipelineConfig → graph 복원 (claim 기반)
  - `matchIssueField` — 백엔드 issue 필드 매핑
- `assertRegistryCompleteness` — 부팅 시 NodeKind 집합 일치 검증
- `placeholder` — 미등록 operator도 유실 없이 복원, 실행 시 validate가 차단
- Merge 외 노드는 입력 엣지 1개 강제 (`onConnect` 가드 + 경고 모달)

### 2-6. 비동기 실행 체계

- 실행 제출: Celery dispatch 후 202 + `ExecutionSubmittedModal`
- 상세: 이력 행 클릭 → `ExecutionDetailDrawer` (공유 컴포넌트). Config JSON 확인/복사, JSON → DAG 복원 지원
- Celery 태스크 1건 = 파이프라인 1회. Phase B는 단일 worker 슬롯 내 순차 처리 (이미지 rotate/mask 시 수천 장 수 분 소요)

### 2-7. 버전 정책

- `{major}.{minor}` 2-tuple 문자열
- major = 수동(사용자 등록/실행), minor = automation 예약(미구현)
- 동일 group 내 split 별로 독립 증가

### 2-7-b. 데이터셋 그룹 목록 UI (개편 완료 · 2026-04-15)

그룹 목록 페이지(`frontend/src/pages/DatasetListPage.tsx`)가 Classification/Detection 혼재 환경에서 쓰기 쉬워지도록 필터·정렬·컬럼 구성을 개편했다.

- **필터 (다중 선택 + 서버 측 적용)**
  - `task_type` — DETECTION / CLASSIFICATION / SEGMENTATION / ZERO_SHOT
  - `dataset_type` — RAW / SOURCE / PROCESSED / FUSION
  - `annotation_format` — COCO / YOLO / ATTR_JSON / CLS_MANIFEST / CUSTOM / NONE
  - 같은 필터 내부는 OR, 서로 다른 필터 간은 AND
  - 이름 검색(`search`) 및 "reset filter" 버튼 포함
- **정렬 (컬럼 헤더 클릭, 서버 측)**
  - `sort_by`: `name` / `dataset_type` / `task_types` / `annotation_format` / `created_at` / `updated_at` / `dataset_count` / `total_image_count`
  - `sort_order`: `asc` / `desc` (기본 `updated_at desc`)
  - `dataset_count` / `total_image_count` 는 활성 Dataset 기준 LEFT JOIN 집계. 인덱스는 추가하지 않음 (현재 규모에서 계획 기반 정렬로 충분)
- **컬럼 구성 (좌→우)**
  - 사용 목적 / 그룹명 / 데이터 유형 / 포맷 / Split / 총 이미지 / 상태 / 등록일 / 최종 수정일 / 액션
  - 사용 목적 태그 색상은 task type 별로 분화 (DETECTION=geekblue, CLASSIFICATION=magenta, SEGMENTATION=cyan, ZERO_SHOT=gold)
- **API 호환성**
  - `GET /dataset-groups` 쿼리 파라미터에 `task_type`, `annotation_format`, `sort_by`, `sort_order` 추가. `dataset_type` 은 기존 단일 → 다중으로 확장
  - 다중 값은 FastAPI 반복 키 방식(`?k=a&k=b`). Axios `paramsSerializer: { indexes: null }` 로 직렬화
- **DatasetGroup.updated_at 자동 갱신**
  - SQLAlchemy `before_flush` 리스너가 Dataset insert/update/delete 를 감지해 부모 `DatasetGroup.updated_at` 을 현재 시각으로 갱신
  - 등록 파이프라인 · 파이프라인 실행 · PATCH API · soft delete 모두 커버
  - FastAPI 프로세스와 Celery worker 양쪽에서 리스너 등록 (`app/main.py`, `app/tasks/celery_app.py` 에서 `app.models.events` import)
  - 그룹 자체 수정은 기존 `onupdate=_now` 로 이미 처리됨 (중복 갱신 회피)

### 2-8. Classification 등록 (구현 완료 · 2026-04-14, filename-identity 전환 · 2026-04-20)

RAW Classification 데이터셋 등록을 Detection과 분리된 전용 흐름으로 구현. **end-to-end 테스트 완료**.

> **v7.5 변경 (2026-04-20, filename-identity 전환)**
> 이미지 identity 를 **SHA-1 content → filename** 으로 전환. SHA 기반 content dedup 과 `duplicate_image_policy` (FAIL/SKIP) 옵션을 전면 폐지하고, 파일명 충돌은 detection 등록과 동일한 규칙(warning + skip 또는 pipeline merge rename)으로 통일했다. 상세 배경·결정은 `docs_for_claude/020-*-handoff.md`.

**폴더 입력 규약 (사용자 준비)**
- `<root>/<head>/<class>/<images>` 2레벨 고정. LOCAL_UPLOAD_BASE에 준비 후 GUI로 split별 1회 등록
- `has_subdirs=true` (2레벨 초과) → **등록 차단**
- 빈 class 폴더(image_count=0) 허용 — 정식 class로 간주
- class 없는 head(classes=0) → warning (한 단계 아래를 루트로 잘못 선택한 경우)

**디스크 레이아웃 (LOCAL_STORAGE_BASE 하위)**
- 평면 `images/{원본 filename}` (샤딩 없음, basename 이 identity)
- `manifest.jsonl` — 이미지 1장 = 1줄
- `head_schema.json` — DB `DatasetGroup.head_schema` 복사본 (오프라인 학습용)
- 실패 시 `process.log` 보존 (dest_root 자체는 남기고 자식만 정리)

**Manifest 한 줄 스키마 (labels: `dict[str, list[str] | None]`, §2-12 확정)**
```json
{"filename":"images/img_0001.jpg",
 "original_filename":"img_0001.jpg",
 "labels":{"hardhat_wear":["helmet"],"visibility":null}}
```
- `sha` 필드 **없음** — filename 이 유일 identity (v7.5 확정)
- `["helmet"]` = known label, `null` = unknown (학습 제외), `[]` = explicit empty (전부 neg, multi-label 전용)

**DB 스키마 — 공유 테이블 + 확장 컬럼**
- `DatasetGroup`/`Dataset` 공유. classification 전용 테이블 만들지 않음 (lineage/pipeline/solution FK 호환)
- `DatasetGroup.head_schema JSONB` 신규 (migration 009, classification만 사용 — detection은 NULL):
  ```json
  {"heads":[{"name":"hardhat_wear","multi_label":false,"classes":["no_helmet","helmet"]}]}
  ```
- `AnnotationFormat` enum: **`CLS_MANIFEST` 신규, `CLS_FOLDER` 제거**
- `Dataset.class_count` int는 **detection 전용**. classification은 NULL 유지
- `Dataset.metadata.class_info`: classification에서는 head 배열 + `skipped_collision_count` + `skipped_collisions` 상세 저장

**head_schema 일관성 (동일 그룹 신규 버전 등록 시)**
- 기존 head의 classes **순서 변경/삭제 금지** (학습 index 계약 — `_diff_head_schema`에서 차단)
- 기존 head `multi_label` 변경 금지
- 신규 head 추가 → warning `NEW_HEAD` 후 허용
- 기존 head에 classes append (prefix 보존) → warning `NEW_CLASS` 후 허용 (사용자 책임)

**파일명 충돌 정책 (v7.5 · filename-identity)**
- 이미지 identity = filename. 같은 파일명이 여러 (head, class) 폴더에 등장하면 **같은 이미지로 간주** → multi-head 라벨로 통합한다.
- **single-label head 내 충돌**: 같은 파일명이 2개 이상 class 에 존재하면 사용자의 라벨링 오류로 판단 — warning 로그 + 해당 이미지 전체 skip (모든 head 에서 제외, pool 에도 저장 안 함)
  - `metadata.class_info.skipped_collisions` 에 `{filename, head_name, conflicting_classes, source_abs_paths}` 로 기록
  - `process.log` 에 요약 + 충돌 파일명 목록 보존, 최종 상태는 `READY_WITH_SKIPS (skipped=N)`
- **multi-label head 내 동일 파일명**: 여러 class 에 등장해도 충돌 아님 — class 들을 OR 로 병합 (`labels[head] = sorted([class_a, class_b, ...])`)
- 이미지 내용이 다른데 파일명이 같은 경우는 플랫폼이 감지할 수 없다 — 첫 발견 파일만 pool 에 저장됨(사용자 책임)
- 폐지된 옵션: `duplicate_image_policy` (FAIL/SKIP), `DuplicateConflictError`, `IntraClassDuplicate`, `skipped_conflicts`, `intra_class_duplicates`. Request 스키마 · 서비스 · Celery task · 등록 모달 UI 에서 모두 제거됨 (v7.5)

**실행 체계**
- 엔드포인트: `POST /dataset-groups/register-classification` (202 + Celery dispatch)
- Celery task: `app.tasks.register_classification_tasks.register_classification_dataset` (queue=default)
- RAW 등록이므로 PipelineExecution 미연결

### 2-10. Classification DAG 실행 경로 (완료 · 2026-04-15)

Classification 파이프라인 에디터 + Celery runner 가 완성되어 RAW 외에도 파이프라인 실행이 가능한 상태가 됐다. 단, manipulator 실체는 stub 단계이므로 operator 를 물려도 현재는 no-op.

**완료 범위**
- 파이프라인 에디터가 Classification 그룹을 Data Load / Save 대상으로 수용
- Operator 팔레트가 `compatible_task_types` 기준 Classification manipulator 만 노출
- `PipelineConfig.tasks` 빈 dict + `OutputConfig.passthrough_source_dataset_id` 조합으로 **Load→Save 직결(passthrough) 모드** 정식 지원
- DAG executor 가 task_kind(detection/classification) 를 `DatasetMeta.head_schema` 존재 여부로 분기
- passthrough 모드에서도 `pipeline.png` 생성 · lineage 엣지 1개 기록
- `manifest.jsonl` 의 `labels` 는 `dict[str, list[str] | None]` — `null` = unknown, `[]` = explicit empty (§2-12). IO 왕복 무손실
- `head_schema.json` = DatasetGroup.head_schema 불변 스냅샷, passthrough 시 그대로 복사

**남은 작업 → §5: Automation 실구현 + Detection 미구현 2종 + Step 2 학습 진입 준비**

### 2-11. Classification merge 정책 (설계 확정 + 실구현 완료 · 2026-04-16, filename-identity 전환 · 2026-04-20)

`cls_merge_datasets` 구현 전에 확정한 다중 입력 병합 정책.

**대원칙**: "학습에 영향을 줄 수 있는 것은 사용자에게 맡긴다." 시스템이 의미를 추정할 수 없는 충돌은 옵션을 주지 않고 warning 으로 맞춰 오도록 차단한다. 의미가 명확하지만 편의상 자동 처리가 가능한 충돌만 옵션화한다.

> **v7.5 변경 (2026-04-20).** 이미지 identity 를 SHA → filename 으로 전환하면서 `on_label_conflict` 옵션과 SHA dedup 단계가 모두 사라졌다. 파일명이 두 입력에 중복되면 detection 경로와 동일하게 `{display_name}_{md5_4}_{basename}` prefix rename 으로 공존시키고, label 병합 자체가 불필요해졌다.

#### 2-11-1. 노드 인터페이스

- **Multi-input**: 2개 이상 (N-way merge 허용). 결정론은 **graph edge 순서** 로 확보.
- **선행 manipulator 체인 유도**: strict 기본값을 통해 `cls_rename_head` / `cls_rename_class` / `cls_reorder_heads` / `cls_reorder_classes` 로 스키마를 맞춘 뒤 merge 하도록 자연스럽게 유도.

```python
cls_merge_datasets params:
  on_head_mismatch:      "error" (default) | "fill_empty"
  on_class_set_mismatch: "error" (default) | "multi_label_union"
  # on_label_conflict: v7.5 에서 삭제. SHA dedup 이 없으므로 이미지 단위 label 충돌 자체가 발생하지 않는다.
```

#### 2-11-2. 정적 검증 (FE primary + BE secondary)

Head/class 스키마는 DatasetGroup 에 이미 저장되어 있어 실행 전에 비교 가능.

**역할 분리:**
- **FE (1차 차단기 + UX)**: 에디터 `validate()` 에서 입력 head_schema 비교, 문제 노드 하이라이트 + "어떤 선행 manipulator 를 쓰라" 구체 가이드 + 실행 버튼 비활성화.
- **BE (최종 안전망)**: API 우회 / 자동화 스크립트 대비. `cls_merge_datasets` manipulator 진입 시 `raise ValueError(f"head 이름 불일치: {a} vs {b}")` 수준의 단순 assert. 정상 흐름에선 안 걸리므로 메시지 품질에 시간 쓰지 않음.

BE 검증을 생략하면 안 되는 이유: 9개 충돌 중 **4개 (head 이름/순서, class 이름/순서) 는 자연 에러 없이 silent 로 오염된 데이터가 생성**된다. Dataset + lineage 엣지까지 박힌 뒤 발견되면 rollback 비용이 크다.

**추가 규칙 — `cls_add_head` 중복 head_name 차단 (v7.5, 2026-04-20).** `backend/lib/pipeline/pipeline_validator.py::_validate_cls_add_head_duplicates` 가 `validate_pipeline_config_static` 의 8번째 항목으로 동작한다. 같은 DAG 체인(상속된 upstream) 에서 두 개 이상의 `cls_add_head` 가 동일 `head_name` 을 추가하려 하면 `CLS_ADD_HEAD_DUPLICATE` ERROR 로 즉시 차단. 독립 브랜치(공통 upstream 없음) 에서 같은 이름을 별도로 추가하는 경우는 허용 — 충돌은 이후 `cls_merge_datasets` 단계에서 §2-11 규칙으로 처리. source dataset 에 이미 존재하는 head_name 과의 충돌은 정적 단계에서 판단 불가 → `cls_add_head.transform_annotation` 런타임 assert 가 최종 방어선. 배경: pipeline id `a30a723f-ee93-4d5d-9e42-badba0d405ac` 에서 세 번째 노드가 첫 번째와 같은 `is_person` 을 추가했는데 정적 검증이 통과해 제출까지 된 버그를 재현 테스트(`TestValidateClsAddHeadDuplicates` 4건)로 고정.

| 충돌 유형 | 처리 |
|---|---|
| Head 이름 다름 (의미 같음) — 예: "species" vs "class" | **강제 error** — 시스템이 동일성 판별 불가. 사용자가 `cls_rename_head` 선행 |
| Head 이름 같은데 의미 다름 | 탐지 불가 — 그대로 merge (사용자 책임) |
| Head 갯수 다름 — 대칭차 존재 | `on_head_mismatch` 옵션 적용 |
| Head 순서 다름 (집합 동일) | **강제 error** — `cls_reorder_heads` 선행 |
| multi_label 플래그 다름 | **강제 error** — 의미 충돌 |
| Class 이름 다름 (같은 개념) | **강제 error** — `cls_rename_class` 선행 |
| Class 이름 같은데 의미 다름 | 탐지 불가 — 그대로 merge |
| Class 집합 다름 (head 내, 대칭차 존재) | `on_class_set_mismatch` 옵션 적용 |
| Class 순서 다름 (집합 동일) | **강제 error** — `cls_reorder_classes` 선행 |

#### 2-11-3. `on_head_mismatch = fill_empty`

- 결과 `head_schema` 는 A 순서 → (B − A) 추가 → (C − B − A) 추가 순으로 union
- 한쪽에만 있는 head 의 `multi_label` 플래그는 **non-empty 쪽 설정을 그대로 따름**
- 반대쪽 이미지 레코드는 해당 head 의 `labels` 에 `null` 삽입 (= unknown, §2-12 확정 규약)
- `labels[head_name]: list[str] | None` — `null` = unknown (학습 제외), `[]` = explicit empty (전부 neg)
- 이전(v7.3 이전)에는 `[]` 로 삽입해 single-label 오판을 일으킨 적 있음 (커밋 `130dc5f` 수정). v7.4 에서 `null` 규약으로 확정돼 우회 로직 불요.

#### 2-11-4. `on_class_set_mismatch = multi_label_union`

- 해당 head 를 **강제 `multi_label=True` 로 승격**
- `classes` 는 A 순서 → (B − A) 추가 → (C − B − A) 추가 순으로 union
- 각 이미지 레코드는 **원래 있었던 annotation 만 유지** (없는 class 를 새로 채우지 않음)
- **UI 모달 경고 필수**: "의미 변경(single→multi 강제 승격) 주의. 이후 `cls_merge_classes` / multi→single 변환 노드로 해소 책임은 사용자"

#### 2-11-5. 이미지 identity 와 label 충돌 (v7.5 확정 · filename 기반)

v7.4 까지 존재했던 `on_label_conflict` 옵션 (SHA dedup 후 동일 이미지 label 충돌 판정) 은 v7.5 에서 완전 삭제됐다. 이유는 단순하다.

- 이미지 identity = **filename**. 두 입력에서 같은 파일명이 등장하면 **detection 과 동일하게 rename 으로 공존시킨다** — 동일 이미지로 간주해 label 을 병합하지 않는다.
- Rename 규칙: `{display_name}_{md5_4}_{basename}` (display_name 은 `DatasetMeta.display_name` 이 있으면 그것을, 없으면 `dataset_id` 앞 12글자 + md5 4자리를 사용). `images/` 경로 prefix 는 유지하고 basename 만 변경된다.
- Rename 이 발생하면 `ImageRecord.extra` 에 Phase B 실체화용 메타를 심는다: `source_storage_uri` (원본 dataset 의 storage_uri), `original_file_name` (rename 이전 경로), `source_dataset_id`. `dag_executor` 의 classification Phase B 가 이 값으로 원본 파일을 찾아 새 이름으로 복사한다.
- 내용이 다르지만 파일명이 같은 케이스는 이제 rename 으로 자연스럽게 공존한다. 내용이 같더라도 파일명이 다르면 서로 다른 이미지로 취급되며, 이는 사용자가 선행 단계에서 정리할 책임 (플랫폼은 content hash 를 보지 않는다).

**§2-12 와의 관계.** head/class 집합 불일치로 인한 `labels[head] = null` (unknown) 은 이전과 동일하게 유지된다. fill_empty / multi_label_union 경로가 만드는 unknown 은 merge 단계가 아니라 **이후 학습 단계에서 loss mask** 로 해석된다. label 충돌 판정 단계가 사라졌을 뿐 unknown 규약 자체는 그대로다.

#### 2-11-6. 이미지 / 파일명 / Split

| 시나리오 | 처리 |
|---|---|
| file_name 다름 | 서로 다른 이미지 — 그대로 공존 |
| file_name 충돌 | **detection 과 동일한 prefix rename** (`{display_name}_{md5_4}_{basename}`) 로 공존, 드롭 없음 |
| file_name 동일하지만 내용이 다름 | rename 으로 공존 — 플랫폼은 내용을 보지 않음 |
| file_name 동일하고 내용도 동일 | 그래도 rename — v7.5 에서 content dedup 폐지됨 |
| Split 교차 merge (train + val) | **허용** — DAG 정합성 체크는 이후 과제 |

#### 2-11-7. 결과 head / class 순서

- Head / class 집합과 순서가 모든 입력에서 동일하면 **입력 A 순서 유지**
- 변경 필요 시: A 순서 → (B − A) 추가 → (C − B − A) 추가 (edge 순서 기준)

#### 2-11-8. 로깅

저장 위치는 **`processing.log` 단일 경로**. 별도 merge_report.json 같은 구조화 파일은 만들지 않는다 (로그 경로가 여러 곳이면 조회가 번잡해짐. 필요 시 후행 개선).

기록 내용 (v7.5 갱신):
- file_name rename 내역: 원본 → rename 결과 + source dataset_id (drop 은 발생하지 않음)
- 스키마 승격 내역: `multi_label_union` 으로 single → multi 승격된 head 이름
- 마지막에 summary 한 줄: `cls_merge_datasets: renamed=M, promoted=K heads`

### 2-12. Image-level `unknown` 라벨 규약 (확정 · 2026-04-17)

핸드오프: `docs_for_claude/018-image-level-unknown-semantics-handoff.md` §2.

**배경.** `cls_merge_datasets` 실구현 과정에서 multi-input merge 의 3125장 드롭 버그(커밋 `130dc5f`)를 수정하면서, manifest.jsonl 의 `labels` 필드가 **image-level 에서 unknown 을 표현할 공식 규약을 갖고 있지 않다**는 사실이 드러났다. v7.3 에서 옵션을 나열한 뒤 v7.4 에서 아래와 같이 확정.

#### 2-12-1. 확정 규약 — `null` = unknown, `[]` = explicit empty

**타입:** `dict[str, list[str] | None]`

```jsonc
// known — 라벨 있음
"labels": {"wear": ["helmet"], "color": ["red", "blue"]}

// explicit empty — 전부 neg (multi-label: BCE all zero)
"labels": {"wear": ["no_helmet"], "color": []}

// unknown — 이 이미지에서 해당 head 판단 안 함 (학습 시 loss mask 대상)
"labels": {"wear": null, "color": ["red"]}
```

| `labels[head]` 값 | 의미 | 학습 시 해석 |
|---|---|---|
| `null` | unknown — 판단 안 함 | 해당 head loss mask (학습에서 제외) |
| `[]` | explicit empty — 명시적 전부 neg | multi-label: BCE all zero, single-label: **허용 안 함** (아래 제약) |
| `["class", ...]` | known label(s) | 정상 학습 대상 |

**Single-label head 제약 (절대 규칙):**
- 허용 값: `null` (unknown) 또는 `[class 1개]` (known)
- `[]` 및 `[class 2개 이상]` 은 **writer assert 에러** — 디스크에 기록되기 전에 차단
- 이 제약은 `manifest_io.py` writer 에서 강제하며, manipulator 버그가 잘못된 데이터를 생성하는 것을 원천 방지

**Multi-label head:**
- `null` = 해당 head 전체 unknown (학습 제외)
- `[]` = 모든 class 가 explicit neg (BCE all zero — 정상 학습 대상)
- `["a", "b"]` = a, b 가 pos, 나머지 class 는 explicit neg

#### 2-12-2. Per-class unknown 처리 원칙

현 규약은 **head-level unknown 만 지원**하며 per-class unknown 은 표현하지 않는다. 대신 안전 원칙으로 대체:

> **per-class 에서 1개라도 unknown 이면 → head 전체를 `null` 로 승격한다.**
> "조금 덜 학습" > "잘못 학습" — 잘못된 neg 로 학습되는 것보다 해당 이미지의 head 를 통째로 loss mask 하는 것이 안전.

이 원칙이 적용되는 시나리오:
- `cls_merge_datasets` 의 `fill_empty` — 상대 schema 에 없던 head → `null`
- `cls_merge_classes` — merge 후 일부 class 판단 불가 → head = `null`
- multi→single 강등 — unknown class 존재 시 → head = `null`

per-class unknown 이 필수가 되는 시점(Step 4 auto-labeling)에 `labels` 구조를 확장한다 (옵션 A 또는 B 재검토).

#### 2-12-3. 방어 전략 — writer strict assert 단일

- **Writer (manifest_io.py)**: single-label head 에 `null` 또는 `[class 1개]` 외의 값이 오면 즉시 `ValueError`. 잘못된 데이터가 디스크에 박히는 것 자체를 차단.
- **Reader 방어 로직 없음**: 기존 classification 데이터는 전량 삭제 후 재등록. 구 manifest 호환 코드를 넣지 않는다.
- **Migration 스크립트 없음**: 위와 동일 이유.

#### 2-12-4. 코드 변경 범위

| 파일 | 변경 내용 |
|---|---|
| `lib/classification/ingest.py` | head 초기화 `[]` → `None` |
| `lib/pipeline/io/manifest_io.py` | writer 에 single-label assert 추가 |
| `lib/manipulators/cls_merge_datasets.py` | `fill_empty` → `None`, `_resolve_label_conflict` 단순화 (`original_classes_per_input` 우회 제거) |
| `lib/manipulators/cls_rename_class.py` | `None` guard 추가 |
| `lib/manipulators/cls_reorder_classes.py` | `None` guard 추가 |
| `backend/tests/test_cls_merge_datasets.py` | `[]` → `None` 반영 |

#### 2-12-5. 검토했으나 채택하지 않은 옵션 (기록 보존)

| 옵션 | 요약 | 미채택 사유 |
|---|---|---|
| A — class 상태 dict (`{red:pos, blue:unknown}`) | 완전한 표현력 | 현 스코프에서 과도한 파급. Step 4 시점에 재검토 |
| B — `unknown_classes` 보조 필드 | per-class unknown 가능, 호환 유지 | head-level 승격 원칙으로 현재 불필요 |
| C — `unknown_heads` 리스트 | head-level 마스크 | `null` 이 더 자연스럽고 추가 필드 불요 |
| D — 구조 불변, key 없음=unknown | migration 불요 | `null` 이 `[]` 과의 의미 구분이 더 명확 |

### 2-13. Classification filename-identity 전환 (확정 · 2026-04-20 · v7.5)

핸드오프: `docs_history/handoffs/020-classification-filename-identity-handoff.md` (→ 현행 `docs_for_claude/021-cls-rotate-and-new-stubs-handoff.md` §1-3 에서 이미지 변형 postfix rename 규약으로 이어짐).

**배경.** v7.4 까지 classification 은 이미지 identity 를 SHA-1 content hash 로 관리했다. 이 설계는 "파일명이 다르지만 내용이 같은 경우를 자동 dedup 한다" 는 편의가 있었으나, 실운영에서 다음 문제를 낳았다.

1. SHA 계산·비교 로직이 등록(`ingest`) + 병합(`cls_merge_datasets`) + Phase B 실체화(`dag_executor`) 각각에 분산되어 검증 포인트가 3개로 늘어났다.
2. Detection 파이프라인은 같은 상황에서 `{display_name}_{md5_4}_{basename}` prefix rename 으로 공존시키는데, classification 만 다른 규칙을 쓰고 있어 UI / 문서 / manipulator 가 이원화되어 있었다.
3. `duplicate_image_policy` (FAIL/SKIP) 옵션이 의미 있는 시나리오가 실제로는 거의 없었다 (대부분 사용자가 잘못 복사해 넣은 동일 파일명 케이스였다).

**결정 (v7.5 확정).**

- **이미지 identity = filename** (full relative path, `images/<basename>` 형태).
- **등록 경로 (`ingest_classification`)**: 같은 파일명이 여러 (head, class) 폴더에 등장하면 같은 이미지로 간주해 multi-head 라벨로 통합한다. single-label head 내 충돌은 사용자 라벨링 오류로 간주해 warning + skip (`skipped_collisions` 에 기록).
- **병합 경로 (`cls_merge_datasets`)**: 두 입력에 같은 파일명이 있으면 detection 과 동일한 prefix rename 으로 공존시킨다. label 충돌 판정 단계 자체가 사라진다.
- **Phase B 실체화 (`dag_executor`)**: classification 분기는 rename 이후 결과 파일명과 원본 파일명이 달라질 수 있으므로, `ImageRecord.extra` 의 `source_storage_uri` + `original_file_name` 으로 src 경로를 복원하고 `record.file_name` 은 dst 경로로만 사용한다.
- **폐지 항목**: `ImageRecord.sha`, `manifest.jsonl` 의 `sha` 필드, `duplicate_image_policy` (+ FE Radio UI), `DuplicateConflictError` / `DuplicateConflict` / `IntraClassDuplicate` dataclass, `metadata.class_info.skipped_conflicts` / `intra_class_duplicates`. Request 스키마, Celery task, 등록 모달 UI 에서 모두 제거됐다.

**Trade-off (명시적으로 수용).**
- 파일명이 다르지만 내용이 같은 사실상 중복 이미지는 **서로 다른 이미지로 들어간다**. 이는 사용자가 선행 단계에서 정리할 책임이다.
- 플랫폼은 content hash 를 보지 않는다 — SHA 관련 버그 / 호환성 부담이 0 이 되는 대가.

**호환성.** 기존 classification 데이터셋(SHA 기반으로 등록된 것)은 **전량 삭제 후 재등록** 전제 (v7.4 확정과 동일 기조). 구 manifest reader 호환 코드를 넣지 않는다. Alembic 마이그레이션 불요 (ORM 모델 / DB 컬럼 변경 없음; `metadata` JSONB 내부 구조만 변경).

**검증.** `/hdd1/data-platform/uploads/hardhat_classification/val` 실등록 (5613 입력, 1건 의도적 중복) → image_count=5612, `skipped_collisions=1` 기록. 이후 파이프라인 실행 2건 (pipeline_id `28ce7e89...`, `75919089...`) 성공, merge 결과 11224 장 (5612 × 2) 생성 확인.

**데이터 상세 뷰어 표시 규약 (v7.5 확정 · 2026-04-20).**

- Classification 샘플 뷰어는 **현재 storage pool 파일명 (`file_name`)** 을 기본 식별자로 노출한다. merge rename 이 적용된 이미지는 prefix 가 붙은 이름이 곧 탐색 / 링크의 기준이 된다.
- 원본 파일명 (`original_file_name`) 은 **rename 이 발생해 두 값이 달라진 경우에만 "(원본: …)" 로 병기**된다. RAW 등록 그대로인 이미지는 두 값이 동일하므로 한 줄만 보인다.
- API 응답 스키마 (`ClassificationSampleImageItem`): `file_name: str` (current) + `original_file_name: str | None` (달라질 때만 값). 폐지된 `sha` 필드는 응답에서 제거됨.
- 좌측 검색은 `file_name` + `original_file_name` 양쪽에 매칭 — 사용자가 원본 이름을 기억해도 rename 된 결과를 찾을 수 있다.

### 2-9. 노드 SDK 불변식 (절대 준수)

- NodeKind 추가는 **3군데 동시 갱신**: `NodeDataByKind` + `definitions/<kind>Definition.tsx` + `bootstrap.ts` + `registry.ts` expected 배열. 누락 시 런타임 assert로 부팅 실패 (의도된 감시)
- React Flow `node.data` prop은 초기값만 — NodeComponent는 반드시 `useNodeData(nodeId)` 훅으로 store 구독
- `matchFromConfig`는 자신이 소유한 `taskKey` / `sourceDatasetId`를 반드시 `ownedTaskKeys` / `ownedSourceDatasetIds`에 올려야 함. leftover는 `placeholder`가 수거
- `schema_version` 상승 시 `matchFromConfig`에서 분기 — 하위 호환 migrator는 도입 보류(YAGNI)

---

## 3. RAW 데이터셋 등록 플로우 (변동 없음)

3단계 위자드(태스크 타입 선택 → 파일 선택 → 포맷/그룹명) → 백엔드가 `LOCAL_UPLOAD_BASE` → `LOCAL_STORAGE_BASE` **copy** (원본 유지) → 버전 자동 생성.

---

## 4. 파이프라인 실행 상세 (변동 없음, §4-2만 갱신)

### 4-2. PipelineConfig 스키마 — `schema_version` 추가

```jsonc
{
  "name": "...",
  "description": "...",
  "output": { "dataset_type": "SOURCE", "annotation_format": "COCO", "split": "VAL" },
  "tasks": {
    "<task_id>": {
      "operator": "<manipulator_name>",
      "inputs": ["source:<uuid>", "<other_task_id>"],
      "params": { ... }
    }
  },
  "schema_version": 1
}
```

- `schema_version` 없으면 허용 (하위 호환), 상위 버전이면 복원 시 경고
- 최종 출력 = sink task 1개만 허용 (`get_terminal_task_name` 검증)

---

## 5. 남은 작업 (우선순위 순)

019 핸드오프 §3과 동일. 여기서는 요약만 둔다.

1. ~~Classification 데이터 입력~~ ✅ **완료 (2026-04-14)**
2. ~~Display / UI 분화 (상세 뷰어 + 목록 필터/정렬)~~ ✅ **완료 (2026-04-15)**
3. ~~Classification DAG 에디터 + Celery runner + passthrough 실행 경로~~ ✅ **완료 (2026-04-15 post-session)**
4. ~~`cls_merge_datasets` 실구현 + 호환성 검증 공유화~~ ✅ **완료 (2026-04-16)**
5. ~~Image-level `unknown` 라벨 규약 확정~~ ✅ **완료 (2026-04-17)** — `null` = unknown, `[]` = explicit empty (§2-12 확정)
6. ~~`null` 규약 코드 반영~~ ✅ **완료 (2026-04-17)** — 9개 파일, 192건 테스트 통과
   - 기존 classification 데이터셋 삭제 후 재등록 (사용자 수행)
7. ~~`cls_merge_classes` 실구현~~ ✅ **완료 (2026-04-17)** — head 내 class 병합 (single/multi-label OR), 팔레트 활성화 + 경고 모달, 17건 테스트
   - 파이프라인 실행 시 null labels 버그 수정 (`pipeline_tasks.py` class_info 생성)
8. ~~`cls_demote_head_to_single_label` 신설~~ ✅ **완료 (2026-04-17)** — multi→single 강등, on_violation skip/fail, 17건 테스트
9. ~~`cls_sample_n_images` 실구현~~ ✅ **완료 (2026-04-17)** — det_sample_n_images 동일 로직, 12건 테스트
10. ~~`cls_rotate_image` 실구현~~ ✅ **완료 (2026-04-20)** — 90°/180°/270° 회전, postfix rename (`_rotated_{degrees}`), src 복원 메타데이터 `record.extra.source_storage_uri / original_file_name`, 25건 테스트. §6-1 의 이미지 변형 공통 규약을 확립한 기준 구현.
11. ~~`cls_add_head` 실구현~~ ✅ **완료 (2026-04-20)** — 신규 head 를 head_schema **맨 뒤**에 추가, 기존 이미지의 신규 head labels 는 전부 `null` (§2-12). params UX 확정: `head_name` (text) + `multi_label` (checkbox, 기본 False) + `class_candidates` (textarea, 2개 이상, 중복 금지). Alembic `024_cls_add_head_params` 로 seed 갱신. DynamicParamForm 에 `checkbox` / `text` 타입 case 추가. 29건 테스트.
12. ~~`cls_set_head_labels_for_all_images` 실구현~~ ✅ **완료 (2026-04-20)** — 지정 head 를 모든 이미지에서 일괄 overwrite. params UX 단순화: `head_name` (text) + `set_unknown` (checkbox, 체크 시 null 로 초기화) + `classes` (textarea, 미체크 시 사용). single-label head 에 0개 또는 2개 이상 classes 입력 시 ValueError 로 사전 차단 (writer assert 이전). head_schema.classes SSOT 위반(바깥 이름) 거부. Alembic `025_cls_set_head_labels_params` 로 seed 갱신. 33건 테스트.
13. ~~`cls_crop_image` 실구현~~ ✅ **완료 (2026-04-20)** — 최초 seed 의 상하좌우 4-필드를 `direction(상단|하단)` + `crop_pct(1~99, default 30)` 2-필드 수직축 단일 crop 으로 scope 축소. postfix `_crop_{up|down}_{pct:03d}` (§6-1). `record.height *= (100-crop_pct)/100` 정수 내림, width 유지. `crop_image_vertical` operation 을 `ImageMaterializer._apply_crop_vertical` 에 추가. Alembic `026_cls_crop_image_params` 로 seed 갱신. 45건 테스트. ⚠️ horizontal crop / Jpeg Quality 조정은 이번 세트에서 제외.
14. ~~`cls_filter_by_class` 실구현 + `cls_remove_images_without_label` 통합 제거~~ ✅ **완료 (2026-04-20)** — 기존 stub 2종을 단일 노드로 통합. params 4필드: `head_name` (text) + `mode` (select include/exclude) + `classes` (textarea, any-match, 비우면 unknown 판정만 수행) + `include_unknown` (checkbox, `labels[head] is None` 도 매칭 대상). v1 match_policy 는 "any" 고정. §2-12 에 따라 `null`=unknown (토글 대상) / `[]`=explicit empty (match_policy 로만 판정) 구분 엄수. "label 없는 이미지 제거" 는 `mode=exclude, classes=[], include_unknown=True` 조합으로 완전 대체. 정적 검증은 `pipeline_service._validate_cls_filter_by_class_compatibility` 로 확장 — `cls_set_head_labels` compat 과 동일하게 `build_stub_source_meta + preview_head_schema_at_task` 로 상류 head_schema 를 시뮬레이션해 `FILTER_BY_CLASS_{CODE}` ERROR 수집. Alembic `027_cls_filter_by_class_unified` 로 params UPDATE + `cls_remove_images_without_label` row DELETE. 55건 테스트.
15. **Automation 실구현** — 정책 확정 대기 (lineage 조정 + minor 버전 증가 규약)
16. **미구현 Detection manipulator 2종** — `det_change_compression` / `det_shuffle_image_ids`
17. **버전 정책 운영 검증** — automation과 함께
18. **Phase 3** — TrainingExecutor/GPUResourceManager 인터페이스, 알림 골격, GNB/Manipulator/시스템 상태 페이지, 전체 UX 정리
19. **Step 2** 진입 — DockerTrainingExecutor, nvidia-smi 기반 GPUResourceManager, MLflow, Prometheus+DCGM, SMTP 알림
    - ⚠️ multi-label head 학습 시 unknown 을 loss mask 로 배제: §2-12 `null` 규약으로 head-level 가능. per-class 필요 시 옵션 A/B 확장
    - ⚠️ head 별 `loss_per_head: dict[str, Literal["softmax", "bce", "bce_ovr"]]` 실장 (§6-2 결정)
20. **Step 3 이후** — S3StorageClient, KubernetesTrainingExecutor, Helm, Argo/Kubeflow, Volcano, KEDA, MinIO
21. **Step 4** — Label Studio, Synthetic Data, Auto Labeling, Offline Testing, Auto Deploy, 데이터 자동 수집
    - ⚠️ auto-labeling 의 per-class unknown 시나리오는 현 head-level `null` 로 부분 해결 (head 전체 승격). 완전 해결은 옵션 A/B 확장 필요
22. **Step 5** — Generative Model MLOps

---

## 6. 방법론 메모

### 6-1. Classification 이미지 변형 시 파일명 rename 규약 (확정 · 2026-04-20 · v7.5)

v7.5 filename-identity 전환 (§2-13) 으로 이미지 identity 는 **filename** 으로 고정됐다. 이 규약 하에서
이미지 회전·crop·압축 변경 등 **바이너리를 변형하는 모든 classification manipulator** 가 따라야 할
공통 계약을 `cls_rotate_image` 실구현으로 확립했다 (핸드오프 021 §1-3). 이후 추가되는 이미지 변형
노드는 전부 이 규약을 따른다.

**1. Phase A (`transform_annotation`) 에서 반드시 해야 하는 3가지.**

- **파일명에 postfix 삽입.** 확장자 앞에 변형 종류를 식별하는 고정 문자열을 붙인다 — 경로 prefix 는
  유지하고 `os.path.splitext` 로 base/ext 를 분리해 `{base}{postfix}{ext}` 로 재조립. 예:
  - `cls_rotate_image`: `_rotated_{degrees}` → `images/truck_001.jpg` → `images/truck_001_rotated_180.jpg`
  - `cls_crop_image` (2026-04-20): `_crop_{up|down}_{pct:03d}` → `images/truck_001.jpg` → `images/truck_001_crop_up_030.jpg` — direction 은 Korean(`상단`/`하단`) 입력을 내부 English(`up`/`down`) 로 정규화해 ASCII 파일명을 유지, crop_pct 는 3자리 zero-pad
  - 같은 manipulator 를 같은 params 로 두 번 태우면 같은 파일명이 다시 나온다 (멱등). 이는 v7.5 의
    "같은 파일명 = 같은 내용" 불변식을 만족하는 의도된 동작.
- **src 복원 메타데이터를 `record.extra` 에 기록 (최초 1회만).**
  - `record.extra["source_storage_uri"]` = 입력 `DatasetMeta.storage_uri`
  - `record.extra["original_file_name"]` = rename 이전 파일명
  - **이미 값이 있으면 덮어쓰지 않는다** — `cls_merge_datasets` 가 prefix rename 과 함께 먼저
    채워뒀을 수 있고, 그 값이 진짜 원본 src 를 가리킨다. 덮어쓰면 추적 체인이 끊어져 Phase B 가
    src 를 찾을 수 없다.
- **`record.extra["image_manipulation_specs"]` 에 append.** 기존 배열이 있으면 그 뒤로 쌓는다.
  순서 = Phase B `ImageMaterializer` 적용 순서. operation 값은 prefix 없이 (`rotate_image`,
  `crop_image`) — detection / classification 이 동일 operation 을 공유한다 (§2-4).

**2. Phase B (`build_image_manipulation`) — ImageManipulationSpec 반환.**

`ImageMaterializer` 가 `source_storage_uri + original_file_name` 으로 src 를 읽어서 specs 순서대로
적용 후 `output_storage_uri + record.file_name` (postfix 가 붙은 새 이름) 으로 저장. rotate/crop/
compression 등 operation 별 적용 함수는 `lib/pipeline/image_materializer.py` 에 집약되어 있고,
기존 detection 경로에서 쓰던 구현을 그대로 쓴다 — manipulator 를 추가해도 materializer 코드는 보통
건드릴 필요 없다 (신규 operation 을 들일 때만 `_apply_*` 추가).

**3. 추가 강제 조건.**

- **head_schema / labels 는 건드리지 않는다** — classification 이미지 변형은 annotation 과 독립.
  label 을 바꾸는 동작이 필요하면 별도 annotation manipulator 를 쓴다.
- **list 입력 거부.** 이미지 변형 manipulator 는 단건 `DatasetMeta` 만 받는다. merge 와 의도를
  혼동하지 않기 위해 `isinstance(input_meta, list)` 일 때 `TypeError`.
- **deep copy 로 입력 격리.** `copy.deepcopy(input_meta)` 로 시작해 호출자의 원본을 보존.
- **90°/270° 회전 등 차원이 바뀌는 경우** `record.width ↔ record.height` 까지 직접 갱신. width/
  height 가 `None` 이면 swap 을 건너뛴다.

**왜 이렇게 설계했나.**

v7.4 까지 논의되던 "SHA 재계산 타이밍" 문제 (a/b/c 안) 는 §2-13 filename-identity 전환으로 원천
소멸했다 — SHA 자체를 보지 않으므로, 변형 결과의 hash 를 미리 알 필요가 없다. 대신 "내용이 바뀌면
파일명을 반드시 바꿔야 한다" 는 책임이 각 변형 manipulator 로 옮겨왔고, 그 책임을 유일한 장소
(`record.file_name` + `record.extra`) 에서 지역적으로 해결하도록 했다.

참조 구현: `backend/lib/manipulators/cls_rotate_image.py`, 테스트:
`backend/tests/test_cls_rotate_image.py` (25 케이스 — 각도별 동작, dim swap, labels 보존, specs
append, extra 최초/보존 분기, list 입력 거부, deep copy 격리).

### 6-2. Binary label type (결정 완료 · 2026-04-20 · v7.5)

현재 `HeadSchema.multi_label: bool` 로 single(softmax) vs multi(sigmoid) 를 구분하지만, **binary classification (BCEWithLogitsLoss)** 을 위한 별도 타입이 없다. `single-label + len(classes) == 2` head 는 softmax 2-way 로도, BCE binary 로도 학습 가능하므로 **데이터 schema 만으로는 의도를 구분할 수 없다**.

**결정: (c) 주 선택 + (b) 보조 — 학습 config 에서 head 별 loss 지정, 고도화 단계에서 schema 기반 auto-suggest + 사용자 검토 강제**

(a) `HeadSchema.label_type` 필드 추가 방식을 채택하지 않은 이유: 사용자가 최초 등록 시점에 binary 의도를 결정해 폴더 구조를 맞춰야 한다면 현재의 `<root>/<head>/<class>/<images>` 2레벨 규약(§2-8)으로 부족해지고, 같은 데이터로 softmax / BCE 양쪽 학습 실험을 해볼 수 없다. Schema migration 파급도 크다.

**(c) 기본 — 학습 config 에서 head 별 loss 명시 지정**
- `TrainingExecutor` config 에 `loss_per_head: dict[str, Literal["softmax", "bce", "bce_ovr"]]` 필드 신설 (Step 2 진입 시 실장).
- 데이터 schema (`head_schema.multi_label`) 는 그대로 유지 — loss 선택은 학습 관심사로 분리.
- 같은 head 에 서로 다른 loss 로 학습을 여러 번 돌릴 수 있다 (실험 유연성).

**(b) 보조 — 학습 config UI 에서 schema 기반 auto-suggest + 사용자 검토 강제**
- UI 가 `head_schema` 를 읽어 head 별 권장 loss 를 초기값으로 채운다.
- 추천 규칙:
  - `multi_label=True` → `bce` (multi-label sigmoid, 현 의미와 동일)
  - `multi_label=False, len(classes) == 2` → softmax / bce 둘 다 후보, **사용자 명시 선택 필수** (auto-save 금지)
  - `multi_label=False, len(classes) > 2` → `softmax` 기본, `bce_ovr` (OvR) 도 선택 가능
- "검토 완료" 를 사용자가 명시적으로 체크해야 학습 제출 가능 — 묵시 기본값으로 잘못된 loss 가 선택되는 위험을 차단.

**`len(classes) != 2` single-label head 에 `bce` 지정 시 정책**
- 단일 sigmoid (`bce`) 는 `len==2` 에서만 허용 — 그 외는 **명시 거부 (에러)**.
- 다중 class 를 OvR BCE 로 학습하려면 별도 값 `bce_ovr` 선택 — 의미 구분을 값 이름으로 강제.

**구현 위치와 타이밍**
- Step 2 진입 직전 (TrainingExecutor config schema 확정 단계) 에 실장.
- 현 Phase 2 / 3 에서는 결정만 기록하고 코드 변경 없음 (데이터 schema / manifest / manipulator 전부 불변).

**Step 2 설계 시 확정할 세부**
- auto-suggest 결과를 DB 에 영속시킬지, UI 휘발성으로 둘지
- per-class weight / class imbalance 대응을 loss 별로 어떻게 얹을지 (현 논의 범위 밖)

---

## 6. 핵심 파일 맵

### 6-1. lib/ (순수 로직, DB 무의존)

| 파일 | 역할 |
|------|------|
| `lib/pipeline/config.py` | `PipelineConfig` / `TaskConfig` / `OutputConfig` / `schema_version` / topological_order |
| `lib/pipeline/dag_executor.py` | `PipelineDagExecutor` — DAG 실행 + processing.log |
| `lib/pipeline/executor.py` | Phase A(annotation) + Phase B(이미지 실체화) |
| `lib/pipeline/image_executor.py` | 이미지 copy vs transform 분기 |
| `lib/pipeline/pipeline_validator.py` | 정적 검증 |
| `lib/pipeline/models.py` | DatasetMeta / Annotation / ImageRecord / ImagePlan |
| `lib/pipeline/io/` | COCO / YOLO 파서·라이터 |
| `lib/manipulators/__init__.py` | `MANIPULATOR_REGISTRY` — pkgutil 자동 발견 |
| `lib/manipulators/*.py` | 26종 UnitManipulator 구현 (det 12 실구현 + cls 14 실구현) |
| `lib/classification/ingest.py` | Classification ingest — filename 기반 identity + manifest.jsonl + head_schema.json + `FilenameCollision` 수집 (single-label head 내 파일명 충돌 skip) |
| `lib/classification/__init__.py` | `ingest_classification` / `ClassificationHeadInput` / `FilenameCollision` 등 export |

### 6-2. app/ (FastAPI + DB + Celery)

| 파일 | 역할 |
|------|------|
| `app/api/v1/pipelines/` | 파이프라인 API 라우터 |
| `app/services/pipeline_service.py` | DB 검증 + 실행 이력 |
| `app/tasks/pipeline_tasks.py` | Celery 태스크 |
| `app/tasks/register_classification_tasks.py` | Classification RAW 등록 Celery task + process.log / metadata 기록 |
| `app/services/dataset_service.py` | `register_classification_dataset` + `_diff_head_schema` / `_merge_head_schema` |
| `app/api/v1/dataset_groups/router.py` | `POST /register-classification` 엔드포인트 |
| `app/models/all_models.py` | 전체 ORM 모델 단일 파일 (`DatasetGroup.head_schema` JSONB 포함) |
| `migrations/versions/009_add_head_schema.py` | head_schema 컬럼 추가 마이그레이션 |

### 6-3. frontend/ — SDK 경로 중심

| 파일 | 역할 |
|------|------|
| `src/pipeline-sdk/types.ts` | `NodeDefinition` / `NodeDataByKind` / 기타 SDK 타입 |
| `src/pipeline-sdk/registry.ts` | `registerNodeDefinition` / `assertRegistryCompleteness` |
| `src/pipeline-sdk/bootstrap.ts` | 5종 definition 등록 진입점 |
| `src/pipeline-sdk/definitions/*Definition.tsx` | 5종 NodeKind 각자 정의 |
| `src/pipeline-sdk/engine/graphToConfig.ts` | graph → `PipelineConfig` |
| `src/pipeline-sdk/engine/configToGraph.ts` | `PipelineConfig` → graph (claim 기반 복원) |
| `src/pipeline-sdk/engine/clientValidation.ts` | 클라이언트 측 검증 |
| `src/pipeline-sdk/engine/issueMapping.ts` | 백엔드 issue → 노드 매핑 |
| `src/pipeline-sdk/hooks/useNodeData.ts` | store 직접 구독 훅 |
| `src/pipeline-sdk/components/NodeShell.tsx` | 공통 헤더/핸들/이슈 태그 |
| `src/pipeline-sdk/palette.ts` | `buildPaletteItems` — manipulator + 특수 노드 병합 |
| `src/pipeline-sdk/nodeTypes.ts` | `buildNodeTypesFromRegistry` — React Flow 연결 |
| `src/pipeline-sdk/styles.ts` | `CATEGORY_STYLE` / `MANIPULATOR_EMOJI` |
| `src/pages/PipelineEditorPage.tsx` | 에디터 오케스트레이션 (React Flow 배선) |
| `src/components/pipeline/PropertiesPanel.tsx` | `definition.PropertiesComponent` 위임 |
| `src/components/pipeline/NodePalette.tsx` | `buildPaletteItems` 소비 |
| `src/stores/pipelineEditorStore.ts` | `nodeDataMap` / `distributeIssuesToNodes` |

---

## 7. 작업 시 준수 원칙

### 7-1. 아키텍처
- `lib/` → `app/` import 금지. SDK는 프론트 전담
- 동일 의도 중복 코드 금지 — 존재하면 통합

### 7-2. 네이밍 / 스타일
- 함수·변수명 한 글자 / 한 단어 금지. 서술형 풀네임
- manipulator 이름: 동작 대상 + 조건을 모두 포함하는 snake_case
- 주석은 한글로 충실하게 (반년 뒤의 나는 다른 사람)

### 7-3. GUI
- 노드 타입별 하드코딩 금지 — 모든 분기는 `NodeDefinition`으로
- NodeComponent는 `useNodeData(nodeId)` 훅만 사용. React Flow `data` prop 직접 참조 금지
- Merge 외 노드는 입력 엣지 1개 강제 유지

### 7-4. 통일포맷
- 내부는 `category_name: str` 유지. 포맷별 integer ID는 IO 경계에서만

### 7-5. 비동기
- API는 async, Celery는 sync. 혼용 금지. 마이그레이션은 sync

### 7-6. 노드 SDK
- 새 manipulator / NodeKind 추가 전 **반드시 `docs/pipeline-node-sdk-guide.md` 통독**
- `assertRegistryCompleteness` 실패를 회피하려 완화하지 말 것 — 의도된 감시점
- `schema_version` 변경은 `CURRENT_SCHEMA_VERSION` 상수 + `matchFromConfig` 분기를 세트로

### 7-7. 커밋
- 사용자가 명시적으로 요청한 경우에만 커밋 — 자동 커밋 금지
