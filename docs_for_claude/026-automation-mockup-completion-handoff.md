# 핸드오프 026 — Automation 목업 구현 완료

> 최초 작성: 2026-04-23
> 브랜치: `feature/pipeline-automation-mockup` (main 에서 025 머지 직후 재생성)
> 직전 핸드오프 (main 머지 완료): `docs_for_claude/025-dataset-three-tier-separation-handoff.md`
> 선행 계획: `docs_for_claude/023-automation-mockup-tech-note.md` §6 / §9
> 설계서 반영 예정: v7.10 (목업 기준선 편입 시)

---

## 0. 이 세션의 목적

023 §9 에서 확정된 7개 블로킹 결정 + §6 의 목업 스코프를 프론트 전용으로 실제 렌더되는 화면까지
구현한다. 백엔드 / DB 는 건드리지 않는다 (§6-5 원칙). 본 세션 종료 시점에 사용자가 브라우저에서
`/automation` 진입부터 상세 탭 / 실행 이력 / chaining DAG / 수동 재실행 모달까지 mock fixture 로
체험할 수 있어야 한다.

---

## 1. 스코프

### 1-1. 이번 세션 범위

- 프론트 타입 + mock fixture + 비동기 API wrapper 3파일 (1단계)
- 사이드바 메뉴 / 라우팅 추가 (2단계)
- Automation 관리 페이지 — 좌 목록 + 우 chaining DAG (3단계)
- 파이프라인 상세 Automation 탭 페이지 — 설정 폼 + 수동 재실행 모달 + 상류 delta + 최근 실행 (4단계)
- Automation 실행 이력 페이지 — batch 트리 + automation 필터 (5단계)
- 회귀 검증 — TS 빌드 pre-existing 외 신규 에러 0 건
- 본 핸드오프 작성 (6단계)

### 1-2. 이번 세션 **밖** (§6-5 원칙 고수)

- Celery beat 폴링 스캐너 / Triggering 훅 실 구현
- Pipeline 엔티티 DB 도입 / Alembic 마이그레이션
- chaining 분석기 / `automation_last_seen_input_versions` 갱신 로직
- minor 버전 자동 증가 / downstream skip 실 분기
- `/pipelines` (실 백엔드 이력 페이지) 개편 — 경로 분리 결정 (§3-3)
- `Dataset.metadata.class_info` 축소 (설계서 §5 item 26)

---

## 2. 세션 내 결정사항

### 2-1. 진행 순서 — 의존성 기반 5단계

1. 타입 + fixture (기반) → 2. 네비 + 라우팅 (껍데기) → 3. 관리 페이지 (메인) → 4. 상세 탭 →
5. 실행 이력. 공통 컴포넌트 (StatusBadge, ManualRerunModal) 가 앞 단계에서 자연스럽게 생겨
뒷 단계가 재사용.

### 2-2. 3파일 분리 — 타입 / fixture / API wrapper

- `frontend/src/types/automation.ts` — 타입 선언
- `frontend/src/mocks/automation.ts` — 순수 fixture 상수 + 세션 스토어 없음
- `frontend/src/api/automation.ts` — 비동기 Promise wrapper + in-memory 세션 스토어 (상태 토글 반영용)

**근거.** 실 API 전환 시 `api/automation.ts` 만 교체하면 페이지·컴포넌트는 그대로 동작.
목업 단계에서도 호출부가 `await api.listPipelines()` 로 통일돼 Suspense / React Query 통합이 자연스럽다.

### 2-3. 세션 in-memory 스토어

`api/automation.ts` 내부의 `sessionPipelines` 변수 — 상태 토글 / mode 변경 등 사용자 조작이 페이지
이동 시에도 일관되게 보이도록 fixture 상수의 복사본을 세션 메모리에 둔다. 새로고침 시 원본으로
초기화된다 (의도된 동작, 실 API 에서는 사라짐).

### 2-4. `/automation/history` 별도 경로 (§2-2 결정의 실행)

