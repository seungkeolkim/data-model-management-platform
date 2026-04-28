# 핸드오프 027 — Pipeline / PipelineRun / PipelineAutomation 3 엔티티 분리 + 2안 run-time version 해석 (설계 문서)

> 최초 작성: 2026-04-23
> 상태: **설계만, 실구현 미착수.** 별도 브랜치에서 후속 세션에 진행 예정
> 계기: 026 automation 목업 진행 중 사용자 피드백 (이슈 5 — "pipeline 과 automation 은 분리되어야 한다")
> 선행 결정의 연장선:
>   - 023 §9-2 — Pipeline 엔티티 신규 도입 (옵션 1)
>   - 025 — Dataset 3계층 분리 (DatasetGroup → DatasetSplit → DatasetVersion)
> 선행 핸드오프 (main 머지 완료): `docs_for_claude/026-automation-mockup-completion-handoff.md`
> 설계 기준일 v7.9 (현행) 에 v7.10 승격 예정 (본 설계 확정 + 실구현 시점)

---

## 0. 이 문서의 목적

026 automation 목업에서 "Pipeline = Automation 엔트리" 로 동일시한 단일 엔티티 모델의 한계가 드러났다.
본 문서는 이를 **3 엔티티로 분리**하고, 동시에 **2안 (Pipeline 은 (group, split) 까지만 고정, version 은
run-time 해석)** 으로 전환하는 설계를 기록한다.

본 문서는 실구현 직전의 "착수 준비 체크리스트" 역할이다. 다음 세션에 별도 브랜치를 파고 이 문서의
§2 ~ §6 을 순서대로 구현한다.

---

## 1. 배경 / 필요성

### 1-1. 개념 분리의 필요 (사용자 피드백)

> "파이프라인과 automation 은 분리되어야지 않을까? 파이프라인은 일종의 템플릿이고, 파이프라인 수행
> 이력(데이터 변형에서)은 템플릿의 materialized run 이야. 파이프라인 automation 은 파이프라인의
> runner 같은 개념의 등록이고."

책임을 세 축으로 나누면 단일 테이블(023 §9-2) 대비 각 엔티티의 라이프사이클과 제약이 명확해진다.

| 엔티티 | 책임 | 생명 |
|---|---|---|
| `Pipeline` | 무엇을 할지 (task graph, input/output slot). 동일성의 단위 | 정적·**config immutable** |
| `PipelineRun` | 언제 어떤 버전으로 실제 실행됐는지 + 결과 | 동적·**immutable** (실행 후 read-only) |
| `PipelineAutomation` | 언제 자동으로 실행할지 (schedule / delta). Run 을 **만들어내는** runner | 정적·가변 (사용자 on/off) |

### 1-2. 025 Dataset 3계층 분리와 구조 정합

```
DatasetGroup (정적)
  └─ DatasetSplit (정적)          ← Pipeline.input_split / output_split 이 FK 로 참조 (2안)
      └─ DatasetVersion (동적)     ← PipelineRun.resolved_input_versions 에서 참조
```

Dataset 쪽의 "정적 슬롯 / 동적 버전" 분리가 Pipeline 쪽의 "정적 템플릿 / 동적 run" 분리와 1:1 매핑.
**구조적 동형성** 이 확보된다. 025 가 실은 이 2안을 자연스럽게 수용하도록 만든 선행 작업이었다.

### 1-3. 2안 (split 까지만 고정) 이 SSOT 규약으로 성립하는 이유

v7.8 `DatasetGroup.head_schema` SSOT 단일 원칙에 의해 **같은 그룹 안에서는 schema 가 절대 안 바뀐다**
(다르면 RAW 등록·파이프라인 출력 양쪽 진입로에서 `ValueError` 로 차단). Detection 도 task_types /
class mapping 이 group 단위로 고정.

즉 "version 이 바뀌어도 pipeline tasks 는 재해석 없이 돈다" 가 **설계서 수준에서 이미 보장**된다.
2안은 이 보장 위에서 성립한다.

---

## 2. 데이터 모델 — 3 엔티티 분리

### 2-1. `Pipeline` (정적 템플릿)

```python
class Pipeline(Base):
    __tablename__ = "pipelines"

    id: UUID                           # PK
    name: str                          # nullable=False. 사용자 명시 또는 output group 명 기반 자동 생성
    version: str                       # "major.minor" (e.g. "1.0"). §3 참조
    description: str | None            # 자동화 페이지에서 편집 가능 (목적 설명)
    input_split_id: UUID               # FK dataset_splits.id
    output_split_id: UUID              # FK dataset_splits.id
    config: dict                       # JSONB. task graph + params. 생성 후 immutable
    task_type: str                     # "DETECTION" | "CLASSIFICATION" | ... 운영용 스냅샷
    is_active: bool                    # soft delete. default=True
    created_at: datetime
    updated_at: datetime

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_pipeline_name_version"),
        Index("ix_pipelines_name_is_active", "name", "is_active"),
    )
```

**핵심 규약.**
- `config` 는 생성 후 **절대 수정 금지** (§6-1). 변경 필요 시 신규 Pipeline 행 생성
- `config` 에 `source:<split_id>` 만 들어감 (dataset_version_id 는 들어가지 않음 — 2안, §4)
- `task_type` 은 input_split 의 group 에서 도출한 스냅샷. group 의 task_types 가 바뀌어도 Pipeline
  자신의 task_type 은 생성 시점 값을 보존
- `is_active = False` 가 soft delete. hard delete 는 PipelineRun 의 FK 참조가 있어 불가

### 2-2. `PipelineRun` (동적 실행 이력)

기존 `PipelineExecution` 을 rename. 025 의 `Dataset → DatasetVersion` rename 과 동일 패턴.

```python
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"      # 기존 pipeline_executions → rename

    id: UUID
    pipeline_id: UUID                     # FK pipelines.id. 신규 NOT NULL
    automation_id: UUID | None            # FK pipeline_automations.id. automation 경로 전용
    resolved_input_versions: dict         # JSONB. {split_id: version} — run 시점에 해석된 input 버전
    output_dataset_version_id: UUID | None # FK dataset_versions.id
    status: str                           # PENDING / RUNNING / DONE / FAILED / SKIPPED_NO_DELTA / SKIPPED_UPSTREAM_FAILED
    current_stage: str | None
    processed_count: int
    total_count: int
    error_message: str | None
    celery_task_id: str | None
    task_progress: dict | None
    pipeline_image_url: str | None
    trigger_kind: str                     # manual_from_editor / automation_auto / automation_manual_rerun
    automation_trigger_source: str | None # polling / triggering / manual_rerun / NULL
    automation_batch_id: UUID | None
    transform_config: dict                # JSONB. 실행 시점의 최종 config 스냅샷 (resolved version 포함). 023 §9-2 옵션 c 유지
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
```

**핵심 규약.**
- 생성 후 **immutable**. status 전이 (PENDING → RUNNING → DONE 등) 는 허용하되, 실행 결과 필드는
  덮어쓰지 않음
- `transform_config` 스냅샷은 유지 — Pipeline 이 soft-deleted 되거나 config 가 모종의 이유로
  손상돼도 과거 run 의 해석·lineage view 는 이 스냅샷 하나로 가능 (023 §9-2 옵션 c)
- `resolved_input_versions` 는 UI 표시 / 재현 / delta 판정에 사용

### 2-3. `PipelineAutomation` (runner 등록, Pipeline 과 1:0..1)

```python
class PipelineAutomation(Base):
    __tablename__ = "pipeline_automations"

    id: UUID                              # PK
    pipeline_id: UUID                     # FK pipelines.id, UNIQUE (1:0..1 관계)
    status: str                           # stopped / active / error. default="stopped"
    mode: str | None                      # polling / triggering / NULL
    poll_interval: str | None             # 10m / 1h / 6h / 24h / NULL
    error_reason: str | None              # CYCLE_DETECTED / PIPELINE_DELETED / INPUT_GROUP_NOT_FOUND / ...
    last_seen_input_versions: dict        # JSONB. {split_id: version} — 자동 실행 성공 시 갱신
    created_at: datetime
    updated_at: datetime
```

