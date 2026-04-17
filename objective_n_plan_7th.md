# 데이터 관리 & 학습 자동화 플랫폼 — 7차 설계서

> **작업지시서 v7.5** | cls 강등+샘플링 실구현 완료, 이미지 변형/Annotation 조작/Head 추가/Binary type 방법론 TODO 추가
> 기준일: 2026-04-17
> 이전 설계서: `docs_history/objective_n_plan_6th.md`
> 통합 핸드오프: `docs_for_claude/019-null-unknown-convention-handoff.md` (이전 018은 `docs_history/handoffs/`)
> 노드 SDK 규약: `docs/pipeline-node-sdk-guide.md` (2026-04-15 재작성본)

6차 설계서의 §7-1 최우선 액션(노드 SDK화 + 가이드)이 완료되어 baseline에 편입됐다.
v7.2 에서 Classification DAG + Celery runner + manipulator prefix 통일(det_/cls_)이 baseline 에 들어갔고,
v7.3 에서 `cls_merge_datasets` 실구현과 3125장 드롭 버그 수정 과정에서 드러난
image-level `unknown` 라벨 규약 갭을 §2-12 로 명문화했으며,
v7.4 에서 `null` = unknown / `[]` = explicit empty 규약을 확정했다 (§2-12).
**v7.5 에서 cls_demote_head_to_single_label + cls_sample_n_images 실구현을 완료**하고,
이미지 변형·Annotation 조작·Head 추가 등 신규 노드 TODO 와 SHA/Binary 방법론 메모를 §5·§6 에 추가했다.

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

### 2-4. MANIPULATOR_REGISTRY — 자동 발견 (23종: det 12 실구현 + cls 9 실구현 + cls 2 stub)

- `lib/manipulators/__init__.py`가 `pkgutil.iter_modules`로 하위 모듈 순회, `UnitManipulator` 구체 서브클래스를 자동 수집
- 인스턴스 `.name` property를 키로 사용. 중복 name 즉시 RuntimeError (seed 정합성 보호)
- 새 manipulator 추가 = **파일 1개 + seed 1건**. 레지스트리 수정 불요
- **네이밍 prefix 규약**: detection = `det_`, classification = `cls_`. prefix 는 `manipulator.name` 에만 붙고 `ImageManipulationSpec.operation` 문자열에는 **절대 붙이지 않음** (operator vs operation 별개 namespace).

**Detection 12종 (`det_` prefix, 전부 실구현 완료):**
- `det_format_convert_to_coco` / `det_format_convert_to_yolo` / `det_format_convert_visdrone_to_coco` / `det_format_convert_visdrone_to_yolo`
- `det_merge_datasets`
- `det_filter_keep_images_containing_class_name` / `det_filter_remove_images_containing_class_name` / `det_filter_remain_selected_class_names_only_in_annotation`
- `det_remap_class_name` / `det_rotate_image` / `det_mask_region_by_class` / `det_sample_n_images`

**Classification 10종 (`cls_` prefix):**
- ✅ 실구현 완료 9종: `cls_rename_head`, `cls_rename_class`, `cls_reorder_heads`, `cls_reorder_classes`, `cls_select_heads`, `cls_merge_datasets` (`accepts_multi_input=True`, §2-11), `cls_merge_classes` (head 내 class 병합), `cls_demote_head_to_single_label` (multi→single 강등), `cls_sample_n_images` (N장 랜덤 샘플)
- 🚧 stub 2종: `cls_filter_by_class`, `cls_remove_images_without_label`

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

### 2-8. Classification 등록 (구현 완료 · 2026-04-14)

RAW Classification 데이터셋 등록을 Detection과 분리된 전용 흐름으로 구현. **end-to-end 테스트 완료**.

**폴더 입력 규약 (사용자 준비)**
- `<root>/<head>/<class>/<images>` 2레벨 고정. LOCAL_UPLOAD_BASE에 준비 후 GUI로 split별 1회 등록
- `has_subdirs=true` (2레벨 초과) → **등록 차단**
- 빈 class 폴더(image_count=0) 허용 — 정식 class로 간주
- class 없는 head(classes=0) → warning (한 단계 아래를 루트로 잘못 선택한 경우)