023 §6-3 의 "실행 이력 페이지 개편" 은 `/pipelines` 페이지를 의도하지만, `/pipelines` 는 실 백엔드
API 를 호출하는 살아있는 페이지라 mock automation 필드와 섞으면 데이터 출처가 혼재된다. 본 목업은
**Automation 메뉴 하위 별도 경로 `/automation/history`** 에 두고, Automation 관리 페이지와
`AutomationSectionNav` (antd Segmented) 로 전환한다. 실 구현 진입 시 두 뷰의 통합 여부는 그때 재결정.

### 2-5. 상태 배지 ↔ DAG 색상 일치

`StatusBadge` 컴포넌트와 `AUTOMATION_STATUS_COLOR` 팔레트를 한 파일에 두어 관리 목록 / 상세 탭 /
chaining DAG 에서 동일한 색상 언어 (회색 stopped · 초록 active · 빨강 error) 를 공유한다.

### 2-6. Chaining DAG — grid layout + fitView

dagre / elk 같은 자동 레이아웃 라이브러리를 도입하지 않고 단순 3-column grid + React Flow `fitView`
로 시작. 목업 6건 규모에서 가독성 충분. 사이클 엣지는 `animated: true` + 빨강 stroke + 빨강 arrow marker
로 시각 차별. 실 구현에서 파이프라인 수가 늘면 dagre 도입 재검토.

### 2-7. 수동 재실행 UX — 2-버튼 확인 모달

- `[변경사항 존재시 재실행]` — `if_delta` mode: 상류 delta 판정 후 dispatch / no-delta skip 분기
- `[강제 최신 재실행]` — `force_latest` mode: delta 무시, 항상 dispatch
- 결과는 Result 화면으로 교체 (async dispatch 후 즉시 결과 안 기다림, §G-29)
- 버튼 위치는 상세 탭 only (목록 행 X) — 사용자가 내용 확인 후 실행 강제 (§G-29)
- error 상태 파이프라인은 수동 재실행 버튼 자체 비활성화

### 2-8. 설정 폼 — 2단계 적용 UX

mode / poll_interval 변경은 draft 상태로 두고 "설정 적용" 버튼 클릭 시에만 반영. 실수로 자동 저장돼
automation 이 의도치 않게 바뀌는 것을 방지 (메모리 `feedback_format_change_ux` — 속성 변경은 2단계
확정 패턴 선호).

Status 전환 (stopped ↔ active) 은 별도 버튼 2개로 분리 — error 상태는 사용자가 직접 설정할 수 없음을
UX 상 명시 (error 는 시스템 자동 감지 전용).

---

## 3. 변경된 / 추가된 파일

### 3-1. 신규

- `frontend/src/types/automation.ts` — 열거형 + Pipeline / ChainingGraph / ExecutionBatch / UpstreamDelta 타입
- `frontend/src/mocks/automation.ts` — 파이프라인 6건 + 실행 이력 8건 + batch 1건 + 상류 delta fixture
- `frontend/src/api/automation.ts` — 비동기 Promise wrapper + `sessionPipelines` in-memory 스토어
- `frontend/src/pages/AutomationPage.tsx` — 관리 페이지 (좌 목록 + 우 DAG)
- `frontend/src/pages/AutomationHistoryPage.tsx` — 실행 이력 페이지
- `frontend/src/pages/AutomationPipelineDetailPage.tsx` — 파이프라인 상세 Automation 탭 (독립 페이지로 시작)
- `frontend/src/components/automation/StatusBadge.tsx` — 상태 배지 + 색상 팔레트 공용
- `frontend/src/components/automation/AutomationPipelineList.tsx` — 좌측 파이프라인 Table + 필터
- `frontend/src/components/automation/AutomationChainingDag.tsx` — 우측 React Flow DAG
- `frontend/src/components/automation/AutomationSettingsForm.tsx` — 상세 탭 설정 폼
- `frontend/src/components/automation/AutomationSectionNav.tsx` — 관리 ↔ 이력 Segmented
- `frontend/src/components/automation/ExecutionHistoryTable.tsx` — batch 트리 테이블 + 필터
- `frontend/src/components/automation/ManualRerunModal.tsx` — 수동 재실행 2-버튼 모달
- `frontend/src/components/automation/UpstreamDeltaList.tsx` — 상류 DatasetGroup delta 표
- `frontend/src/components/automation/RecentAutomationRuns.tsx` — 상세 탭 최근 실행 요약