**관계의 본질.**
- Pipeline 과 1:0..1 — automation 등록 여부 = row 존재 여부 (vs 단일 테이블의 NULL 컬럼)
- Automation 이 가리키는 Pipeline 이 soft-deleted 되면 §6-4 의 reassign 또는 자동 stopped 처리

---

## 3. 버전 정책 (확정 · 2026-04-23)

### 3-1. 형식 — `major.minor` (dataset 과 통일)

- 예: `"1.0"`, `"2.0"`, `"3.0"`
- 최초 생성 시 `"1.0"`
- 사용자가 "새 버전 생성" 을 누르면 **major 만 증가** (`1.0` → `2.0` → `3.0`)
- **minor 는 당분간 `0` 고정**. 향후 automation 경로 등에서 규칙이 필요해지면 그때 활성화 (자리만 남겨둠)
- "1.0 대신 1 로 해도 되지만 dataset 과의 통일 & 확장 여지" 를 위해 2-level 유지 (사용자 결정)

### 3-2. 생성 규칙 — **사용자 명시 only, hash 판정 없음**

> "버전은 pipeline 형태에 따른 hash 가 아닌, 사용자가 신규 버전 생성을 하면 그냥 만들어. 동일하던,
> 겹치던 상관 없어." — 2026-04-23 사용자 확정

- Pipeline 생성 UX 2종:
  1. **신규 파이프라인 생성**: 새 name + version = `"1.0"` 으로 저장
  2. **기존 파이프라인의 새 버전 생성**: 같은 name 선택 + version = 자동 `major++`
- **config 동일성 자동 판정 없음.** 동일 config 를 다른 version 으로 저장해도 OK. 겹쳐도 OK
- 유일 제약: `(name, version)` UNIQUE — 같은 name 에서 같은 version 번호 중복만 금지

**의도.** 시스템이 자동으로 version 을 올리는 경로가 없음 (Pipeline DAG 를 시스템이 건드릴 일 없으므로).
버전 증가는 오직 사용자의 명시적 행위.

### 3-3. Automation 과 version 의 관계

- `PipelineAutomation.pipeline_id` 는 **특정 version 의 Pipeline** 을 가리킨다 (family 가 아니라 row 참조)
- v1.0 에 자동화 등록되어 있고 사용자가 v2.0 을 만들면, automation 은 **계속 v1.0 에 붙어 있음**
- 사용자가 명시적으로 "automation 을 v2.0 으로 옮기기" 를 해야 v2.0 이 자동 실행됨 (§6-4 reassign)

**이유.** 자동 추종하면 사용자 모르게 자동 실행 동작이 달라지는 위험. 명시적 이동이 안전.

### 3-4. 과거 PipelineRun 복원 시 version 가시성

- PipelineRun → Pipeline FK → `(name, version)` 이 UI 에 자연 노출
- 예: "이 run 은 `helmet_merge v2.0` 으로 돌았구나" 가 한 눈에 보임
- UI 필터 / 정렬: Pipeline 목록에서 `name` 그룹 내 `version` desc 정렬 기본값

---

## 4. 2안 — Split 까지만 고정, version 은 run-time 해석

### 4-1. DataLoad 노드 spec 변경

현재 (026 baseline):

```ts
interface DataLoadNodeData {
  groupId: string | null
  split: string | null
  datasetId: string | null    // ← 제거 대상
  version: string | null      // ← 제거 대상
  ...
}
```

변경 후:

```ts
interface DataLoadNodeData {
  groupId: string | null
  split: string | null        // 여기까지만 파이프라인 spec
  ...
}
```

**영향 파일.**
- `frontend/src/pipeline-sdk/definitions/dataLoadDefinition.tsx`
- `frontend/src/pipeline-sdk/engine/graphToConfig.ts`
- `frontend/src/pipeline-sdk/engine/configToGraph.ts`
- 관련 store / 검증

### 4-2. PipelineConfig 스키마 — `schema_version: 2`

`source:<dataset_id>` → `source:<split_id>` 로 격상.

```jsonc
{
  "name": "...",
  "version": "1.0",
  "output": { "split_id": "...", "annotation_format": "COCO" },
  "tasks": {
    "t1": {
      "operator": "...",
      "inputs": ["source:<split_id>", "t0"],   // ← dataset_id 가 아니라 split_id
      "params": {...}
    }
  },
  "schema_version": 2
}
```

- `schema_version: 1` (현행) 과의 호환: `matchFromConfig` 에서 분기. v1 config 은 **placeholder
  파이프라인** 으로 복원 (읽기 전용, 재실행 차단). `pipeline-sdk` 의 placeholder 노드 패턴 재활용
- v1 → v2 migrator 는 만들지 않음 (YAGNI). 실질적으로 v1 은 레거시

### 4-3. 실행 제출 UX — Version Resolver Modal

에디터의 "실행" 버튼 클릭 → 중간 Modal 이 끼어든다:

```
┌─ 실행 전 입력 버전 확인 ────────────────┐
│ source: hardhat_raw / VAL               │
│   최신 버전: 2.1  (기본값)              │
│   다른 버전 선택: [1.0, 2.0, 2.1 ▼]    │
│                                          │
│ source: visible_added / VAL             │
│   최신 버전: 3.0  (기본값)              │
│   ...                                    │
│                                          │
│              [취소]  [이 버전으로 실행] │
└─────────────────────────────────────────┘
```

- 기본값: 각 source split 의 최신 DatasetVersion
- 사용자가 이전 버전으로 돌려보고 싶으면 드롭다운에서 선택
- 확정 시 `POST /pipelines/{id}/runs { resolved_input_versions: {...} }`

### 4-4. Automation 경로의 version 해석

- polling / triggering / manual_rerun 공통: 각 source split 의 **최신 DatasetVersion** 을 항상 사용
- delta 판정: `current_latest_versions` vs `PipelineAutomation.last_seen_input_versions`
- 수동 재실행 `force_latest` 모드: delta 무시, 최신으로 강제 실행

---

## 5. 마이그레이션 — 전략 2 (엄격 비교, N → N legacy Pipeline)

### 5-1. 선택 근거

- **전략 1 (정규화 후 해시)**: 비의미 필드 판정이 어려워 오매칭 위험
- **전략 2 (엄격, N → N legacy Pipeline)**: 안전, 단순. Pipeline 목록에 legacy 많아 보일 수 있음 →
  **legacy 필터** 로 해결
- **전략 3 (단일 Legacy Pipeline 에 몰아넣기)**: 대표 config 가 임의 execution 의 것이 되어 해석 불명확

**채택: 전략 2 + legacy 숨기기 필터 (기본 ON)**.

### 5-2. 마이그레이션 순서 (Alembic 031+ 예정)

1. `pipelines` 테이블 CREATE + `pipeline_automations` 테이블 CREATE
2. 기존 `pipeline_executions.transform_config` 의 구조적 부분을 `pipelines.config` 로 복사
   - 1 execution = 1 Pipeline (legacy)
   - `pipelines.name = "legacy_{execution_id[:8]}"`, `version = "1.0"`
   - `pipelines.config = <execution.transform_config 의 정규화된 subset>` (resolved version 을 제외한
     구조적 필드만)
   - `pipelines.is_active = FALSE` 로 설정 (legacy 는 수정 / 신규 run 제출 금지)