**디스크 레이아웃 (LOCAL_STORAGE_BASE 하위)**
- 평면 `images/{sha1}.{원본확장자}` (샤딩 없음)
- `manifest.jsonl` — 이미지 1장 = 1줄
- `head_schema.json` — DB `DatasetGroup.head_schema` 복사본 (오프라인 학습용)
- 실패 시 `process.log` 보존 (dest_root 자체는 남기고 자식만 정리)

**Manifest 한 줄 스키마 (labels: `dict[str, list[str] | None]`, §2-12 확정)**
```json
{"sha":"ab12...","filename":"images/ab12...jpg",
 "original_filename":"img_0001.jpg",
 "labels":{"hardhat_wear":["helmet"],"visibility":null}}
```
- `["helmet"]` = known label, `null` = unknown (학습 제외), `[]` = explicit empty (전부 neg, multi-label 전용)

**DB 스키마 — 공유 테이블 + 확장 컬럼**
- `DatasetGroup`/`Dataset` 공유. classification 전용 테이블 만들지 않음 (lineage/pipeline/solution FK 호환)
- `DatasetGroup.head_schema JSONB` 신규 (migration 009, classification만 사용 — detection은 NULL):
  ```json
  {"heads":[{"name":"hardhat_wear","multi_label":false,"classes":["no_helmet","helmet"]}]}
  ```
- `AnnotationFormat` enum: **`CLS_MANIFEST` 신규, `CLS_FOLDER` 제거**
- `Dataset.class_count` int는 **detection 전용**. classification은 NULL 유지
- `Dataset.metadata.class_info`: classification에서는 head 배열 + `skipped_conflicts` + `intra_class_duplicates` 상세 저장

**head_schema 일관성 (동일 그룹 신규 버전 등록 시)**
- 기존 head의 classes **순서 변경/삭제 금지** (학습 index 계약 — `_diff_head_schema`에서 차단)
- 기존 head `multi_label` 변경 금지
- 신규 head 추가 → warning `NEW_HEAD` 후 허용
- 기존 head에 classes append (prefix 보존) → warning `NEW_CLASS` 후 허용 (사용자 책임)

**중복 이미지 정책 (SHA-1 기반 · 내용 동일하면 파일명 달라도 같은 이미지)**
- single-label head에서 동일 SHA가 여러 class에 존재하면 충돌
  - **FAIL (기본)**: `DuplicateConflictError` → 등록 중단, process.log에 양쪽 occurrence 전체 기록
  - **SKIP**: 충돌 이미지를 **양쪽 모두에서 제외**하고 진행, process.log + metadata.class_info.skipped_conflicts에 상세
- 같은 (head, class) 폴더 내 동일 SHA 중복 → `intra_class_duplicates` 경고 (pool에는 첫 파일만 저장, 나머지 파일명은 process.log에 보존)
- `ImageOccurrence`: `(head_name, class_name, original_filename, source_abs_path)` — 파일명이 양쪽에서 달라도 추적 가능

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

**남은 작업 → §5: 잔여 stub 2종 실구현 + 신규 노드 4종 (이미지 변형/Annotation 필터/Head 추가/Annotation 일괄 변경)**

### 2-11. Classification merge 정책 (설계 확정 + 실구현 완료 · 2026-04-16)

`cls_merge_datasets` 구현 전에 확정한 다중 입력 병합 정책.

**대원칙**: "학습에 영향을 줄 수 있는 것은 사용자에게 맡긴다." 시스템이 의미를 추정할 수 없는 충돌은 옵션을 주지 않고 warning 으로 맞춰 오도록 차단한다. 의미가 명확하지만 편의상 자동 처리가 가능한 충돌만 옵션화한다.

#### 2-11-1. 노드 인터페이스

