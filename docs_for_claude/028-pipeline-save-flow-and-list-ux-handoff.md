# 핸드오프 028 — 저장/실행 분리 정식화 + 모달 두 모드 + 회색지대 차단 + JSON import 통합 + 실행 이력 강화 + 출력 필터 (v7.13)

> 최초 작성: 2026-04-30
> 브랜치: `feature/pipeline-family-and-version` (v7.10 ~ v7.13 누적)
> 직전 핸드오프 (같은 브랜치 위 v7.10 / v7.11 / v7.12): `docs_for_claude/027-pipeline-run-automation-separation-design.md`
> 직전 main 머지 완료 핸드오프: `docs_history/handoffs/025-dataset-three-tier-separation-handoff.md`
> 설계서: `objective_n_plan_7th.md` v7.13 (본 핸드오프와 짝)

---

## 0. 이 핸드오프의 위치

027 가 v7.10 (3 엔티티 분리) → v7.11 (Family + Version + source format v3) → v7.12
(UI 마무리 + Family.color) 까지 한 호흡으로 다뤘다. 본 028 은 그 직후의 v7.13 으로,
027 §14-5 가 "v7.13 → 후속" 으로 미뤄둔 항목들 (Automation 제외) 을 모두 흡수하고
사용자 스모크 누적 피드백을 반영한 챕터.

**v7.13 의 단일 테마.** "Pipeline 측 분할 (Family / Pipeline / Version / Run) 을
사용자 워크플로우 관점에서 마무리" — 저장/실행이 명확히 분리되고, 이름/설명/버전
메모가 인라인으로 편집되며, 같은 출력으로 모이는 Pipeline 들을 한눈에 필터링하고,
실행 이력을 다축으로 정렬·리사이즈한다. Automation 만 v7.14 로 남는다.

---

## 1. 결정 + 변경 요약 (커밋 단위)

### 1-1. §12-1 저장/실행 분리 정식화 (commit `a734963`)

**왜.** v7.11 에서 도입한 `_get_or_create_concept_and_version` 임시 shim 이 에디터
"실행" 클릭 한 번으로 concept + version + run 을 모두 만들고 있었다. 사용자가
"저장만 하고 나중에 실행" 을 못 했고, 같은 config 라도 무조건 새 run 이 생기는 등
멘탈 모델이 흐릿했다.

**무엇을.**
- `POST /pipelines/concepts` 정식 신설 (status 201, body = config). `concept_name`
  query param 으로 모달 입력 이름 전달. 실행 (PipelineRun + Celery dispatch) 은
  하지 않는다.
- 서비스 `save_pipeline_from_config(config, *, concept_name=None)` 신설. 출력
  DatasetGroup / DatasetSplit 자동 생성 (§12-7 빈 그룹 노출 OK 정책 그대로) +
  Pipeline (concept) + PipelineVersion 저장만.
- `_get_or_create_concept_and_version` → `_save_concept_and_version` 정식 헬퍼
  격상. tuple 반환 `(pipeline, version, is_new_concept, is_new_version)`.
- **제거**: `submit_pipeline` 메서드, `POST /pipelines/execute` 엔드포인트,
  `_extract_resolved_input_versions` 헬퍼.
- FE: `pipelineConceptsApi.save(config, conceptName?)` + `pipelinesApi.execute` 제거.
  EditorToolbar 의 "실행" 버튼 → "저장". 저장 모달 → success 메시지 + `/pipelines`
  navigate. `ExecutionStatusModal.tsx` 삭제, store 의 `executionId` / `setExecutionId` 정리.

**실행 흐름 (분리 후).**
- 에디터에서는 "저장" 만. PipelineRun 은 만들지 않음.
- 목록 행 우측 "실행" 버튼 → Version Resolver Modal → `POST /pipelines/versions/{id}/runs`
  (v7.11 에서 이미 존재) → PipelineRun + Celery dispatch.

### 1-2. §12-2 #1 + 확장 — 저장 모달 두 모드 + 회색지대 차단 (commit `3d049fe`)

**왜.** §12-2 #1 단순 텍스트 입력만 있으면 사용자가 "이미 같은 (group, split) 출력
을 가진 Pipeline 이 있는지" 모르고 새 이름으로 저장해 중복을 만들거나, 동일 이름
인데 다른 출력으로 저장해 회색지대를 만들 수 있다. → 두 모드 + 출력 mismatch
구조적 차단.