3. `pipeline_executions` 에 `pipeline_id UUID` 컬럼 추가 + 백필 (execution → legacy pipeline 1:1 매핑)
4. `pipeline_executions` → `pipeline_runs` RENAME (PostgreSQL RENAME 으로 외부 FK 자동 추종)
5. `pipeline_runs.pipeline_id NOT NULL` + FK 제약 추가
6. `pipeline_runs.resolved_input_versions` JSONB 추가 + 기존 transform_config 에서 추출 백필
7. `pipeline_runs.automation_id` 컬럼 추가 (nullable, 기본 NULL)
8. downgrade: 역순 (단, legacy 경로가 있으므로 엄격히 되돌리려면 Pipeline 데이터 drop 후 execution 원상)

### 5-3. `is_active=FALSE` legacy Pipeline 처리

- Pipeline 목록 기본 필터에서 숨김
- 상세 페이지 진입은 가능 (과거 run 확인용)
- automation 등록 불가, 새 run 제출 불가
- UI 배지: "legacy" 명시

---

## 6. 생명주기 / 제약

### 6-1. `Pipeline.config` immutable

생성 후 절대 수정 금지. 엔드포인트 레벨에서 `PATCH /pipelines/{id}` 가 `config` 필드를 받지 않음.
사용자가 변경하려면 새 버전 또는 새 이름으로 생성.

### 6-2. Pipeline soft delete

- `is_active` = False 로 전환 (row 유지)
- 삭제된 Pipeline 은 목록 기본 필터에서 숨김
- 과거 PipelineRun 의 `pipeline_id` 참조는 유효
- PipelineAutomation 이 붙어 있으면 §6-4 처리

### 6-3. PipelineRun immutable

- 상태 전이 (PENDING → RUNNING → DONE/FAILED/SKIPPED) 는 허용
- 실행 완료 후 결과 필드 (`output_dataset_version_id`, `transform_config`, `started_at`, `finished_at`)
  덮어쓰기 금지

### 6-4. Automation 이 가리키는 Pipeline 이 삭제되면

1. Pipeline soft delete 순간, 연결된 PipelineAutomation.status 를 `error`, error_reason =
   `PIPELINE_DELETED` 로 전환
2. UI 에 알림 / 배지 노출
3. 사용자 선택지:
   - (a) Automation 의 `pipeline_id` 를 **유효한 다른 Pipeline 으로 reassign** — 설정 유지 + 대상만 교체
   - (b) Automation 삭제 후 새 Pipeline 에 새 Automation 생성
- (a) 가 "v1 → v2 승격 후 automation 그대로" 같은 일상 시나리오에 필요

### 6-5. PipelineRun 의 `automation_id` nullability

- manual_from_editor: `automation_id = NULL`
- automation_auto / automation_manual_rerun: `automation_id = NOT NULL`
- Automation 이 삭제되면 해당 Automation 의 기존 Run 들은 `automation_id` 를 유지해도 되고 (이력은
  Automation 이 가리켰던 과거 시점 정보) nullify 해도 됨 — **유지 추천** (과거 사실의 불변성)

---

## 7. 후보 개념 — 이번 범위에서 차용 보류

### 7-1. Pipeline Group (사용자 명시 "함께보기" 묶음)

> "pipeline 의 group 을 만들어서 완전히 동일 input/output group 인데 split 만 다른 것을 관리할 수 있게
> 하면 좋겠어. 저런 경우를 자동으로 검출해야 하는건 아니고 저런 경우에만 쓸 수 있는것도 아니야. 다만
> 사용자가 볼 때 아 얘네들은 관련된 아이들이구나. 하고 쉽게 알고 쓸 수 있도록." — 2026-04-23

- 사용자가 수동으로 여러 Pipeline 을 하나의 Group 으로 묶는 **즐겨찾기 / 함께보기** 수준의 기능
- 예: `hardhat_merge_train`, `hardhat_merge_val`, `hardhat_merge_test` 3 파이프라인을 `"hardhat_merge"`
  Group 으로 묶어 목록에서 함께 표시
- 자동 검출 / 강제 사용 아님
- **차용 보류**. 필요해지면 `pipeline_groups` + `pipeline_group_members` 조인 테이블 추가만으로 가능
  (구조 brake 없음)

### 7-2. Pipeline Family (name rename 대응 계통)

- 같은 Pipeline 의 "계통" 을 연결하는 장치
- 이름이 바뀐 경우 (예: `helmet_merge` → `helmet_merging`) 도 같은 계통으로 묶고 싶을 때 필요
- 현재는 `(name, version)` + 목록 정렬로 계통이 보이므로 불필요
- **차용 보류**. 필요해지면 `family_id` 컬럼만 후행 추가 (구조 brake 없음)

### 7-3. config 해시 기반 동일성 자동 판정

- 023 §9-2 옵션 a 안 1 에서 채택됐던 메커니즘
- 2026-04-23 사용자 결정으로 **채택하지 않음** — "동일하던 겹치던 상관없음"
- 필요해지면 나중에 `config_hash` 컬럼 + 중복 경고 UI 추가 가능

---

## 8. 영향 범위 스케치

### 8-1. 백엔드

- `backend/app/models/all_models.py` — Pipeline / PipelineAutomation 신규, PipelineExecution →
  PipelineRun rename
- `backend/app/models/events.py` — 전파 리스너 (필요 시)
- `backend/app/services/pipeline_service.py` — Pipeline CRUD, 버전 증가 로직, run 제출 resolver
- `backend/app/services/dataset_service.py` — `_next_version` 는 무영향 (Dataset 쪽 유지)
- `backend/app/tasks/pipeline_tasks.py` — run 실행 시 pipeline_id / automation_id 기록
- `backend/app/api/v1/pipelines/` — 신규 엔드포인트:
  - `POST /pipelines` (Pipeline 생성)
  - `POST /pipelines/{id}/runs` (run 제출, resolved_input_versions 인자)
  - `GET /pipelines`, `GET /pipelines/{id}`, `PATCH /pipelines/{id}` (description / is_active 수정만)
  - `POST /pipelines/{id}/automation` (automation 등록/수정)
  - `POST /pipelines/{id}/automation/rerun`
- `backend/migrations/versions/` — 031 신규 (§5-2)

### 8-2. 프론트엔드

- `frontend/src/types/pipeline.ts` — Pipeline / PipelineRun / PipelineAutomation 타입 신규
- `frontend/src/types/automation.ts` — 026 목업 타입을 실 타입에 맞춰 align
- `frontend/src/pipeline-sdk/definitions/dataLoadDefinition.tsx` — §4-1 DataLoad 노드 spec 축소
- `frontend/src/pipeline-sdk/engine/graphToConfig.ts` / `configToGraph.ts` — schema_version=2
- `frontend/src/pages/PipelineHistoryPage.tsx` → `/pipelines` 트리 재설계:
  - `/pipelines` (Pipeline 목록)
  - `/pipelines/:id` (Pipeline 상세 — 파이프라인 구성 + 해당 Pipeline 의 Run 이력)
  - `/pipelines/runs` (전체 실행 이력)
- 사이드바 "데이터 변형" 하위에 `파이프라인 목록` + `파이프라인 실행 이력` 2개
- 에디터 "실행" → Version Resolver Modal 삽입
- Automation 메뉴는 유지 (026 에서 구축된 UI 를 3 엔티티에 맞춰 재배선)

### 8-3. seeds / fixture

- 백엔드 seed 는 영향 없음 (manipulator seed 만 존재, Pipeline seed 는 없음)
- 026 목업 fixture (`frontend/src/mocks/automation.ts`) 는 3 엔티티에 맞춰 재작성

---

## 9. 진행 순서 제안 (별도 브랜치에서)

후속 세션 착수 순서. 브랜치명은 `feature/pipeline-run-automation-separation` 정도.

