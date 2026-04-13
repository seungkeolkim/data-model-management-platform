# 데이터 관리 & 학습 자동화 플랫폼 — 7차 설계서

> **작업지시서 v7.0** | 파이프라인 노드 SDK 완성 직후 baseline
> 기준일: 2026-04-13
> 이전 설계서: `docs_history/objective_n_plan_6th.md`
> 통합 핸드오프: `docs_for_claude/014-node-sdk-complete-handoff.md`
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

### 2-8. 노드 SDK 불변식 (절대 준수)

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

014 핸드오프 §3과 동일. 중복을 피하기 위해 여기서는 요약만 둔다.

1. **Classification 데이터 입력** — Detection 전용 해소
2. **Automation 실구현** — 템플릿 + downstream 탐색 + minor 증가
3. **미구현 manipulator 2종** — `change_compression` / `shuffle_image_ids`
4. **버전 정책 운영 검증** — automation과 함께
5. **Phase 3** — TrainingExecutor/GPUResourceManager 인터페이스, 알림 골격, GNB/Manipulator/시스템 상태 페이지, 전체 UX 정리
6. **Step 2** 진입 — DockerTrainingExecutor, nvidia-smi 기반 GPUResourceManager, MLflow, Prometheus+DCGM, SMTP 알림
7. **Step 3 이후** — S3StorageClient, KubernetesTrainingExecutor, Helm, Argo/Kubeflow, Volcano, KEDA, MinIO
8. **Step 4** — Label Studio, Synthetic Data, Auto Labeling, Offline Testing, Auto Deploy, 데이터 자동 수집
9. **Step 5** — Generative Model MLOps

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

### 6-2. app/ (FastAPI + DB + Celery)

| 파일 | 역할 |
|------|------|
| `app/api/v1/pipelines/` | 파이프라인 API 라우터 |
| `app/services/pipeline_service.py` | DB 검증 + 실행 이력 |
| `app/tasks/pipeline_tasks.py` | Celery 태스크 |
| `app/models/all_models.py` | 전체 ORM 모델 단일 파일 |

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