**무엇을.**
- 모달 Radio 로 모드 토글:
  - **manual** (기본): Input 직접 입력. 기본값 = `{config.name}_{split.lower()}`.
  - **select**: 같은 `task_type` + 같은 `output_split_id` Pipeline 만 dropdown
    (latest_version / 비활성 여부 함께 표시). 출력이 같음이 보장됨.
- backend `_save_concept_and_version`:
  - 동일 name + `existing_concept.output_split_id != output_split_id` → ValueError.
    라우터에서 400 친화 메시지 (`"같은 이름의 Pipeline 이 이미 다른 output (group/split)
    으로 등록돼 있습니다 — 다른 이름을 사용하거나, 출력을 동일하게 맞추세요."`).
- backend `list_pipelines` 에 `output_split_id: list[str] | None` 다중 IN 필터.
  라우터에 같은 이름의 query param. 저장 모달 select 모드 후보 좁히기 + 출력
  필터 (§1-7) 양쪽에서 사용.
- FE: `pipelineConceptsApi.list` 시그니처에 `output_split_id` 추가.

**효과.**
- 같은 이름 + 같은 출력 → 새 버전으로 추가 (정상 운영).
- 같은 이름 + 다른 출력 → 400 차단 (회색지대 제거).
- 다른 이름 + 같은 출력 → 별개 Pipeline 공존 (의도된 동작 — 같은 (group, split) 에
  다른 처리 방식 가능).

### 1-3. JSON import 통합 (commit `b597a08`)

**왜.** PipelineRun.transform_config 에는 `source:dataset_version:<id>` 토큰이
들어있어, 사용자가 그걸 복사해 에디터의 "JSON 불러오기" 에 붙이면 v7.11 의 split
기반 spec 과 충돌해 저장이 막혔다. 또 Pipeline.config (split 토큰) 케이스도 매핑
방식이 어긋나 DataLoad 노드 그룹/Split 라벨이 안 채워졌다.

**무엇을.** `handleLoadJson` 재작성:
- listGroups 한 번 호출로 두 인덱스 동시 구축:
  - `splitIdToDisplay: Record<split_id, DatasetDisplayInfo>`
  - `versionIdToSplitId: Record<dataset_version_id, split_id>`
- `unresolveVersionRefsToSplitRefs(config, versionToSplitMap)` 로 dataset_version
  토큰 → 부모 split 환원 후 configToGraph 호출. PipelineRun JSON 도 저장 검증
  통과.
- datasetDisplayMap 키를 split_id 로 통일 (matchFromConfig lookup 일치).
- 누락 토큰 (현재 DB 에 없는 split / 부모 split 미매핑 version) 은 Modal 경고로
  명시 (저장 검증에서 차단).

SDK index 에 `parseSourceRef` / `buildSplitSourceRef` / `buildVersionSourceRef` /
`unresolveVersionRefsToSplitRefs` export 추가.

### 1-4. 이름 · 설명 · 버전 메모 inline 편집 + Alembic 034 (commit `4e8e617`)

**왜.** v7.11 부터 `Pipeline.name` / `Pipeline.description` 은 PATCH 가능했지만 UI
가 readonly 였다. PipelineVersion 에는 description 컬럼 자체가 없어 "이 버전에서
무엇을 바꿨는가" 를 적을 곳이 없었다. config 가 immutable 인 만큼 변경 의도는
사람이 적어줘야 추적 가능.

**무엇을.**
- Alembic 034: `pipeline_versions.description TEXT NULL` 추가. 백필 없음.
- ORM PipelineVersion.description.
- Pydantic schemas — `PipelineVersionResponse.description` /
  `PipelineVersionSummary.description` / `PipelineVersionUpdateRequest.description`.
  description 시맨틱: None=미변경, ""=NULL clear, 그 외=갱신.
- `update_pipeline_version` 에 description 매개 변수.
- FE — Typography editable 로 인라인 편집:
  - PipelineListPage ExpandedConceptContent: 제목 (Pipeline name) + 설명.
  - VersionRow: 접힌 상태에 description 한 줄 미리보기, 펼친 미니 패널에서 편집.
  - PipelineVersionDetailPage 사이드 패널: "버전 설명" Descriptions item.