1. **Alembic 마이그레이션 031** (§5-2) — 스키마 변경 + legacy 백필. 왕복 왕복 테스트
2. **ORM + 서비스 레이어** — Pipeline / PipelineRun / PipelineAutomation 모델 + 신규 엔드포인트 최소 집합
3. **DataLoad 노드 spec 축소** — v1 → v2 schema_version 분기, placeholder 복원
4. **Version Resolver Modal** — 실행 제출 단계 UX
5. **페이지 재배선** — /pipelines 목록 / /pipelines/:id 상세 / /pipelines/runs
6. **Automation 메뉴 재연결** — 026 목업의 UI 를 실 API 에 맞춰 재사용. mock 레이어 제거
7. **legacy 필터 + Pipeline 삭제 / automation reassign UX**
8. **회귀 테스트 + 핸드오프 027 완료 기록 갱신**

---

## 10. 미결 / 실구현 진입 전 추가 결정 필요

**2026-04-24 착수 준비 세션에서 본 §의 4건 전부 해소 + 파생 이슈 3건 추가 결정 — §12 참조.**

- **Pipeline 생성 UX의 구체적 동선** — 에디터에서 "실행" 이 아닌 "저장 + 실행 분리" 가 필요한가?
  - 현 데이터 변형 탭은 "에디터에서 실행" 단일 경로. 저장 분리 필요 시 UI 확장
- **Pipeline name 정책** — 자유 문자열인가, output group 명 기반 권장인가? 023 §9-3 에서는 "수동 입력
  + 자동 생성 둘 다 허용" 이었음. 기본값을 output group 명으로
- **`PipelineRun.automation_id` 를 Automation 삭제 시 유지 / nullify** — §6-5 는 유지 추천이지만
  구현 편의 따라 재결정 가능
- **Pipeline description 편집 권한** — 상세 탭에서 누구나 편집? 목업(026) 은 자유 편집으로 가정.
  실 구현에서 RBAC 이 들어오면 그때 결정

---

## 11. 참조

- 설계서 (현행): `objective_n_plan_7th.md` (v7.9)
- 023 자동화 기술 검토 + §9 결정: `docs_for_claude/023-automation-mockup-tech-note.md`
- 025 Dataset 3계층 분리 (완료): `docs_history/handoffs/025-dataset-three-tier-separation-handoff.md`
- 024 head_schema SSOT: `docs_history/handoffs/024-head-schema-ssot-enforcement-handoff.md`
- 026 Automation 목업 (이 문서의 직접 계기): `docs_for_claude/026-automation-mockup-completion-handoff.md`
- 노드 SDK 가이드: `docs/pipeline-node-sdk-guide.md`

---

## 12. 실착수 전 최종 결정 (2026-04-24 세션)

§10 미결 4건 해소 + 파생 이슈 3건 (E / H / M) 확정. 다음 세션부터 §9 의 9단계 구현에 순차
착수. 브랜치 `feature/pipeline-run-automation-separation` 이미 생성됨 (main 985acc2 기준,
커밋 없음).

### 12-1. Pipeline 생성 / 실행 UX — 저장/실행 완전 분리 (§10-A 확정)

- **에디터 역할**: 순수 편집기. "저장" 만 수행. 에디터 안에 "실행" 버튼 없음.
- **Load Node UI 는 1원화 유지** — DAG 구성용 하나만. `(group, split)` 까지만 입력. DAG 전체
  복원이나 실행 전용 Load Node ver2 UI 는 만들지 않는다.
- **실행 버튼 위치** — Pipeline **목록 각 행 우측** 에 "실행" 버튼. 클릭 시 모달 / 드로워 /
  별개 페이지 (구현 편의 우선) 로 `source:<split_id>` 각각에 대해 version 드롭다운만 받고
  dispatch. `is_active=FALSE` (legacy) Pipeline 은 버튼 비활성.
- **기본 기능 우선** — "저장 후 실행" 병치, 에디터 내부 실행 등 편의 기능은 기본 flow 가
  돌아간 뒤 별도 판단.

### 12-2. Pipeline name 자동 생성 규칙 (§10-B 확정)

- **자동 생성 기본값**: `{output_group_name}_{output_split}` (예: `hardhat_merged_train`)
- **충돌 시**: 같은 `(name, version)` 이 이미 있으면 뒤에 숫자 suffix 자동 추가
  (`_2`, `_3`, ...)
- **변경 시점**: 에디터 저장 전 / Pipeline 생성 후 상세에서 언제든 rename 가능.
  `Pipeline.config` immutable 규약과 별개 (name 은 수정 허용).
- 자동 생성 rule 은 formatted string 한 줄이므로 사용해 보고 쉽게 조정.

### 12-3. PipelineAutomation soft delete (§10-C 확정)

- 027 §2-3 `PipelineAutomation` 에 컬럼 추가: `is_active: bool = True`,
  `deleted_at: datetime | None`
- **FK 제약 그대로 유지** — dangling 아님. 과거 `PipelineRun.automation_id` 참조는 row 가
  살아있으므로 영원히 유효. 과거 사실 완전 불변 보존 + DB 무결성 유지.
- 목록 기본 필터 `is_active=TRUE`. 삭제 = `is_active=FALSE` + `deleted_at=NOW()`.
  재활성화 가능.
- Pipeline 의 soft delete 패턴(§6-2) 과 대칭.
- `ON DELETE SET NULL` 은 차선책으로 검토됐지만 soft delete 가 "과거 사실 불변" 의도에
  더 부합해 본 안 채택.

### 12-4. RBAC 없는 자유 편집 (§10-D 확정)

- Pipeline description / name 은 인증 없이 누구나 편집. 인증 레이어는 이후 세션.
- `updated_at` 자동 갱신으로 audit 충분.

### 12-5. 저장 시점 vs 실행 시점 검증 책임 분리 (파생 E)

기존 `pipeline_service._validate_with_database` 를 두 단계로 쪼갠다. §12-1 "Load Node UI
1원화" + "실행 모달은 version 드롭다운만" 이 성립하려면 이 분리가 전제.

- **저장 시점 (`validate_structural`)** — version 무관한 구조적 검증 전부:
  - §2-8 head_schema SSOT 비교 (`_validate_output_schema_compatibility`)
  - §2-11-2 cls_add_head duplicate (`_validate_cls_add_head_duplicates`)
  - `cls_filter_by_class` / `cls_set_head_labels_for_all_images` compat 정적 검증
  - DAG 토폴로지 / sink 유일성 등 구조 검증
- **실행 시점 (`validate_runtime`)** — `resolved_input_versions` 기준:
  - 선택된 DatasetVersion 이 존재 + READY 상태인지
  - `resolved_input_versions` 의 `split_id` 가 Pipeline 의 `input_split` 과 일치하는지

이 분리 덕분에 실행 모달은 정말 "version 드롭다운 + 실행" 버튼만으로 충분.

### 12-6. Automation reassign — 자동 처리 X, 노티만 (파생 H)

v1 → v2 새 버전 생성 시, automation 은 v1 에 그대로 유지 (§3-3 원칙 재확인). 다만 사용자
인지를 돕기 위해:

- 새 버전 생성 완료 시점 / 새 버전 상세 페이지 진입 시 **"이 Pipeline 계열에 Automation 이
  v<old> 에 등록돼 있습니다 — v<new> 로 이동할지 확인하세요" 노티** 1회 표시
- 자동 이동 / 강제 모달은 **하지 않음** — 사용자가 의도적으로 유지 / 이동 판단
- 실제 이동은 기존 Automation 상세의 "Pipeline reassign" UX(§6-4) 로 수행

**이유.** 자동 이동은 호의처럼 보이지만 사용자가 의도하지 않은 자동 실행 동작 변경을
유발할 수 있다. 이런 경우 **노티만 띄워 선택권을 사용자에게 남기는 것이 안전**.

### 12-7. Pipeline 생성 시 output DatasetGroup / DatasetSplit 선행 생성 (파생 M)