- **Multi-input**: 2개 이상 (N-way merge 허용). 결정론은 **graph edge 순서** 로 확보.
- **선행 manipulator 체인 유도**: strict 기본값을 통해 `cls_rename_head` / `cls_rename_class` / `cls_reorder_heads` / `cls_reorder_classes` 로 스키마를 맞춘 뒤 merge 하도록 자연스럽게 유도.

```python
cls_merge_datasets params:
  on_head_mismatch:      "error" (default) | "fill_empty"
  on_class_set_mismatch: "error" (default) | "multi_label_union"
  on_label_conflict:     "drop_image" (default) | "merge_if_compatible"
```

#### 2-11-2. 정적 검증 (FE primary + BE secondary)

Head/class 스키마는 DatasetGroup 에 이미 저장되어 있어 실행 전에 비교 가능.

**역할 분리:**
- **FE (1차 차단기 + UX)**: 에디터 `validate()` 에서 입력 head_schema 비교, 문제 노드 하이라이트 + "어떤 선행 manipulator 를 쓰라" 구체 가이드 + 실행 버튼 비활성화.
- **BE (최종 안전망)**: API 우회 / 자동화 스크립트 대비. `cls_merge_datasets` manipulator 진입 시 `raise ValueError(f"head 이름 불일치: {a} vs {b}")` 수준의 단순 assert. 정상 흐름에선 안 걸리므로 메시지 품질에 시간 쓰지 않음.

BE 검증을 생략하면 안 되는 이유: 9개 충돌 중 **4개 (head 이름/순서, class 이름/순서) 는 자연 에러 없이 silent 로 오염된 데이터가 생성**된다. Dataset + lineage 엣지까지 박힌 뒤 발견되면 rollback 비용이 크다.

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

#### 2-11-5. `on_label_conflict` — 런타임 (SHA dedup 후 동일 이미지에 복수 라벨)

SHA 로 dedup 된 후 동일 이미지에 대해 입력별 labels 가 존재한다. 이 시점의 충돌 판정 규칙:

**`drop_image` (default)**
- 라벨 불일치 시 해당 이미지를 결과에서 제외
- 로그: 이미지 SHA, 각 source dataset_id, 각 측 labels 전체, 폐기 사유

**`merge_if_compatible`**
- Single-label head 에서 값이 다르면 **무조건 폐기** (union 불가)
  - 한쪽 또는 양쪽의 `labels[head]` 가 `null` (unknown) 이면 충돌 판정에서 제외한다. `fill_empty` 로 추가된 head 는 `null` 로 저장되므로 (§2-12) 자연스럽게 unknown 처리됨.
- Multi-label head 는 class 별로 3-값 상태를 판정:
  - `null` (head-level unknown): `labels[head]` 가 `null` 이면 해당 입력의 모든 class 가 unknown — 충돌 판정에서 제외 (§2-12 확정 규약)
  - `pos`: `labels[head]` 가 리스트이고 해당 class 가 포함됨
  - `explicit_neg`: `labels[head]` 가 리스트이고 해당 class 가 포함되지 않음 (head.classes 에는 있으므로 명시적 부정)
  - dataset-level unknown: 해당 측 `classes` 에 class 가 **애초에 없었음** — `DatasetMeta.head_schema[i].classes` 로 판정
- `pos` vs `explicit_neg` 상충 있으면 폐기, 나머지는 union (`pos` vs `unknown`, `explicit_neg` vs `unknown` 허용)

**예시** (multi_label head `color`, `on_class_set_mismatch=multi_label_union`)
- A.classes=[blue,red,black], A.labels[color]=[red]
- B.classes=[blue,red], B.labels[color]=[blue]
- A 기준: red=pos, blue=explicit_neg, black=explicit_neg
- B 기준: blue=pos, red=explicit_neg
- red, blue 모두 `pos` ↔ `explicit_neg` 상충 → 폐기

**`pos` ↔ `neg` 상충을 판정하려면 각 입력의 원본 `classes` 집합을 살려야 하는데**, 이는 `DatasetMeta.head_schema[i].classes` 에 정상적으로 유지됨 (`manifest_io.py:86-92` 로드, `178-187` 저장 확인). 추가 정보 보존 불요.