- mutation 후 `pipeline-version-detail-page` / `pipeline-concepts` /
  `pipeline-concept-detail` 캐시 invalidate.

### 1-5. 실행 이력 페이지 column overhaul + 정렬 + 가변 폭 (commit `d9d2c00`, `6695c56`)

**왜.** "파이프라인" 단일 컬럼이 `config.name` (= output group name) 만 보여줬다.
실제로는 Pipeline.name 과 다르고, 어떤 version 이 어떤 output 으로 갔는지도 안
보였다. 또 컬럼 폭이 고정이라 긴 이름이 잘렸고 정렬은 created_at desc 만 가능.

**무엇을.**
- backend `PipelineRunResponse` 에 평탄화 필드 4개 추가: `pipeline_name`,
  `pipeline_version`, `output_dataset_group_name`, `output_dataset_split`.
  `_build_run_response` 가 selectinload 된 관계 (`pipeline_version.pipeline` /
  `output_dataset.split_slot.group`) 에서 채움.
- `list_executions` / `list_runs_by_pipeline` / `list_runs_by_pipeline_version` /
  `get_execution_status` 의 selectinload 체인을 `group` + `pipeline_version.pipeline`
  까지 확장.
- `list_executions` 에 `sort_by` + `sort_order` 인자. 9개 키 — 자체 컬럼 4
  (created_at / status / started_at / finished_at) + Pipeline join 2 (pipeline_name /
  pipeline_version) + Output join 3 (group_name / split / version). join 필요한
  키는 outerjoin 으로 묶고, count 는 별도 쿼리로 안정화. 라우터 화이트리스트 검증.
- FE: PipelineHistoryPage column 5개 분리 (파이프라인명/버전/Output 그룹/Split/버전).
  `useResizableColumnWidths` 적용 + 모든 컬럼 헤더 우측 경계 드래그 + 클릭 정렬.

**리사이즈 perf 개선 + §6-3 규약화 (commit `6695c56`).**
- `ResizableTableColumns` 훅 재작성:
  - drag 동안 React state 갱신 X. colgroup `<col>` + `<th>` 의 `style.width` 직접
    조작. mouseup 시 onResize 1회 sync.
  - AntD `scroll: { x }` 로 split 된 헤더 / 바디 두 colgroup 동시 갱신
    (container 안의 모든 colgroup 의 같은 cellIndex col 갱신).
  - rAF coalesce — mousemove 폭주를 frame 당 1회 flush.
  - 매 frame `table.style.width = sum + 'px'` 직접 박아 CSS `max-content` 동적
    합산 비용 회피. mouseup 에서 inline width 비워 페이지 CSS 가 다시 적용되도록.
  - drag 종료 후 click 이 부모 th 로 전파해 정렬이 토글되던 회귀 — capture 단계
    1회 swallow (deltaPx ≠ 0 발생 시만, 100ms safety timeout).
  - `MINIMUM_COLUMN_WIDTH_PX = 0` (사용자 자유 폭 조정).
- 페이지 측 (PipelineHistoryPage / DatasetListPage) 에:
  ```css
  .<page-class> .ant-table-content > table,
  .<page-class> .ant-table-body > table {
    width: max-content !important;
    min-width: 0 !important;
  }
  ```
  AntD 기본 `width: 100%` 로 인한 비례 분배 (가장 넓은 컬럼이 잉여 절대량을
  가장 많이 받아 우측 공백 부풀림 + 줄여도 안 줄어듦) 회피.
- 본 패턴은 설계서 §6-3 으로 정식 규약화. 새 페이지가 `useResizableColumnWidths` 를
  쓸 때 빠뜨리면 안 되는 4가지 (페이지 CSS / drag 중 state 금지 / split-table
  동시 / rAF + 직접 width / drag 후 click swallow / floor 0) + 위반 시 진단 가이드.

### 1-6. Pipeline 목록 — 미분류 최상단 + 빈 family 표시 (commit `8d6cce7`)

**왜.** 직전엔 미분류가 마지막에 가고 Pipeline 0개 family 는 표시되지 않아 "비어
있는 family 가 있는지" 자체를 사용자가 인지하기 어려웠다.