**문제.** 027 §2-1 은 `output_split_id FK NOT NULL` 이지만, SOURCE / PROCESSED / FUSION
output 은 대개 파이프라인 실행으로 **처음 생성**되므로 Pipeline 저장 시점에 DatasetSplit
(그리고 상위 DatasetGroup) 이 존재하지 않는 경우가 많다. split 만이 아니라 **group 도 없는
상태에서 최초 group + split 이 같이 생기는 케이스** 가 일반적.

**확정 — 저장 시점에 output DatasetGroup → DatasetSplit 순서대로 자동 생성**:

- Pipeline 저장 시 output `(group_name, split)` 이 DB 에 없으면 **DatasetGroup 먼저,
  이어서 DatasetSplit 자동 생성**. head_schema / class 구성은 Pipeline config 에서
  `preview_head_schema_at_task` 로 저장 시점에 이미 결정 가능 → group 의 `head_schema`
  / `task_types` / `dataset_type` 도 같은 시점에 채워짐.
- 실제 DatasetVersion 은 파이프라인 실행이 있어야 생성됨. 저장 후 첫 실행 전까지는
  "빈 group + 빈 split (version 0 건)" 상태.
- 025 의 "split = 정적 슬롯" 원칙과 일치 — 한 번 만들어진 슬롯은 version 이 쌓여도 재사용.

**빈 그룹의 목록 노출 — 별도 로직 없이 그대로 보여준다.**

- "등록된 그룹은 반드시 데이터가 있다" 는 규약은 **원래 없었다** — 단순히 RAW 등록만 해온
  결과로 우연히 그렇게 보였을 뿐.
- 그룹 목록 UI 는 빈 그룹도 그대로 노출. `dataset_count=0`, `total_image_count=0` 으로
  자연스럽게 표시됨.
- 사용해 보고 UX 가 혼란스럽다고 판단되면 이후 filter / badge 추가. **중복 개발 예상
  되는데 목업이라도 미리 만들어 둬야 하는 케이스가 아니면, 일단 그대로 간다.**

**구현 위치.** `pipeline_service.create_pipeline` 내부에서 025 에서 만든 헬퍼를 재사용:
- `dataset_service._get_or_create_group(name, dataset_type, task_types, head_schema)` —
  없으면 생성, 있으면 SSOT 비교 후 재사용 (§2-8 강제)
- `dataset_service._get_or_create_split(group_id, split)` — 025 기존 헬퍼

### 12-9. Pipeline input / output 카디널리티 — 비대칭 확정 (파생 N)

착수 단계에서 현 DB 의 `pipeline_executions.config` 를 점검하며 발견한 이슈. §2-1 원안은
`input_split_id: UUID FK NOT NULL` 로 단일 input 을 가정했으나, 실제 파이프라인은
`det_merge_datasets` / `cls_merge_datasets` 등 **multi-input 이 흔하다** (현 DB 의 execution
57건 중 merge 체인 다수).

**3 안 비교 후 C 채택**:

- **(A) 원안 유지 — `input_split_id` 단일 FK (대표 input)** — multi-input 시 "대표" 를 임의로
  고르는 것이 애매하고 legacy 백필도 어렵다. 탈락
- **(B) M:N 조인 테이블 `pipeline_inputs(pipeline_id, split_id)`** — SQL 정석. 다만 Pipeline.
  config 가 immutable(§6-1) 이라 denormalization 동기화 부담이 원천 차단되므로 B 의 정석적
  이점이 실은 약하다. Alembic 테이블 1개 + 생성 경로마다 iterate/insert 부담
- **(C) top-level FK 제거, `config.tasks[*].inputs` 의 `source:<split_id>` 만으로** — 채택

**C 채택 근거**:

1. **JSON copy 기반 흐름 친화** — Pipeline 클론(새 버전 생성) / PipelineRun 스냅샷 생성 모두
   JSONB deep copy 한 번으로 끝남. B 로 가면 매번 `pipeline_inputs` iterate/insert 수반
2. **저장 경로 수렴** — `config.tasks[*].inputs` 가 유일 진리. 이중화 없음
3. **Alembic 단순화** — 테이블 1개 덜 만듦
4. **나중에 B 로 확장 가능** — Pipeline.config immutable 이므로 필요 시점에 `pipeline_inputs`
   만들고 한 번 백필하면 끝. 하루짜리 작업

**C 채택 시 추가 작업**:

- `lib/pipeline/config.py` 에 `extract_source_split_ids(config) -> list[str]` 순수 헬퍼 함수.
  chaining 분석기 / automation triggering 훅 / "이 split 을 쓰는 Pipeline 찾기" UI filter 에서
  재사용
- **GIN 인덱스는 당장 만들지 않음** — 현 규모(수십 개 Pipeline) 에서 불필요. JSONB 스캔으로
  충분. 성능 이슈 발생 시
  `CREATE INDEX ix_pipelines_config_gin ON pipelines USING GIN (config jsonb_path_ops);`
  한 줄 추가로 해결. 해당 위치에 주석으로 명시

**비대칭 유지 — output 은 여전히 단일 FK**:

`Pipeline.output_split_id` 는 NOT NULL FK 그대로. output 은 항상 단일 DatasetVersion 을
생성하므로 FK 가 자연스럽다. **"싱글은 FK, 복수는 JSONB"** 원칙.

**미래 확장 — multi-output 의 경우 (보류, 별개 개념 예정)**:

Palantir Foundry 의 data pipeline 은 여러 논리 파이프라인을 한 파일에 모아 정의하고 실제
실행은 단일 단위로 뽑아 쓰는 형태. 우리도 multi-output 이 필요해지는 시점이 오면 현재
`Pipeline` 모델을 확장하지 않고 **`PipelineSet` 같은 상위 개념을 별개 엔티티로** 도입해 여러
Pipeline 을 묶는 것으로 처리. 이번 범위 밖.

### 12-8. 현재 상태 스냅샷 (최신 갱신: 2026-04-28 v1 legacy 코드 제거 + UI 스모크 통과)

- **브랜치** — `feature/pipeline-run-automation-separation` (10 commits 누적)
- **머지 대상** — 현행 `main = 985acc2`
- **§9 진행 상황**:
    - ✅ §9-1 Alembic 031 (3 엔티티 테이블 + FK 제약. legacy 백필 SQL 은 v1 제거 시 삭제됨)
    - ✅ §9-2 ORM rename + 신규 모델
    - ✅ §9-3 서비스 + 라우터 MVP — Pipeline CRUD + Automation 서비스 + submit_run
    - ✅ §9-4 schema_version 2 전환 — backend config + FE DataLoad 축소
    - ✅ §9-5 Celery executor 치환 — `_substitute_resolved_versions` 가
      `source:<split_id>` → `source:<dataset_version_id>` 해석. transform_config 스냅샷도
      이 resolved dict. executor 코드 무변경
    - ✅ §9-6 Version Resolver Modal — `components/pipeline/VersionResolverModal.tsx`.
      config 에서 source split 추출 + 최신 버전 드롭다운 + `POST /pipelines/entities/{id}/runs`
    - ✅ §9-7 `/pipelines` 재배선 — PipelineListPage (신규), `/pipelines/runs` (기존 이력).
      "새 파이프라인" 버튼은 이력이 아닌 목록에 위치 (CreatePipelineButton 공통 컴포넌트)
    - ✅ **§9-8 일부 / 사용자 UI 스모크 누적 fix** (2026-04-28):
      - DAG 검증 / 스키마 프리뷰 v2 schema_version 지원
      - 검증/실행 API 422 → friendly issue 변환 (Pydantic 형식 오류 우회)
      - operator 노드 inputs:[] root cause (`buildInputsFromIncoming` v1 잔재)
      - classification head schema 노드 클릭 시 표시
      - detection RAW 등록 MissingGreenlet (split=req.split)
      - `_intersect_source_task_types` v1/v2 분기로 task_types 자동 채워짐
      - `submit_run_from_pipeline` 에 deleted 그룹 자동 복구 + task_types 백필
      - `/next-version` 엔드포인트 시그니처 불일치 (1.0 fallback 버그)
    - ✅ **v1 legacy 호환 코드 전수 제거** (2026-04-28, commit 45eb23d):
      - DB 초기화 후 v1 데이터 부재 시점에 사용자 결정으로 진행
      - 17 파일, +246/-696 (450 줄 감소)
      - schema_version=2 단일 가정. is_schema_v2 / passthrough_source_dataset_id (FE) /
        get_all_source_dataset_ids 의 v1 분기 / Alembic 031 의 legacy 백필 SQL 모두 제거
      - `passthrough_source_dataset_id` 필드는 backend 에 남아있되 의미 재정의 — FE 가
        보내지 않고 submit 단계에서 backend 가 채우는 resolved 필드 (executor 호환용)
    - ⬜ §9-8 Automation 메뉴 실 API 연결 — 다음 세션 (026 mock fixture → 실 엔드포인트)
    - ⬜ §9-9 핸드오프 028 + 설계서 v7.10 승격 — 다음 세션 (이 세션에서 §12-8 만 갱신)