### 3-2. 수정

- `frontend/src/App.tsx` — /automation / /automation/history / /automation/pipelines/:id 3개 라우트 추가
- `frontend/src/components/common/AppLayout.tsx` — 사이드바 "Automation" 메뉴 항목 + selectedKey 분기 추가 (ThunderboltOutlined 아이콘)

---

## 4. 목업 시나리오 fixture

6건 파이프라인으로 automation 주요 케이스를 시연한다.

| ID | 이름 | 시나리오 | 상태 | 모드 |
|---|---|---|---|---|
| P1 | `hardhat_headcrop_original_merge` | RAW → SOURCE 정상 체인 입력 | active | triggering |
| P2 | `hardhat_headcrop_visible_add` | SOURCE → SOURCE 정상 체인 출력 | active | polling 1h |
| P3 | `cycle_demo_a_to_b` | 사이클 — 시스템 자동 error | error (CYCLE_DETECTED) | polling 10m |
| P4 | `cycle_demo_b_to_a` | 사이클 — 시스템 자동 error | error (CYCLE_DETECTED) | triggering |
| P5 | `person_detection_raw_to_coco` | stopped 그대로 | stopped | — |
| P6 | `vehicle_detection_augment` | 수동 재실행 no-delta skip 시연 | active | polling 6h |

**chaining DAG 엣지**
- `P1 → P2` (정상, `hardhat_headcrop_original_merged` 매개)
- `P3 → P4 → P3` (사이클, 빨강 엣지 + 노드 빨강 테두리)

**실행 이력**
- `batch-20260422-1430` : P1 → P2 토폴로지 순서 2건 (triggering source)
- 단발 실행 5건 (P1/P2 초기 manual, P3/P4 사이클 감지 전 manual, P5 manual, P6 polling)
- 수동 재실행 no-delta skip 1건 (P6, `SKIPPED_NO_DELTA`)

**사용자 제공 참조 DatasetVersion ID** (023 §9-10 / 025 §7-2-8 계보, 실 DB 존재 여부는 재확인 필요):
- `hardhat_headcrop_visible_added` — `83f76037-df56-4575-a343-2ade37299225`
- `hardhat_headcrop_original_merged` — `4d2afb95-f7e6-4297-afff-6c435b9af9cf`

fixture 의 P1 / P2 batch 실행에 이 두 ID 를 `output_dataset_version_id` 로 박아두어, 사용자가 추후
실 DB 재확보 시 fixture 를 실 조회 체인으로 쉽게 전환할 수 있게 한다.

---

## 5. 검증

### 5-1. TypeScript 빌드

`docker compose exec frontend npx tsc -b` — **pre-existing 11건 외 신규 에러 0건**. pre-existing 목록은
022 §7 에 등록된 그대로 유지 (api/index.ts / AppLayout.tsx / ServerFileBrowser / SampleViewerTab /
DatasetRegisterModal / ManipulatorListPage).

### 5-2a. 수동 스모크 피드백 반영 (2026-04-23 세션 후반)

사용자 스모크 1회차 피드백을 반영해 좌측 목록 ↔ 우측 DAG 를 **master-detail 패턴**으로 변경.

**배경.** 1회차 구현은 목록 행 클릭 시 즉시 `/automation/pipelines/:id` 로 이동하는 구조였다. 그러나
사용자 의도는 "여러 파이프라인을 돌려보며 우측 DAG 구성을 비교" 인데, 즉시 이동 때문에 DAG 를 확인할
시간이 없었다.