**무엇을.** `groupedItems` 산출 재작성:
- 미분류 그룹은 항상 페이지 **최상단** push.
- `familiesQuery` 전체 기반으로 그룹을 만들고 각 그룹의 items 는 listQuery 결과
  에서 매칭. Pipeline 0개여도 family heading + "0개 Pipeline" + 점선 박스 안내
  ("이 family 에 등록된 Pipeline 이 없습니다") 표시.
- 필터 활성 시 (selectedFamilyIds 또는 includeUnfiled) 선택된 family 만 노출,
  미분류는 includeUnfiled 일 때만.
- `firstNonEmptyGroupIndex` 로 첫 비어있지 않은 그룹의 Table 만 column 헤더 노출
  (빈 그룹은 Table 자체를 안 그리므로 인덱스 0 이 비어있어도 헤더가 사라지지
  않게 보정).

### 1-7. 출력 (group, split) 필터 (commit `6ce0995`)

**왜.** Family 필터 외에 "출력 (group, split) 기준" 필터 욕구 — 같은 출력으로
모이는 Pipeline 들을 한눈에 모아 보고 싶다. 사용자가 직접 디자인 — "그룹당 한 행,
group checkbox + 4개 고정 split (TRAIN/VAL/TEST/NONE) 체크박스".

**무엇을.**
- 이름 검색과 Family 필터 사이에 신규 Dropdown.
- 비활성 포함 모든 Pipeline 의 출력 그룹을 후보 행으로 나열 (`allOutputPipelinesQuery` —
  pipelineConceptsApi.list({include_inactive: true, limit: 200})).
- 그룹당 한 행 — group checkbox (4 split 중 일부만 선택 시 indeterminate, 클릭
  시 4개 모두 토글) + TRAIN / VAL / TEST / NONE 4개 고정 split 체크박스 (각각
  독립 토글).
- state: `selectedOutputPairs: Set<\`${group}::${split}\`>`.
- backend 전달: 선택된 페어들에 매칭되는 split_id 들을 backend `output_split_id`
  IN 필터로 (1-2 에서 추가한 필터). 매칭이 0개인 경우 (사용자가 실재하지 않는
  조합만 선택) sentinel UUID `00000000-0000-0000-0000-000000000000` 을 박아 빈
  결과를 강제 (빈 list 가 backend 의 falsy 체크에서 무시돼 전체 반환되는 문제 회피).
- Dropdown 폭: minWidth 640px, maxWidth 880px (긴 그룹명이 잘리지 않도록).

---

## 2. 이번 세션의 사용자 결정 (출처)

- **저장/실행 분리는 정식 분리** — 에디터 안에 실행 버튼은 두지 않음. 저장 후
  목록의 행 우측 "실행" 버튼으로 별도 Version Resolver. (§12-1 그대로)
- **저장 모달의 기본은 직접 입력**. 기존 선택은 Radio 로 토글. (사용자 명시)
- **회색지대 차단은 backend 가 담당** — 동일 이름 + 다른 출력은 ValueError → 400.
  FE 는 친화 메시지를 띄울 뿐.
- **출력 필터는 (group × 4 split) 행 단위** — 사용자가 직접 레이아웃 설계.
- **컬럼 floor 는 0** — 사용자 자유. 너무 좁아져 핸들이 안 잡히면 옆 컬럼의 우측
  핸들로 회복 가능.
- **미분류 최상단 + 빈 family 표시** — 사용자 명시.
- **PipelineVersion.description** 은 별도 컬럼. concept-level description 과 독립.

---

## 3. 영향 파일 / Alembic

### 3-1. Alembic
- `034_pipeline_version_description.py` — `pipeline_versions.description TEXT NULL`.

### 3-2. backend
- `app/api/v1/pipelines/router.py`:
  - `POST /concepts` 신설. `concept_name` query param. ValueError → 400 매핑.
  - `POST /execute` 제거.
  - `GET /` 에 `output_split_id: list[str]` query param.
  - `GET /runs` 에 `sort_by` / `sort_order` query param + 화이트리스트.
  - `_build_run_response` — pipeline_name / pipeline_version / output group_name /
    output split 평탄화.
  - `_version_summary` / `_version_to_response` 에 description.
