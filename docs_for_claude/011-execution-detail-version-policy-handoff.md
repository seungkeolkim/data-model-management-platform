# 파이프라인 실행 상세 Drawer + 버전 정책 변경 + 출력 그룹 task_types 자동 설정 -- 핸드오프

> 브랜치: `feature/data-manipulate-pipeline-gui-detection-as`
> 작업 기간: 2026-04-09 ~ 2026-04-10
> 이전 핸드오프: `010-unified-format-migration-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. 파이프라인 실행 상세 Drawer + Config JSON 재사용 기능

파이프라인 실행 이력 행 클릭 시 Drawer로 상세 정보를 표시하고, Config JSON을 복사하여 에디터에서 DAG를 복원할 수 있게 했다.

#### 1-1. JSON 기반 DAG 복원 (에디터 → "JSON 불러오기")

PipelineConfig JSON을 에디터에 붙여넣으면 원래 DAG 구조를 복원한다.

| 파일 | 변경 |
|------|------|
| `frontend/src/utils/pipelineConverter.ts` | `pipelineConfigToGraph()`, `extractSourceDatasetIdsFromConfig()`, `_applyAutoLayout()` 추가 |
| `frontend/src/components/pipeline/EditorToolbar.tsx` | "JSON 불러오기" 버튼 추가 |
| `frontend/src/pages/PipelineEditorPage.tsx` | JSON load 모달 + 비동기 복원 로직 (manipulator/dataset API 조회 → 그래프 변환) |

**복원 과정:**
1. JSON 파싱 → `extractSourceDatasetIdsFromConfig()`로 소스 데이터셋 ID 추출
2. `manipulatorsApi.list()` + `datasetsApi.get()` + `datasetGroupsApi.get()`으로 메타데이터 조회
3. `pipelineConfigToGraph()`로 React Flow 노드/엣지 생성
4. `_applyAutoLayout()`으로 topological sort 기반 자동 배치 (HORIZONTAL_GAP=320, VERTICAL_GAP=160)

#### 1-2. Config JSON 확인 모달 (Drawer 내)

실행 상세 Drawer에서 "Config JSON 확인" 버튼으로 모달을 열어 JSON을 확인/복사할 수 있다.

**clipboard 복사:**
- `navigator.clipboard.writeText()` 우선 시도
- HTTP + 비localhost 환경에서는 `document.execCommand('copy')` textarea fallback 사용
- 모달 내 `<pre userSelect="all">` 블록으로 수동 선택 복사도 가능

#### 1-3. 출력 데이터셋 버전 표시

Drawer "출력 설정" 섹션에 버전 항목 추가.

| 파일 | 변경 |
|------|------|
| `backend/app/schemas/pipeline.py` | `PipelineExecutionResponse`에 `output_dataset_version`, `output_dataset_group_id` 추가 |
| `backend/app/api/v1/pipelines/router.py` | `_build_execution_response()`에서 output_dataset 관계로부터 추출 |
| `frontend/src/types/pipeline.ts` | `PipelineExecutionResponse` 타입에 필드 추가 |

#### 1-4. 출력 데이터셋 링크 수정

"데이터셋 보기" 링크가 `/datasets?highlight=<id>` 대신 `/datasets/<group_id>/<dataset_id>` (실제 상세 페이지)로 이동하도록 수정.

#### 1-5. 데이터셋 상세에 생성 Pipeline ID 표시

| 파일 | 변경 |
|------|------|
| `backend/app/models/all_models.py` | Dataset 모델에 `@property pipeline_execution_id` 추가 |
| `backend/app/schemas/dataset.py` | `DatasetSummary`, `DatasetResponse`에 `pipeline_execution_id` 추가 |
| `backend/app/services/dataset_service.py` | `selectinload(Dataset.pipeline_executions)` 추가 (lazy loading 방지) |
| `frontend/src/types/dataset.ts` | `DatasetSummary`에 `pipeline_execution_id` 추가 |
| `frontend/src/pages/DatasetViewerPage.tsx` | "생성 Pipeline" 항목 추가, `copyable={{ text: fullId }}` |

### 2. ExecutionDetailDrawer 공유 컴포넌트 추출

PipelineHistoryPage에 인라인되어 있던 Drawer 코드(~400줄)를 공유 컴포넌트로 분리.

| 파일 | 역할 |
|------|------|
| `frontend/src/components/pipeline/ExecutionDetailDrawer.tsx` | **신규** — 재사용 가능한 실행 상세 Drawer |
| `frontend/src/pages/PipelineHistoryPage.tsx` | 인라인 Drawer 제거, import로 교체 |
| `frontend/src/pages/DatasetViewerPage.tsx` | 생성 Pipeline 클릭 시 Drawer 직접 오픈 |

**Props:**
```typescript
{
  execution: PipelineExecutionResponse | null  // null이면 Drawer 닫힘
  onClose: () => void
  onNavigateToDataset?: (groupId: string, datasetId: string) => void  // optional
}
```

- `onNavigateToDataset` 미전달 시 "출력 데이터셋" 행이 숨겨짐 (데이터셋 상세에서 자기 자신으로의 순환 링크 방지)
- 데이터셋 상세에서는 `pipelinesApi.getStatus(executionId)`로 실행 정보를 가져와 Drawer를 직접 연다

### 3. 버전 정책 변경: v{major}.{minor}.{patch} → {major}.{minor}

3단계 semver를 2단계 버전 정책으로 변경.

| 구분 | 이전 | 이후 |
|------|------|------|
| 형식 | `v1.0.0`, `v1.0.1`, `v1.0.2` | `1.0`, `2.0`, `3.0` |
| major 증가 | - | 사용자가 명시적으로 파이프라인 실행 |
| minor 증가 | - | 향후 automation이 자동 실행 (미구현) |
| patch 증가 | 매 등록/실행 시 | 삭제 |

**변경 파일:**

| 파일 | 변경 |
|------|------|
| `backend/app/services/dataset_service.py` | `_next_version()` — `v1.0.0` → `1.0`, major+1 반환 |
| `backend/app/services/pipeline_service.py` | `_next_version()` — 동일 |
| `backend/app/schemas/dataset.py` | version 필드 description 업데이트 |
| `backend/migrations/versions/007_migrate_version_format.py` | 기존 DB 데이터 마이그레이션 (group+split별 순번 재부여) |
| `frontend/src/components/dataset/DatasetRegisterModal.tsx` | 기본 버전 `v1.0.0` → `1.0` (6개소) |

**마이그레이션 로직:**
- group_id + split 그룹 단위로 created_at 오름차순 정렬
- 순번에 따라 `1.0`, `2.0`, `3.0` ... 재부여

### 4. 데이터셋 등록 안내 메시지에 버전 경로 표시

등록 완료 모달에 복사 대상 경로를 `raw/그룹명/split/버전` 형태로 표시.

| 이전 | 이후 |
|------|------|
| `raw/coco2017/train/` | `raw/coco2017/train/1.0` |

### 5. 파이프라인 출력 그룹 task_types 자동 설정

파이프라인 실행 시 출력 DatasetGroup의 `task_types`를 소스 데이터셋 그룹들의 교집합으로 자동 설정.

| 파일 | 변경 |
|------|------|
| `backend/app/services/pipeline_service.py` | `_intersect_source_task_types()` 신규, `_find_or_create_dataset_group()`에 `task_types` 파라미터 추가 |

**로직:**
1. config의 모든 태스크에서 `source:<dataset_id>` 참조를 수집
2. 각 소스 데이터셋의 그룹에서 `task_types` 조회
3. 교집합 계산 (하나라도 None이면 해당 그룹은 건너뜀)
4. 신규 그룹 생성 시 교집합 적용 / 기존 그룹에 task_types가 없으면 자동 채움

---

## 커밋 이력

| 커밋 | 내용 |
|------|------|
| `1240162` | 파이프라인 실행 상세 Drawer + 태스크별 진행 추적 + JSON 기반 DAG 복원 |
| `4fe040f` | 파이프라인 실행 상세에 출력 데이터셋 버전 표시 |
| `7020941` | 파이프라인 상세 '데이터셋 보기' 링크가 실제 데이터셋 상세 페이지로 이동하도록 수정 |
| `38d43b8` | 데이터셋 상세에 생성 Pipeline ID 표시 + 목록 조회 lazy loading 수정 |
| `10e3d8c` | ExecutionDetailDrawer 공유 컴포넌트 추출 + 데이터셋 상세에서 Drawer 직접 열기 |

버전 정책 변경 + task_types 자동 설정은 아직 미커밋 상태.

---

## 다음 세션 작업: DAG 정합성 검증

### 검토 필요 사항

1. **DB 의존 vs Logical Plan 단계 검증**
   - 현재 `validate_pipeline_config_static()` (lib/)은 DB 없이 정적 검증만 수행
   - `pipeline_service.py`에서 DB 조회 후 소스 데이터셋 존재/상태 검증
   - **질문**: execution 모델(DB)이 검증에 더 필요한가, 아니면 JSON(logical plan) 단계에서 execute 가능 여부를 충분히 판단할 수 있는가?

2. **중간 노드의 output 산출물 타입 추론**
   - 현재 중간 노드의 출력 타입(annotation_format, dataset_type 등)은 추적하지 않음
   - **질문**: 중간 노드에서 output 타입을 알아야 하는가? (예: COCO→YOLO 변환 후 YOLO 전용 manipulator만 허용)
   - 통일포맷 전환으로 annotation_format은 내부에서 의미가 없어졌지만, dataset_type(SOURCE/PROCESSED/FUSION) 전파는 필요할 수 있음

3. **엣지 연결 규칙 검증**
   - 현재 아무 노드나 연결 가능 — 타입 호환성 체크 없음
   - DataLoadNode → OperatorNode/MergeNode만 허용, SaveNode → 아무것도 연결 불가 등의 규칙 필요
   - 클라이언트(React Flow `isValidConnection`)에서 할지, 서버 검증에서 할지

4. **검증 결과 노드별 하이라이트**
   - validate API 결과의 `issue_field`를 개별 노드에 매핑하여 시각적 피드백 제공

### 현재 검증 체계 참고

**정적 검증 (lib/pipeline/pipeline_validator.py):**
- INVALID_DATASET_TYPE, RAW_NOT_ALLOWED_AS_OUTPUT, INVALID_SPLIT
- INVALID_ANNOTATION_FORMAT, UNKNOWN_OPERATOR
- MERGE_MIN_INPUTS, MULTI_INPUT_WITHOUT_MERGE

**DB 검증 (app/services/pipeline_service.py):**
- SOURCE_DATASET_NOT_FOUND, SOURCE_DATASET_GROUP_DELETED
- SOURCE_DATASET_NOT_READY, SOURCE_DATASET_NO_ANNOTATIONS

---

## 핵심 파일 변경 맵 (이번 세션)

### 신규 파일

| 파일 | 역할 |
|------|------|
| `frontend/src/components/pipeline/ExecutionDetailDrawer.tsx` | 공유 실행 상세 Drawer 컴포넌트 |
| `backend/migrations/versions/007_migrate_version_format.py` | 버전 포맷 마이그레이션 |

### 수정된 파일

| 파일 | 주요 변경 |
|------|-----------|
| `frontend/src/utils/pipelineConverter.ts` | JSON→Graph 역변환 함수 3종 추가 |
| `frontend/src/components/pipeline/EditorToolbar.tsx` | "JSON 불러오기" 버튼 |
| `frontend/src/pages/PipelineEditorPage.tsx` | JSON load 모달 + 비동기 복원 |
| `frontend/src/pages/PipelineHistoryPage.tsx` | 인라인 Drawer 제거 → import 교체 |
| `frontend/src/pages/DatasetViewerPage.tsx` | 생성 Pipeline ID + Drawer 직접 오픈 |
| `frontend/src/types/pipeline.ts` | output_dataset_version, output_dataset_group_id |
| `frontend/src/types/dataset.ts` | pipeline_execution_id |
| `frontend/src/components/dataset/DatasetRegisterModal.tsx` | 버전 기본값 1.0, 안내 경로에 버전 포함 |
| `backend/app/schemas/pipeline.py` | output_dataset_version, output_dataset_group_id |
| `backend/app/schemas/dataset.py` | pipeline_execution_id, 버전 description |
| `backend/app/api/v1/pipelines/router.py` | _build_execution_response 확장 |
| `backend/app/models/all_models.py` | Dataset.pipeline_execution_id @property |
| `backend/app/services/dataset_service.py` | selectinload 추가, _next_version 정책 변경 |
| `backend/app/services/pipeline_service.py` | _next_version 정책 변경, _intersect_source_task_types 신규, _find_or_create_dataset_group task_types |