- **사용자 검증 완료**:
  - RAW 등록 (detection / classification 양쪽)
  - DAG 노드 (cls_sample_n_images 등) 정상 작동
  - 실행 이력 e8a54621 / 466382fc 정상 완주, 출력 데이터셋 그룹 노출 / task_types 채워짐
- **남은 사용자 피드백 (Pipeline 작업 외)**:
  - **#1 파이프라인명 입력 곳 안 보임** — 중요도 낮음. 에디터에 name 입력 UI 추가 필요
  - **#2 저장 vs 실행 분리** — §12-1 핵심 UX. `POST /pipelines/entities` 신설 + 에디터
    "실행" → "저장" 라벨 변경 필요. UX 큰 변경이라 별도 세션
- **§9-3 에 포함하지 않고 §9-4 로 미룬 작업**:
    1. `validate_structural` / `validate_runtime` 명시적 분리 (§12-5) — 현재 기존
       `_validate_with_database` 가 여전히 잘 도는 상태이고, 분리의 이점은 schema_version=2
       "source:<split_id>" 전환과 함께 와야 자연스러움
    2. `POST /pipelines/entities` (명시적 Pipeline 저장 엔드포인트, §12-1) — 현재
       `submit_pipeline` 의 임시 `_get_or_create_pipeline_for_submit` 가 Pipeline 을 자동
       생성 중. FE 가 "저장/실행 분리" 로 전환되면 이 엔드포인트를 신설하고 임시 로직 제거
- **§9-3 구현 결과 엔드포인트** (모두 `/api/v1/pipelines` 하위):
    - `GET /entities` / `GET /entities/{id}` / `PATCH /entities/{id}` — Pipeline CRUD
    - `GET /entities/{id}/runs` / `POST /entities/{id}/runs` — Pipeline 별 run 이력 + submit
    - `GET /automations` / `PUT /entities/{id}/automation` / `GET /entities/{id}/automation`
    - `DELETE /automations/{id}` — soft delete (§12-3)
    - `POST /automations/{id}/reassign?new_pipeline_id=...` — §6-4 (a)
    - `POST /automations/{id}/rerun` — 수동 재실행 if_delta / force_latest (§4-4 / 026 §5-2a)
    - 기존 `POST /execute` / `GET /{id}/status` / `GET /` (run list) 도 유지 — FE 호환
- **§10 미결 4건** — 전부 §12-1 ~ §12-4 에서 해소 (파생 E/H/M/N 추가 결정 §12-5 ~ §12-9)
- **재개 시 참조 순서**: §12 (본 절, 최종 결정) → §9 (진행 순서 9단계) → §2 ~ §6 (엔티티 /
  버전 / 마이그레이션 / 생명주기) → §8 (영향 범위 상세)

- **UI 스모크 테스트 가이드 (현재 단계 — §9-7 완료 후, §9-8 전)**:
  브라우저 `http://localhost:18080/pipelines` 에서 아래 항목 확인:
  1. **목록 페이지 진입** — 사이드바 "데이터 변형" > "파이프라인 목록" 클릭 시 PipelineListPage
     렌더. 기본 필터 `is_active=TRUE` 이라 legacy 57건은 숨김 — 현재는 active Pipeline 이
     0건이라 빈 목록 (이것이 정상). legacy 포함 토글 ON 하면 57건 표시
  2. **legacy Pipeline 활성화** — legacy 행 "복원" 버튼 클릭 → is_active=TRUE 전환 →
     "실행" 버튼이 활성화됨 (색상 변화 확인)
  3. **실행 제출** — 활성 Pipeline 행 "실행" 버튼 클릭 → Version Resolver Modal 열림.
     각 source split 마다 버전 드롭다운이 최신 값으로 기본 선택되어야 함. "이 버전으로 실행"
     클릭 시 success 메시지 + Modal 닫힘. 백그라운드에서 Celery dispatch
  4. **실행 이력 확인** — 사이드바 "실행 이력" 이동 → 방금 제출한 run 이 RUNNING 또는 DONE 으로
     표시되어야. pipeline.png 생성 확인
  5. **에디터에서 저장** — `/pipelines/editor?taskType=DETECTION` 진입 → DataLoad 노드에
     그룹 + split 만 선택 (버전 Select 없음 — §12-1 확인). Save 노드까지 연결 후 "실행"
     클릭 시 기존 submit_pipeline 경로가 새 Pipeline 생성 + run dispatch. 새 Pipeline 이
     파이프라인 목록에 active 로 나타나야 함
  6. **automation 목업 페이지는 아직 목업 데이터** — `/automation` 은 §9-8 전까지 mock
     fixture. 실 Pipeline 과 연결 안 됨 — 다음 세션에서 교체

- **재개 시 체크리스트 (§9-8 이어서 · 다음 세션)**:
    1. §9-8 `api/automation.ts` mock 레이어 제거 → `pipelineEntitiesApi` /
       `pipelineAutomationsApi` 호출 + adapter 로 기존 목업 Pipeline 타입 형태로 변환.
       chaining / upstream delta / execution batch 는 당분간 빈 응답 (§16 실구현 전)
    2. §9-8 AutomationPage / AutomationPipelineDetailPage / AutomationHistoryPage 가
       실 API 응답 구조에 맞춰 동작하는지 확인
    3. §9-8 §12-6 — 새 Pipeline 버전 생성 시 automation 이 v1 에 그대로 있음 노티 추가
    4. §9-9 legacy 필터 기본 ON 배지 완성 + FE 후속 정리 (`DatasetSummary.pipeline_execution_id`
       → `pipeline_run_id` 이름 일치, v1 config 복원 시 legacy 설명 Alert)
    5. §9-9 UI 스모크 피드백 반영 후 backend 446/446 + FE tsc 재확인
    6. §9-9 핸드오프 028 작성 + 설계서 v7.10 승격 + CLAUDE / MEMORY 포인터 갱신

- **§9-5 ~ §9-7 에서 남긴 후속 정리 (지금은 정상 동작, 기록만)**:
    - v1 legacy config 상세 진입 시 엣지 복원 미완 (DataLoad 노드가 v2 만 수거). is_active=FALSE
      라 실행 불가이므로 기능상 문제 없음
    - FE `DatasetSummary.pipeline_execution_id` 필드는 이제 API 가 `pipeline_run_id` 로
      내려주므로 undefined. UI 영향 없지만 타입 이름 일치는 §9-9 에서 정리
    - validate_structural / validate_runtime 명시 분리 (§12-5) 는 실행 시점 runtime 검증이
      이미 `submit_run_from_pipeline` 안에 있어 기능상 필요성이 낮음. 별도 세션으로 미룸
    - Pipeline 상세 페이지 (`/pipelines/:id`) 는 아직 없음. 목록에서 실행/legacy 토글/description
      편집 가능한 정도로 충분. §9-9 에서 필요 시 추가