- `app/schemas/pipeline.py`:
  - `PipelineSaveResponse` 신설.
  - `PipelineRunResponse` 4개 필드 추가.
  - `PipelineVersionSummary.description` / `PipelineVersionResponse.description` /
    `PipelineVersionUpdateRequest.description`.
- `app/services/pipeline_service.py`:
  - `save_pipeline_from_config(config, *, concept_name=None)` 신설.
  - `_save_concept_and_version` 격상 + 동일 이름 + 다른 output_split_id ValueError.
  - `update_pipeline_version` 에 description 매개 변수.
  - `list_pipelines` 에 `output_split_id` 필터.
  - `list_executions` 에 sort_by / sort_order.
  - selectinload 체인 4곳 확장.
- `app/models/all_models.py` — `PipelineVersion.description: Mapped[str | None]`.

### 3-3. frontend
- `src/api/pipeline.ts` — `pipelineConceptsApi.save(config, conceptName?)` /
  `.list` 에 `output_split_id`. `pipelinesApi.execute` 제거.
- `src/types/pipeline.ts` — `PipelineSaveResponse` / `PipelineExecutionResponse`
  4개 필드 / `PipelineVersionSummary.description` / Response.description /
  UpdateRequest.description.
- `src/pages/PipelineEditorPage.tsx` — handleSave / handleConfirmSave 분리, 저장
  모달 두 모드 (Radio + manual / select), JSON import 재작성, datasetsForPipelineApi
  활용, ExecutionStatusModal 의존성 제거.
- `src/pages/PipelineListPage.tsx` — Pipeline name / description editable, 미분류
  최상단 + 빈 family 표시 + firstNonEmptyGroupIndex, 출력 필터 Dropdown +
  selectedOutputPairs state + outputSplitIdsFilter 메모.
- `src/pages/PipelineVersionDetailPage.tsx` — "버전 설명" Descriptions item +
  Paragraph editable + updateVersionDescription mutation.
- `src/pages/PipelineHistoryPage.tsx` — column 5개 + sort + 가변 폭 +
  CSS max-content / min-width: 0 박음.
- `src/pages/DatasetListPage.tsx` — 같은 CSS max-content / min-width: 0 박음.
- `src/components/common/ResizableTableColumns.tsx` — 훅 재작성 (DOM-direct +
  rAF + split-table 동시 + table.style.width 직접 + click swallow + floor 0).
- `src/components/pipeline/EditorToolbar.tsx` — "실행" → "저장".
- `src/components/pipeline/ExecutionStatusModal.tsx` — 삭제.
- `src/stores/pipelineEditorStore.ts` — executionId / setExecutionId 정리.
- `src/pipeline-sdk/index.ts` — parseSourceRef / unresolveVersionRefsToSplitRefs
  export.

---

## 4. 검증

- backend pytest: **446/446 통과** (모든 커밋에서).
- FE TypeScript: 신규 에러 **0건** (pre-existing 11건 그대로 — `api/index.ts` /
  `AppLayout.tsx` / `ServerFileBrowser.tsx` / `SampleViewerTab.tsx` /
  `DatasetRegisterModal.tsx` / `ManipulatorListPage.tsx`).
- Alembic 034: upgrade / downgrade 왕복 검증.
- 사용자 브라우저 스모크 — 8개 기능 모두 정상 확인:
  1. 저장/실행 분리 (에디터 → /pipelines navigate)
  2. JSON import (split / version 토큰 양쪽)
  3. Pipeline 이름 / 설명 / PipelineVersion 설명 인라인 편집
  4. 실행 이력 5개 컬럼 + 정렬 + 가변 폭
  5. 컬럼 리사이즈 매끄러움 + 폭 정합 (max-content)
  6. 저장 모달 두 모드 (직접 입력 / 기존 Pipeline 선택)
  7. 동일 이름 + 다른 출력 400 차단
  8. 미분류 최상단 + 빈 family 표시
  9. 출력 (group, split) 필터

---

## 5. 남은 작업 — v7.14 후보

### 5-1. §9-8 Automation 메뉴 실 API 재연결 (가장 큰 작업)

- 026 mock fixture (`frontend/src/api/automation.ts` 의 `sessionPipelines`) →
  `pipelineVersionsApi` / `pipelineAutomationsApi` 어댑터.