**변경점.**
- 행 클릭 = **선택 토글** (같은 행 재클릭 시 해제). 선택 행은 `#e6f4ff` 배경 강조
- 우측 DAG 에서 선택된 노드는 테두리 굵어지고 파란 box-shadow, 선택된 노드의 1-hop 이웃은 평소대로,
  그 외 노드는 `opacity: 0.3` + 무관 엣지는 `opacity: 0.2` 로 흐림 처리
- 상세 페이지 이동은 목록 행 끝의 **"상세 →"** 링크 버튼 (`stopPropagation` 으로 행 선택과 분리)
- DAG 상호작용 관련 로직은 `AutomationChainingDag.buildReactFlowGraph` 의 `selectedPipelineId` 인자에 집약

**영향 파일.** `AutomationPipelineList.tsx`, `AutomationChainingDag.tsx`, `AutomationPage.tsx`.

**batch 2건 묶인 row 는 정상 동작으로 확인.** fixture 의 `batch-20260422-1430` (P1 → P2 triggering
자동 실행) 시연용이며, 행 왼쪽 화살표로 펼치면 토폴로지 순서 내부 2건이 표시된다. 023 §6-3 요구
사항 "automation batch 시각화 — 같은 batch_id 는 트리/그룹으로 접힘" 을 그대로 반영.

### 5-2b. 수동 스모크 피드백 반영 (2차 · 2026-04-23 세션 후반)

1차 피드백 (§5-2a) 이후 이어진 사용자 2차 스모크에서 **3 가지 UI 개선 요구** 를 반영.

**이슈 1 — task 종류 (DETECTION / CLASSIFICATION) 가시화.**
- `Pipeline.task_type: TaskType` 타입 필드 신규. fixture 6건에 값 직접 박음 (P1/P2 = CLASSIFICATION,
  P3~P6 = DETECTION)
- `StatusBadge.tsx` 에 `TaskTypeTag` 공용 컴포넌트 신설. `DatasetListPage` 팔레트와 동일 (DETECTION =
  geekblue, CLASSIFICATION = magenta, SEGMENTATION = cyan, ZERO_SHOT = gold). `variant="short"` 축약
  (`DET` / `CLS` / ...) + `variant="long"` 전체 이름
- 목록 (파이프라인명 인라인 앞), 상세 헤더, DAG 노드 카드 세 군데 모두 노출

**이슈 3 — 상세 → 목록 복귀 동선.**
- 상세 페이지 최상단에 **`← 목록으로`** Button (text type, `ArrowLeftOutlined`) 추가
- Breadcrumb 은 유지 (세밀 경로 파악)

**이슈 4 — description inline 편집.**
- `api/automation.ts` 에 `updatePipelineDescription(id, description)` 추가 — 세션 스토어 mutate
- 상세 페이지 헤더 description 영역을 `Typography.Paragraph` + `editable` 로 전환. 빈 값이면 placeholder
  노출 ("설명을 입력해 주세요 — 다른 사용자가 이 파이프라인의 목적을 이해할 수 있게")
- 저장 성공 시 `['automation']` 전체 invalidate → 목록의 description 도 즉시 갱신

**영향 파일.**
- `types/automation.ts`, `mocks/automation.ts` — task_type 필드 + fixture
- `components/automation/StatusBadge.tsx` — TaskTypeTag 신설
- `components/automation/AutomationPipelineList.tsx`, `AutomationChainingDag.tsx` — task 태그 렌더
- `pages/AutomationPipelineDetailPage.tsx` — 복귀 Button + description Paragraph editable
- `api/automation.ts` — updatePipelineDescription mutator

**검증.** `tsc -b` pre-existing 11건 외 신규 에러 0건.

**이슈 2 (DAG 구성 ↔ 의존 그래프 Segmented) 는 보류.** 027 의 "DataLoad 노드 spec 축소 + run-time version
해석" 변경이 DAG 구성 그래프 자체 형태에 영향을 주므로, 027 이후에 같이 재설계 (사용자 결정, 2026-04-23).

### 5-2. 수동 스모크 (사용자 확인 필요)