#### 2-11-6. 이미지 / 파일명 / Split

| 시나리오 | 처리 |
|---|---|
| SHA 동일 | 동일 이미지 — dedup |
| SHA 다름, 시각적으로 동일 (re-encode/resize) | 다른 이미지 취급 — 검출 불가 |
| file_name 충돌, SHA 다름 | **suffix 부여 + 로그** (어느 dataset 의 어떤 이미지가 어떻게 rename 됐는지) |
| file_name 충돌, SHA 동일 | SHA dedup 으로 자연 해결 |
| Split 교차 merge (train + val) | **허용** — DAG 정합성 체크는 이후 과제 |

#### 2-11-7. 결과 head / class 순서

- Head / class 집합과 순서가 모든 입력에서 동일하면 **입력 A 순서 유지**
- 변경 필요 시: A 순서 → (B − A) 추가 → (C − B − A) 추가 (edge 순서 기준)

#### 2-11-8. 로깅

저장 위치는 **`processing.log` 단일 경로**. 별도 merge_report.json 같은 구조화 파일은 만들지 않는다 (로그 경로가 여러 곳이면 조회가 번잡해짐. 필요 시 후행 개선).

기록 내용:
- 이미지 폐기 내역: SHA + source dataset_id + 각 측 labels + 사유
- file_name rename 내역: 원본 → rename 결과 + source dataset_id
- 스키마 승격 내역: `multi_label_union` 으로 single → multi 승격된 head 이름
- 마지막에 summary 한 줄: `cls_merge_datasets: dropped=N, renamed=M, promoted=K heads`

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
10. **잔여 Classification operator 실구현 (stub 2종)**
    - `cls_filter_by_class` — 특정 class 포함/미포함 이미지 필터
    - `cls_remove_images_without_label` — unknown(`null`) 이미지 제거
11. **Classification 이미지 변형 노드 (신규)**
    - `cls_crop_image` — 이미지 상하 Crop (상단 N%, 하단 M% 잘라 저장). SHA 재계산 + file_name 갱신 필요
    - `cls_rotate_image` — 이미지 회전. det_rotate_image 와 동일 로직, classification 자료구조 대응
    - ⚠️ Jpeg Quality 조정은 포함하지 않음
    - ⚠️ 이미지 변형 시 SHA 변경 문제 — §6-1 방법론 참조
12. **Classification Annotation 기반 이미지 필터 (신규)**
    - 특정 head 의 특정 class 값 조건으로 이미지 필터링 (예: `visible` head 에서 `0_seen` 인 이미지만 유지)
    - `cls_filter_by_class` 의 확장 또는 별도 노드로 구현
13. **Classification Head 추가 노드 (신규)**
    - `cls_add_head` — 기존 데이터셋에 새 head 를 추가. 추가할 head 이름, 가능한 class candidate 목록을 params 로 수신
    - 기존 이미지의 신규 head labels 는 `null` (unknown, §2-12)
14. **Classification Annotation 일괄 변경 노드 (신규)**
    - 특정 head 의 labels 를 일괄적으로 특정 값으로 설정 (예: `visible` head 를 전부 `null`(unknown) 으로 설정)
    - head 전체 unknown 화, 특정 class 로 일괄 설정 등
15. **Automation 실구현** — 정책 확정 대기 (lineage 조정 + minor 버전 증가 규약)
16. **미구현 Detection manipulator 2종** — `det_change_compression` / `det_shuffle_image_ids`
17. **버전 정책 운영 검증** — automation과 함께
18. **Phase 3** — TrainingExecutor/GPUResourceManager 인터페이스, 알림 골격, GNB/Manipulator/시스템 상태 페이지, 전체 UX 정리
19. **Step 2** 진입 — DockerTrainingExecutor, nvidia-smi 기반 GPUResourceManager, MLflow, Prometheus+DCGM, SMTP 알림
    - ⚠️ multi-label head 학습 시 unknown 을 loss mask 로 배제: §2-12 `null` 규약으로 head-level 가능. per-class 필요 시 옵션 A/B 확장