> **§13 이후는 후속 브랜치 `feature/pipeline-family-and-version` 의 결정 + 구현 기록.**
> 027 의 §12 까지가 본문 (Pipeline / PipelineRun / PipelineAutomation 3 엔티티 분리)
> 이고, §13 은 그 위에 쌓인 후속 단계: Pipeline 자체를 (Family + concept + version) 으로
> 다시 한 번 분리하면서 source format 도 v3 로 격상.

---

## 13. 후속 — Pipeline Family + Version 3계층 + source format v3 (2026-04-28)

027 §12 까지로 Pipeline / PipelineRun / PipelineAutomation 3 엔티티 분리는 완료됐다.
이 §13 은 사용자 피드백을 받아 **Pipeline 자체를 다시 한 번 3계층으로 분리** 하고,
동시에 PipelineRun JSON 복사 → 에디터 import 흐름의 모호성을 해소하기 위해 **source
토큰 포맷을 v3 로 격상** 한 작업의 결정 + 구현 기록이다.

### 13-1. 동기 — 두 가지 사용자 피드백

1. **"Pipeline 클릭이 안 돼서 뭘 하는 건지 알기 힘들다"** — 027 까지의 Pipeline 목록은
   행을 클릭해도 상세 정보가 보이지 않아, 사용자가 PipelineRun 상세의 "JSON 복사" 로
   템플릿을 우회 복제하고 있었음.
2. **JSON 복사로 복원할 때 split not found 에러** — PipelineRun.transform_config 는
   resolved 스냅샷이라 `source:<dataset_version_id>` 를 담고 있는데, Pipeline.config 측
   에디터는 같은 토큰을 split_id 로 해석. 같은 모양인데 의미가 달라 에디터가 split 으로
   조회 → DB 에 없어 실패.

### 13-2. 핵심 결정 — 사용자와 함께 합의 (2026-04-28)

| 항목 | 결정 |
|---|---|
| Pipeline 의 versioning | Pipeline 자체에 `version` 컬럼 두지 않고 **PipelineVersion 별도 테이블** 분리. 같은 version 은 같은 Pipeline 안에서만 누적, 다른 Pipeline 으로 이동 불가 |
| Family 의 의미 | **즐겨찾기 폴더** — 자유 이동 가능한 느슨한 묶음. DatasetGroup 처럼 강제력 있는 묶음 아님. Pipeline.family_id 는 NULL 허용 |
| name UNIQUE 범위 | family 와 무관하게 **전역 UNIQUE** (Pipeline 이 family 간 자유 이동하므로 name 으로 식별) |
| source 포맷 | `source:<UUID>` → `source:<type>:<UUID>` 로 격상. type ∈ {`dataset_split`, `dataset_version`} |
| Pipeline 상세 진입 | 행 클릭 = 우측 drawer (versions 세로 목록 + 인라인 expand). "상세" 버튼 = 풀 페이지 (`/pipeline-versions/:id`) |
| schema_version | 2 → 3 으로 bump (v1 처럼 v2 호환성도 버림 — 마이그레이션만 작성) |
| automation 의 부착점 | PipelineVersion 단위 유지 (§3-3 "automation 은 특정 version 가리킨다" 그대로). Family 가 추가되어도 변경 없음 |

### 13-3. 데이터 모델 — Dataset 3계층과의 비교

```
DatasetGroup (정적 개념)
  └─ DatasetSplit (정적 슬롯 — TRAIN/VAL/TEST 병렬 축, 강제 구조)
      └─ DatasetVersion (시간축 인스턴스)

PipelineFamily (느슨한 폴더 — 자유 이동, 강제력 없음)
  └─ Pipeline (정적 개념 — name 전역 UNIQUE, output_split 고정)
      └─ PipelineVersion (시간축 인스턴스 — config immutable)
```

차원이 다르다 — Dataset 의 Split 은 진짜 병렬 축이지만, Pipeline 에는 그런 슬롯
차원이 없다. Family 가 그 자리를 채우진 않는다 (Family 는 시간/공간이 아닌 "폴더링"
한 차원). 결과적으로 Pipeline 측은 (개념 + 시간축) 2 차원이고, 그 위에 사용자
편의용 Family 레이어 한 장.

```python
class PipelineFamily(Base):
    __tablename__ = "pipeline_families"
    id: UUID                # PK
    name: str               # UNIQUE
    description: str | None
    created_at / updated_at

class Pipeline(Base):
    __tablename__ = "pipelines"
    id: UUID
    family_id: UUID | None  # FK pipeline_families.id, NULL OK (ON DELETE SET NULL)
    name: str               # UNIQUE 전역
    description: str | None
    output_split_id: UUID   # FK dataset_splits.id (개념 레벨 고정)
    task_type: str          # 개념 레벨 고정
    is_active: bool         # 개념 단위 soft delete
    created_at / updated_at

class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"
    id: UUID
    pipeline_id: UUID       # FK pipelines.id (NOT NULL, ON DELETE CASCADE)
    version: str            # "1.0", "2.0" — UNIQUE(pipeline_id, version)
    config: dict            # JSONB. immutable
    is_active: bool         # version 단위 soft delete (개별 끄기)
    created_at / updated_at

class PipelineRun(Base):
    pipeline_version_id: UUID  # ← 기존 pipeline_id 가 이 자리로 격하
    automation_id: UUID | None
    ...

class PipelineAutomation(Base):
    pipeline_version_id: UUID  # ← 기존 pipeline_id 가 이 자리로 격하
    is_active / deleted_at
    # partial unique index: pipeline_version_id WHERE is_active = TRUE
```

### 13-4. Source format v3 — `source:<type>:<id>`

```
v2:  source:<UUID>                       (의미가 위치 의존적 — 모호)
v3:  source:dataset_split:<split_id>     (Pipeline.config 측 — spec)
     source:dataset_version:<version_id> (PipelineRun.transform_config 측 — resolved)
     task_<node_id>                       (task 간 참조 — 변경 없음)
```

`_substitute_resolved_versions` 가 spec → resolved 변환 시 type 도
`dataset_split` → `dataset_version` 으로 함께 flip. dag_executor 는 항상
`dataset_version` 만 본다 (split 토큰을 받으면 RuntimeError).

**JSON 복사 → 에디터 import 흐름**:
- Pipeline.config (또는 PipelineVersion.config) 의 JSON 을 그대로 import → 정상.
- PipelineRun.transform_config 의 JSON 을 import 하면 `dataset_version:` 토큰이
  들어있음. FE `unresolveVersionRefsToSplitRefs(config, versionToSplitMap)` 헬퍼가
  부모 split 으로 환원 (사용자 결정 — 원본 버전 표시 X, split 만 채움). 호출자
  (JSON 불러오기 UI) 가 versionId → splitId 매핑을 백엔드에서 받아 전달.

**schema_version 3** — 마이그레이션 시 기존 `Pipeline.config` (현 `pipeline_versions.config`)
의 source 토큰을 `dataset_split:` 접두로, `pipeline_runs.transform_config` 의 토큰을
`dataset_version:` 접두로 일괄 rewrite. 백엔드 / FE 의 `parse_source_ref` 헬퍼가
잘못된 v2 잔재를 만나면 ValueError.

### 13-5. 마이그레이션 — Alembic 032 (데이터 보존)

핵심 트릭: **`pipeline_versions.id` 를 기존 `pipelines.id` 그대로 승계**. 그러면
`pipeline_runs.pipeline_id` / `pipeline_automations.pipeline_id` 의 값은 변경하지
않고 컬럼 이름만 `pipeline_version_id` 로 rename 해도 의미가 자동 전환된다.
신규 `pipelines` (concept) 행은 새 UUID 발급.