브라우저 `http://localhost:18080/automation` 에서 아래 항목 체크:

- [ ] 사이드바 "Automation" 메뉴 표시 / 클릭 시 관리 페이지 진입
- [ ] 관리 페이지 좌측 목록 — 6건 표시, 상태 배지 (회색 / 초록 / 빨강) 구분, error 사유 인라인 표시
- [ ] 필터 (상태 / 모드 / 주기) 각각 복수 선택 시 목록 필터링
- [ ] 정렬 (파이프라인명 / 주기 / 마지막 실행) 헤더 클릭 시 반영
- [ ] 우측 DAG — P1 → P2 엣지 파랑, P3 ↔ P4 엣지 빨강 + animated
- [ ] 목록 행 클릭 시 `/automation/pipelines/:id` 상세 탭 이동
- [ ] 상세 탭 Status 전환 버튼 (stopped ↔ active) 동작, 목록 돌아가면 반영돼 있음
- [ ] Mode 라디오 / Poll interval 선택 후 "설정 적용" 버튼 활성화, 클릭 시 메시지
- [ ] 수동 재실행 버튼 → 모달 2-버튼 → 각각 결과 Result 화면 (P6 `if_delta` → no-delta skip)
- [ ] error 상태 (P3/P4) 상세 탭 — 수동 재실행 버튼 비활성 + 해결 가이드 Alert
- [ ] Segmented 로 관리 ↔ 실행 이력 전환
- [ ] 실행 이력 필터 (Trigger / Source / 상태) + batch 행 확장 → 토폴로지 순서 2건 표시
- [ ] 필터에 `SKIPPED_NO_DELTA` 선택 시 P6 재실행 건만 남는지

---

## 6. 023 §9 갱신 필요 사항

### 6-1. §9-9 "현재 상태 스냅샷" 업데이트

- **브랜치** — `feature/pipeline-automation-mockup` 재생성 완료 (본 세션)
- **진행** — §6 목업 3개 화면 + §7 7개 블로킹 결정 반영. 작업 완료
- **다음 작업** — 목업 수용 기준 (§6-2~§6-4 세 화면 mock 동작) 충족. 사용자 수동 스모크 확인 후
  main 머지 여부 결정

### 6-2. 실구현 진입 준비 체크리스트 (핸드오프 027 로 이어질 항목)

- [ ] Pipeline 엔티티 ORM 모델 + Alembic 마이그레이션 (023 §9-2 옵션 1)
- [ ] `PipelineExecution` 확장 — `pipeline_id FK` + `trigger_kind` / `automation_trigger_source` /
      `automation_batch_id` 컬럼 신규
- [ ] 버전 정책 분기 (`_resolve_next_version` 에 `trigger_kind` 인자, 023 §9-7)
  - 데이터 변형 탭 수동 / 구성 변경 신규 → major++
  - Automation 경로 → minor++
- [ ] chaining 분석기 구현 (pure 함수) + 사이클 감지 → `automation_status = error`
- [ ] Polling 스캐너 (Celery beat) / Triggering 훅 (SQLAlchemy `after_flush`)
- [ ] 수동 재실행 엔드포인트 — `POST /pipelines/{id}/automation/rerun` (mode 인자)
- [ ] 실 API 라우터 + 목업 `api/automation.ts` 교체 (타입 / 페이지 / 컴포넌트는 무변경 목표)

---

## 6-a. 이 목업의 한계 — 027 챕터에서 재설계 예정

이번 목업은 **"Pipeline == Automation 엔트리" 로 동일시한 단일 엔티티 모델** 위에서 그렸다 (023 §9-2
옵션 1 을 그대로 반영). 1차 스모크 이후 사용자 피드백으로 다음 한계가 드러났다 (2026-04-23 논의):

1. **개념 섞임.** "파이프라인은 템플릿, PipelineRun 은 templaet 의 materialized run, Automation 은
   runner 등록" 이라는 3 축이 목록 UI 에서 한 줄로 표시되어 "파이프라인 목록" 처럼 읽힘. 사용자가
   "automation 등록 관리 페이지" 임을 인지하기 어려움.