20. **Step 3 이후** — S3StorageClient, KubernetesTrainingExecutor, Helm, Argo/Kubeflow, Volcano, KEDA, MinIO
21. **Step 4** — Label Studio, Synthetic Data, Auto Labeling, Offline Testing, Auto Deploy, 데이터 자동 수집
    - ⚠️ auto-labeling 의 per-class unknown 시나리오는 현 head-level `null` 로 부분 해결 (head 전체 승격). 완전 해결은 옵션 A/B 확장 필요
22. **Step 5** — Generative Model MLOps

---

## 6. 방법론 메모 (미해결)

### 6-1. Classification 이미지 변형 시 SHA 문제

이미지 회전, crop 등 바이너리 변형이 일어나면 SHA-1 이 변경된다.

**문제 1 — 사전 SHA 계산**: `imsave` 전에 SHA 를 먼저 알아야 manifest.jsonl 작성이 가능. 현재 detection 경로는 file_name 기반이라 SHA 불요하지만, classification 은 `images/{sha}.{ext}` 규약이므로 Phase A(annotation) 에서 SHA 를 결정해야 한다. 가능한 접근:
  - (a) Phase A 에서 in-memory 변환 후 SHA 계산 → manifest 작성 → Phase B 에서 동일 변환 재실행 + 파일 저장. 변환이 결정론적이면 SHA 일치 보장. CPU 비용 2배.
  - (b) Phase A 에서 placeholder SHA 사용 → Phase B 에서 실제 변환 + SHA 계산 → manifest 사후 패치. IO 2회 발생.
  - (c) Phase A/B 통합 — 이미지 변형 manipulator 는 Phase A 에서 바로 파일까지 생성. 현재 아키텍처 변경 필요.

**문제 2 — split 후 merge 시 중복**: 한 이미지를 두 갈래로 분기(예: split → 각각 다른 변형 → merge)하면 동일 원본에서 파생된 서로 다른 변형 이미지가 생성된다. SHA 가 다르므로 dedup 되지 않고 양쪽 모두 저장됨. 이는 의도된 동작일 수 있으나 (변형이 다르므로 다른 이미지), 동일 변형이 적용된 경우에는 불필요한 중복 → SHA dedup 으로 자연 해결.

### 6-2. Single / Multi 외 Binary label type 필요성

현재 `HeadSchema.multi_label: bool` 로 single(softmax) vs multi(sigmoid) 를 구분하지만, **binary classification (BCEWithLogitsLoss)** 을 위한 별도 타입이 없다.

**문제**: binary 는 class 가 정확히 2개인 single-label head 에서 BCEWithLogitsLoss 를 쓰려면 학습 시작 전에 "이 head 는 binary" 라는 정보가 필요하다.

**가능한 접근**:
  - (a) `HeadSchema` 에 `label_type: "single" | "multi" | "binary"` 필드 추가. 명시적이지만 schema 변경 파급이 큼.
  - (b) 학습 시작 단계에서 single-label + `len(classes) == 2` 를 자동 감지하여 binary 로 처리. 2 가 아니면 "manipulation 으로 class 를 2개로 맞추세요" 강제. schema 변경 불요, 규약 기반.
  - (c) 학습 config 에서 head 별 loss function 을 명시적으로 지정. 데이터 schema 와 학습 설정을 분리.

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
| `lib/manipulators/*.py` | 23종 UnitManipulator 구현 (det 12 실구현 + cls 9 실구현 + cls 2 stub) |
| `lib/classification/ingest.py` | Classification ingest — SHA-1 dedup + manifest.jsonl + head_schema.json + occurrence/intra-class dup 수집 |
| `lib/classification/__init__.py` | `ingest_classification` / `ClassificationHeadInput` / `DuplicateConflict` / `IntraClassDuplicate` 등 export |

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
