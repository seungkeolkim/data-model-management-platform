# 데이터 관리 & 학습 자동화 플랫폼 — 7차 설계서

> **작업지시서 v7.1** | Classification 뷰어 UI 분화 + 그룹 목록 필터·정렬 개편 반영 baseline
> 기준일: 2026-04-15
> 이전 설계서: `docs_history/objective_n_plan_6th.md`
> 통합 핸드오프: `docs_for_claude/016-group-list-enhance-handoff.md` (이전: 015는 `docs_history/handoffs/`)
> 노드 SDK 규약: `docs/pipeline-node-sdk-guide.md` (사람용 가이드)

6차 설계서의 §7-1 최우선 액션(노드 SDK화 + 가이드)이 완료되어 baseline에 편입됐다. 7차는 **그 결과를 포함한 현재 스냅샷**과 **남은 Step 1 마무리 / Step 2 진입 준비**를 정리한다.

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

### 2-4. MANIPULATOR_REGISTRY — 자동 발견 (12종)

- `lib/manipulators/__init__.py`가 `pkgutil.iter_modules`로 하위 모듈 순회, `UnitManipulator` 구체 서브클래스를 자동 수집
- 인스턴스 `.name` property를 키로 사용. 중복 name 즉시 RuntimeError (seed 정합성 보호)
- 새 manipulator 추가 = **파일 1개 + seed 1건**. 레지스트리 수정 불요

**현재 12종:**
- `format_convert_to_coco` / `format_convert_to_yolo` / `format_convert_from_coco` / `format_convert_from_yolo` (no-op — 통일포맷 도입 후 의미만 유지)
- `merge_datasets`
- `filter_keep_images_containing_class_name` / `filter_remove_images_containing_class_name` / `filter_remain_selected_class_names_only_in_annotation`
- `remap_class_name` / `rotate_image` / `mask_region_by_class` / `sample_n_images`

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

**Manifest 한 줄 스키마 (labels는 항상 list)**
```json
{"sha":"ab12...","filename":"images/ab12...jpg",
 "original_filename":"img_0001.jpg",
 "labels":{"hardhat_wear":["helmet"],"visibility":["seen"]}}
```

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

016 핸드오프 §3과 동일. 여기서는 요약만 둔다.

1. ~~Classification 데이터 입력~~ ✅ **완료 (2026-04-14)**
2. ~~Display / UI 분화 (상세 뷰어 + 목록 필터/정렬)~~ ✅ **완료 (2026-04-15)**
3. **Classification DAG 파이프라인 + 데이터 업로드/저장 정합성** [1순위 — 다음 세션 주제]
   - `CLS_MANIFEST` IO 파서/라이터를 `lib/pipeline/io/` 에 추가
   - Classification 전용 manipulator (augment/filter/remap/split) 도입
   - 파이프라인 executor 가 Detection + Classification 양쪽 DAG 를 동일 SDK 로 실행
   - 업로드/등록 경로의 정합성 강화: SHA-1 기반 중복 정책, head_schema 검증, manifest 무결성, storage_uri 레이아웃 실측 검증
4. **Automation 실구현** — 정책 확정 대기 (lineage 조정 + minor 버전 증가 규약)
5. **미구현 manipulator 2종** — `change_compression` / `shuffle_image_ids` (detection용)
6. **버전 정책 운영 검증** — automation과 함께
7. **Phase 3** — TrainingExecutor/GPUResourceManager 인터페이스, 알림 골격, GNB/Manipulator/시스템 상태 페이지, 전체 UX 정리
8. **Step 2** 진입 — DockerTrainingExecutor, nvidia-smi 기반 GPUResourceManager, MLflow, Prometheus+DCGM, SMTP 알림
9. **Step 3 이후** — S3StorageClient, KubernetesTrainingExecutor, Helm, Argo/Kubeflow, Volcano, KEDA, MinIO
10. **Step 4** — Label Studio, Synthetic Data, Auto Labeling, Offline Testing, Auto Deploy, 데이터 자동 수집
11. **Step 5** — Generative Model MLOps

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
| `lib/manipulators/*.py` | 12종 UnitManipulator 구현 |
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