**전체 단계** (단순화):
1. `pipeline_families` 신규 + `pipeline_versions` 신규 (FK 임시 nullable)
2. 자식 FK (pipeline_runs / pipeline_automations → pipelines) drop
3. `pipelines` 의 version / config 컬럼 drop, family_id NULL FK 추가, name UNIQUE 교체
4. 기존 pipelines 데이터 → `name` 별 grouping → `pipelines` 에 concept 행 새로 INSERT
   (id 새로 발급, name / description / task_type / output_split_id 보존)
5. 기존 데이터 → `pipeline_versions` 에 INSERT (id 보존, pipeline_id = 위에서 만든
   concept id, config 는 v3 source 포맷으로 rewrite + schema_version=3)
6. `pipeline_runs.pipeline_id` → `pipeline_version_id` rename + 자식 FK 재연결
   (FK 대상이 `pipeline_versions` 로 전환). `transform_config` 도 v3 rewrite.
7. `pipeline_automations.pipeline_id` → `pipeline_version_id` rename. partial unique
   index 도 새 컬럼 기준으로 재생성

**downgrade**: 역순. version 행 + concept 행 합쳐서 v1 평면 형태 복원, source 토큰
v3 prefix 제거.

upgrade → downgrade → upgrade 왕복 검증 통과 (실데이터 pipelines 2 / runs 9 무손실).

### 13-6. API 라우트 정리 (renamed for clarity)

기존 `/api/v1/pipelines/entities/*` 와 `/api/v1/pipelines` (run list 가 같은 prefix
에서 충돌) 가 의미 흐려져, **사용자 결정으로 전부 명시적 sub-path 로 정리**:

```
/api/v1/pipelines                     GET  — Pipeline (concept) 목록
/api/v1/pipelines/{id}                GET  — concept 상세 (versions 요약 포함)
/api/v1/pipelines/{id}                PATCH — concept 편집 (family / name / is_active)
/api/v1/pipelines/{id}/runs           GET  — concept 의 모든 version 누적 run
/api/v1/pipelines/versions/{id}       GET  — PipelineVersion 상세 (config 포함)
/api/v1/pipelines/versions/{id}       PATCH — version 편집 (is_active 토글)
/api/v1/pipelines/versions/{id}/runs  GET  / POST — version 별 run 이력 / 제출
/api/v1/pipelines/families            GET / POST — Family CRUD
/api/v1/pipelines/families/{id}       GET / PATCH / DELETE
/api/v1/pipelines/runs                GET  — 전체 run 이력 (이전 prefix `/pipelines` 에서 이동)
/api/v1/pipelines/runs/{run_id}       GET  — run 단건 상태
/api/v1/pipelines/automations         GET  — active automation 전체
/api/v1/pipelines/versions/{id}/automation GET / PUT — version 별 automation
/api/v1/pipelines/automations/{id}    DELETE — soft delete
/api/v1/pipelines/automations/{id}/reassign POST — `?new_pipeline_version_id=`
/api/v1/pipelines/automations/{id}/rerun    POST — if_delta / force_latest
/api/v1/pipelines/{validate, preview-schema, execute} POST — FE 호환 진입점 유지
```

FE 측 alias `pipelineEntitiesApi` 는 deprecated 표시만 두고 한시적 유지
(다른 페이지에서 점진 교체).

### 13-7. UX 흐름 — 행 클릭 drawer + 상세 풀 페이지

**`/pipelines` 목록 페이지**:
- 각 행 = 1 Pipeline (concept). `latest_version` 을 v1.0 처럼 인라인 표시,
  `version_count > 1` 이면 "+N개 버전" tag. `family_name` 도 행에 노출.
- 행 단순 클릭 → **우측 Drawer** 펼침. 상단에 concept 메타 (Description / Family /
  Task / Output / Active), 하단에 versions 세로 목록.
- 각 version 행 클릭 시 **인라인 expand** (작은 메타 — 노드 수 / schema_version).
- 각 version 행 옆에 **"실행"** + **"상세"** 버튼. "상세" 누르면 풀 페이지로.
- 행 자체의 **"상세 보기"** 버튼은 latest active version 의 풀 페이지로 직진 (편의).

**`/pipeline-versions/:versionId` 풀 페이지** (F-8):
- 상단 헤더: 개념명 + family tag + **version 드롭다운** (같은 concept 의 모든 version)
  + 실행 / JSON 복사 / JSON 보기 버튼.
- 본체: 좌측 readonly **ReactFlow DAG** (nodesDraggable / Connectable / deleteKey 모두
  off — 에디터 컴포넌트 분리 대신 새 페이지에서 ReactFlow 직접 사용), 우측 사이드
  메타 패널.
- 하단: 이 version 의 PipelineRun 이력 inline 테이블.

### 13-8. 진행 상황 / 검증 (2026-04-28)

- **브랜치** — `feature/pipeline-family-and-version` (`feature/pipeline-run-automation-separation`
  위에서 분기, 1 commit `25023ce` — 26 파일, +2981/-760).
- **F-1 ~ F-8 완료**:
    - F-1 Alembic 032 + roundtrip 검증
    - F-2 ORM 분리 (PipelineFamily / Pipeline / PipelineVersion)
    - F-3 lib/pipeline source format v3 (parse_source_ref / split·version 분리 메서드 / dag_executor)
    - F-4 pipeline_service / pipeline_automation_service 재작성
    - F-5 router 라우트 명시적 분리
    - F-6 FE pipeline-sdk + types + api 갱신, sourceFormat.ts 헬퍼,
      unresolveVersionRefsToSplitRefs 추가
    - F-7 PipelineListPage 행 클릭 drawer + version 세로 목록 + 인라인 expand
    - F-8 PipelineVersionDetailPage 신규 (readonly DAG / 사이드 메타 / run 이력 / JSON 복사·보기)
- **검증 통과**:
    - backend pytest 446/446 (테스트 파일 v3 포맷 일괄 갱신, get_source_dataset_ids →
      get_source_split_ids rename)
    - FE TypeScript 신규 0 (pre-existing 11 외)
    - Alembic upgrade/downgrade roundtrip + 데이터 보존
    - smoke API: `/pipelines` (concept list), `/pipelines/{id}`, `/pipelines/versions/{id}`,
      `/pipelines/runs` 모두 v3 응답 정상

### 13-9. 남은 작업 / 다음 후보

- **사용자 UI 스모크 피드백 반영** — 사용자가 "마음에 들게 동작하지만 수정할 게 좀
  있다" 보고. 피드백 받아 fine-tuning.
- **§9-8 Automation 메뉴 실 API 재연결** — 026 mock fixture → `pipelineAutomationsApi`.
  여기는 자료구조가 version 단위로 한 단 격하됐으니 026 의 mock 타입과 어댑터 작업이
  생각보다 큼.
- **§12-1 저장/실행 분리 UX** — 명시적 `POST /pipelines/concepts` (또는
  `/pipelines/versions`) 엔드포인트 신설 + 에디터 "실행" → "저장" 라벨 변경.
  현재는 `_get_or_create_concept_and_version` 임시 shim 이 호환 유지.
- **§12-2 #1 파이프라인명 입력 UI** (에디터에 name 필드 추가)
- **JSON import UI 통합** — `unresolveVersionRefsToSplitRefs` 헬퍼만 추가됨. 실제
  JSON 불러오기 모달이 PipelineRun JSON 인지 감지 → 백엔드 lookup → 변환된 config 로
  configToGraph 호출 흐름은 별도 구현 필요.
- **핸드오프 028 + 설계서 v7.11 승격 + main 머지** — 본 §13 까지 정리되면 028 신설
  검토.