2. **Pipeline 이 DatasetVersion 까지 고정.** 현 DataLoad 노드는 `(group, split, version)` 3단 선택이
   라 version 이 올라갈 때마다 파이프라인을 새로 만들어야 함. "(group, split) 까지만 고정, version 은
   run-time 해석" (2안) 이 더 자연스럽다.
3. **버전 계통 부재.** 동일한 파이프라인의 v1 / v2 같은 세로 관계가 명시되지 않아 과거 run 복원 시
   "어떤 버전으로 돌았는지" 가 표현되지 않음.

**해결 방향 — 핸드오프 027 에서 별도 브랜치로 진행.** 상세는
`docs_for_claude/027-pipeline-run-automation-separation-design.md`.

핵심 결정 요약:

- **3 엔티티 분리**: `Pipeline` (정적 템플릿) / `PipelineRun` (동적 이력, 기존 `PipelineExecution`
  rename) / `PipelineAutomation` (Pipeline 과 1:0..1 runner 등록)
- **2안 채택**: Pipeline 은 `(input_split, output_split)` 까지만 FK 로 고정. DatasetVersion 은 run 제출
  시 resolver Modal 에서 선택 (기본 = 최신)
- **버전 정책**: `Pipeline.version = "major.minor"` (예: `"1.0"`). 사용자 명시로만 증가 (hash 판정 없음).
  동일 config 도 겹쳐 OK. 최초 `1.0`, 새 버전 = `major++`, minor 는 당분간 `0` 고정 (확장 여지)
- **Automation 은 특정 version 의 Pipeline 에 붙음**. v1 → v2 승격 시 자동 추종 안 하고 사용자가 명시
  reassign
- **Pipeline Group / Family 는 후보로 기록만**, 이번 범위에서 차용 X (027 §7)

**이 목업의 남은 가치.** 목업 자체는 UX / 상태 전이 / chaining DAG / 수동 재실행 2-버튼 UX 등을 사용자
검증을 거친 확정 상태로 남긴다. 027 실구현 시 이 화면들의 **레이아웃 · 인터랙션 · 네이밍** 은 3 엔티티
구조에 맞춰 재배선하되, 사용자 수용이 끝난 UX 패턴은 그대로 이식한다.

---

## 7. 유의사항 (세션 이후에도 영구 유효)

- **`/pipelines` 이력 페이지는 건드리지 않는다** — 실 백엔드 데이터이므로 목업 automation 필드와
  혼재하면 안 된다. 실 구현 진입 후 통합 여부 결정.
- **session 스토어는 새로고침 시 초기화된다** — 상태 토글 UX 는 체감용이며, 사용자에게도 페이지
  상단 warning Alert 로 명시돼 있다.
- **Pipeline 엔티티는 아직 백엔드에 없다** — 목업 UI 는 Pipeline 존재를 선가정해 그린다. 실 구현에서
  이 구조가 그대로 매핑 가능하도록 `Pipeline` 타입을 설계했다 (023 §9-2 옵션 1 과 부합).
- **DAG 레이아웃은 단순 grid** — 파이프라인 수 / 엣지 수가 늘어 가독성이 떨어지면 dagre / elk 도입
  재검토. 현 6건 규모에서는 fitView 로 충분.
- **수동 재실행의 no-delta skip 레코드는 실 구현에서도 남긴다** — 023 §9-5, §B-15. 목업은
  `SKIPPED_NO_DELTA` status 로 이를 시연.

---

## 8. 참조

- 설계서 (현행): `objective_n_plan_7th.md` (v7.9, 2026-04-23)
- 선행 결정 기록: `docs_for_claude/023-automation-mockup-tech-note.md` §1-1 / §6 / §9
- 직전 핸드오프 (main 머지 완료): `docs_for_claude/025-dataset-three-tier-separation-handoff.md`
- CLAUDE.md / MEMORY.md — 네이밍 규칙 / 커밋 규약 / 아키텍처 제약