- v7.10 / v7.11 격하로 자료구조가 PipelineVersion 단위라 026 mock 의 단일 Pipeline
  타입과 어댑터 구현 부담이 있음.
- 영향 페이지: AutomationPage / AutomationHistoryPage / AutomationPipelineDetailPage 3개.
- chaining / upstream delta / execution batch 는 당분간 빈 응답 (실 구현은 §16
  단계).

### 5-2. Automation 자동 실행 본구현 (§16)

- chaining 분석기 (pure 함수) + 사이클 감지 → automation_status = error.
- Polling 스캐너 (Celery beat) / Triggering 훅 (SQLAlchemy after_flush).
- `last_seen_input_versions` 갱신 로직.
- 수동 재실행 엔드포인트 — `POST /pipelines/automations/{id}/rerun` (이미 027 §13-6
  에 라우트 있음, 본 구현 필요).

### 5-3. 핸드오프 029 + main 머지

- 5-1 / 5-2 끝나면 핸드오프 029 작성 + 설계서 v7.14 승격 + 본 브랜치
  (`feature/pipeline-family-and-version`) main 머지.

---

## 6. 참조

- 설계서 (현행): `objective_n_plan_7th.md` v7.13 (2026-04-30 baseline).
- 직전 핸드오프 (027): `docs_for_claude/027-pipeline-run-automation-separation-design.md`
  (§13 v7.11 / §14 v7.12).
- §6-3 정식 규약: `objective_n_plan_7th.md` §6-3 — AntD Table 가변 폭 컬럼
  리사이즈 성능 / 폭 정합.
- 노드 SDK 가이드: `docs/pipeline-node-sdk-guide.md`.

---

## 7. UI 스모크 가이드 (v7.13 baseline)

브라우저 `http://localhost:18080` 에서 아래 항목 체크:

1. **저장 흐름** — `/pipelines/editor?taskType=DETECTION` → DAG 구성 → "저장"
   클릭 → 검증 통과 후 모달 → 기본 이름 prefilled → 저장 → `/pipelines` 자동 이동.
2. **모달 두 모드** — 같은 흐름에서 모달 내 Radio "기존 Pipeline 선택" 클릭 →
   같은 task_type + 같은 output_split Pipeline 만 dropdown → 선택 → 그 Pipeline
   의 새 버전으로 추가됨.
3. **회색지대 차단** — 직접 입력에서 같은 이름 + 다른 출력으로 저장 시도 → 400
   친화 메시지 ("같은 이름의 Pipeline 이 이미 다른 output (group/split) 으로 등록…").
4. **JSON import** — PipelineRun JSON (dataset_version 토큰) 또는 Pipeline.config
   JSON (dataset_split 토큰) 을 에디터의 "JSON 불러오기" 에 붙여넣기 → DataLoad
   노드의 그룹/Split 라벨이 정상 채워짐. 누락 토큰이 있으면 모달 경고.
5. **이름 / 설명 / 버전 메모 편집** — `/pipelines` → 행 클릭 → 펼친 상자의
   제목 / 설명 / 버전 카드 description → Typography editable 아이콘 클릭 → 편집.
6. **실행 이력 페이지** — `/pipelines/runs` → 5개 컬럼 (파이프라인명/버전/Output
   그룹/Split/버전) → 헤더 클릭 정렬 (ascend / descend / 해제) → 우측 경계 드래그
   로 폭 조정.
7. **컬럼 리사이즈 매끄러움** — 가장 넓은 컬럼 (예: 파이프라인명) 의 우측 경계를
   드래그 → cursor 와 column edge 가 1:1 추종, 줄임도 매끄러움. drag 후 정렬이
   토글되지 않음.
8. **출력 필터** — `/pipelines` 헤더 "출력 필터" Dropdown → 그룹당 한 행 (group
   checkbox + 4 split) → 선택 → 매칭 Pipeline 만 노출. 후보 행 0건 또는 매칭 0건
   인 경우도 정상.
9. **미분류 최상단 + 빈 family** — `/pipelines` → 미분류 그룹이 페이지 맨 위 →
   Pipeline 이 0개인 family 도 점선 박스 안내로 표시.

---

> **다음 세션은 v7.14 진입.** §9-8 Automation 실 API 재연결을 시작점으로.
