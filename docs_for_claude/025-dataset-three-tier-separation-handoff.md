# 핸드오프 025 — Dataset 3계층 분리 (DatasetGroup → DatasetSplit → DatasetVersion)

> 최초 작성: 2026-04-23 (착수 전 계획 수립 시점)
> 브랜치: `feature/dataset-three-tier-separation` (착수 시 생성 예정)
> 직전 핸드오프 (main 머지 완료): `docs_for_claude/024-head-schema-ssot-enforcement-handoff.md`
> 대기 후속 작업: `docs_for_claude/023-automation-mockup-tech-note.md` §9 (본 작업 완료 후 재개)
> 설계 반영 예정: `objective_n_plan_7th.md` v7.9 (본 작업 완료 시 승격)

---

## 0. 이 세션의 목적

Automation 실착수 이전에 Dataset 데이터 모델을 3계층으로 분리해 **정적 / 동적 경계를 테이블 단위로 구조화**한다. 023 §9-8 에서 확정된 선행 과제이며, 이 작업의 완료가 automation 실구현의 전제 조건.

**핵심 원칙.** split 은 정적 슬롯이다. 한 번 생성된 `(group, split)` 조합은 버전이 쌓일 때마다 재사용되며, 정적 식별자로서의 자기 ID 를 갖는다. Pipeline 이 "TRAIN split 최신 버전" 을 FK 무결성 하에 참조할 수 있게 하기 위함.

---

## 1. 스코프

### 1-1. 이번 세션 범위

- DB schema 3계층 분리 (Alembic 단일 revision)
- ORM 모델 재구성
- 서비스 / 라우터 / Celery / lib 계층의 `Dataset.group_id` 접근 경로 전수 조정
- FE 타입 rename (응답 shape 유지 시 타입명 교체 중심)
- 회귀 테스트 전수 통과 + 수동 스모크 검증

### 1-2. 이번 세션 **밖**

- Automation 관련 코드 (`Pipeline` 테이블 신규, `automation_*` 컬럼, chaining 분석기, polling / triggering / 수동 재실행 등) — 023 §9 에 전부 기록, 본 세션 완료 후 별도 챕터에서 처리
- API 응답 shape 변경 — 기존 스키마 그대로 유지해 FE 파괴 최소화
- `Dataset.metadata.class_info` 축소 리팩토링 — 024 §5-2 / §5-3 결정대로 별도 세션 (설계서 §5 item 26)

---

## 2. 설계 결정

### 2-1. 3계층 모델

```
DatasetGroup (정적)
  └─ DatasetSplit (정적)          — unique(group_id, split)
     └─ DatasetVersion (동적, 버전)  — unique(split_id, version)
```

| 계층 | 역할 | 주요 필드 |
|---|---|---|
| `DatasetGroup` | 그룹 정적 메타 (불변) | name, dataset_type, annotation_format, task_types, head_schema, created_at, updated_at |
| `DatasetSplit` | `(group, split)` 정적 슬롯 (신규) | id, group_id (FK), split (enum: TRAIN/VAL/TEST/NONE), created_at |
| `DatasetVersion` | 실제 데이터 버전 (기존 `Dataset` rename) | id, split_id (FK), version, storage_uri, annotation_files, class_count, metadata, created_at, updated_at |

### 2-2. 네이밍 (X+Y 하이브리드 확정)

- 중간 계층: `DatasetSplit` (신규)
- 동적 계층: `DatasetVersion` — 기존 `Dataset` 을 의미 변화 명시를 위해 ORM 클래스 + DB 테이블명 모두 rename (`datasets` → `dataset_versions`)
- 기존 "Dataset" 이 사실상 version 역할이었던 의미 모호성을 이 rename 으로 제거

### 2-3. Lineage

`DatasetLineage` 는 `DatasetVersion → DatasetVersion` 엣지로 의미 승계. 테이블 구조는 불변이며, FK 참조 테이블명만 `datasets` → `dataset_versions` rename 을 따라간다.

### 2-4. head_schema SSOT

024 에서 확정한 `DatasetGroup.head_schema` 단일 원칙은 Group 레벨이라 이번 변경의 영향을 받지 않는다. `DatasetSplit` / `DatasetVersion` 에는 head_schema 를 두지 않는다.

### 2-5. updated_at 전파 (§2-7-b)

- 기존 (`app/models/events.py::touch_dataset_group_on_dataset_change`, 73 lines): `Dataset insert/update/delete → DatasetGroup.updated_at` 자동 갱신. `session.new/dirty/deleted` 에서 `Dataset` 인스턴스의 `group_id` 를 수집해 identity_map 또는 bulk UPDATE 로 처리
- 변경 후: `Dataset` → `DatasetVersion` 으로 클래스 참조만 교체. `group_id` 접근이 이제 `DatasetVersion.split.group_id` 경로가 되므로 리스너 내부에서 `instance.split.group_id` 또는 association_proxy 로 조회
- 주의: flush 중이므로 `split` relationship 이 이미 로드돼 있는지 확인 필요. 안전하게 하려면 `DatasetVersion.split_id` → `DatasetSplit` 조회 → `group_id` 의 2단 쿼리를 리스너 내부에서 수행하거나, `DatasetVersion` 에 `group_id` 를 `association_proxy` 로 투명 노출
- `DatasetSplit.updated_at` 은 **생략** — 정적 엔티티이므로 `created_at` 만 둠 (§3-2 결정)

### 2-6. head_schema.json FS 레이아웃

024 §5-1 결정 그대로 유지. `<group>/<split>/<version>/head_schema.json`. DB 구조가 바뀌어도 파일시스템 레이아웃은 불변 — "특정 버전만 복사" UX 보존.

### 2-7. 현재 ORM 스냅샷 (rename 전 참조, `app/models/all_models.py`)

**`DatasetGroup`** (line 41~90, 불변)
- `id, name, dataset_type, annotation_format, task_types, modality, source_origin, description, extra, head_schema, created_at, updated_at, deleted_at`
- 관계: `datasets: list[Dataset]` → 변경 후 `splits: list[DatasetSplit]`

**`Dataset`** (line 93~167, `DatasetVersion` 으로 rename 예정)
- `id, group_id (FK), split, version, annotation_format, storage_uri, status, image_count, class_count, annotation_files, annotation_meta_file, metadata_, created_at, updated_at, deleted_at`
- unique: `(group_id, split, version)` → 변경 후 `(split_id, version)`
- 관계: `group: DatasetGroup`, `lineage_as_parent/child`, `pipeline_executions`
- rename 후: `split: DatasetSplit`, `group` 은 association_proxy

**`DatasetLineage`** (line 170~191, 구조 불변)
- `parent_id / child_id` FK → `datasets.id` → RENAME 후 자동 `dataset_versions.id` 로 추종

**외부 FK → `datasets.id`** (RENAME 자동 추종 대상)
- `pipeline_executions.output_dataset_id` (line 240~241)
- `solutions.train_dataset_id / val_dataset_id / test_dataset_id` (line 327~335, Phase 2 대비 빈 테이블)
- `dataset_lineage.parent_id / child_id` (line 175~180)

PostgreSQL `ALTER TABLE RENAME` 은 FK 메타데이터를 OID 기반으로 참조하므로 자동 추종된다. Alembic `op.rename_table()` 이 이를 포괄한다.

---

## 3. 착수 전 결정 사항 (2026-04-23 확정)

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 3-1 | DB 테이블명 rename 범위 | **(a) 채택** — `datasets` → `dataset_versions` (ORM + DB 둘 다 rename) | 의미 변화 명시 + Alembic `op.rename_table()` 이 외부 FK 자동 추종 |
| 3-2 | `DatasetSplit.updated_at` | **생략** (`created_at` 만 둠) | 정적 엔티티 — split 생성 시점만 의미 있음 |
| 3-3 | `DatasetVersion.group` 접근 방식 | **association_proxy 채택** | 기존 `Dataset.group` 호출 코드가 `DatasetVersion.group` 으로 투명하게 동작 — 접근 경로 변경으로 인한 리팩토링 범위 최소화 |
| 3-4 | Lineage 엣지 방향 | **DatasetVersion → DatasetVersion 승계** | 024 시점의 lineage 의미 그대로. 엣지 해석 로직 불변 |
| 3-5 | 024 `head_schema` SSOT 영향 | **영향 없음 확인** | SSOT 는 `DatasetGroup` 레벨 — 중간/말단 계층 추가는 무관 |

---

## 4. 마이그레이션 계획

### 4-1. Alembic 단일 revision 순서

원자성 확보를 위해 단일 revision 으로 묶음. upgrade / downgrade 왕복 완비. Revision 번호는 030 (직전 029 가 head_schema backfill).

1. `dataset_splits` 테이블 CREATE
   - `id UUID PK`, `group_id UUID FK → dataset_groups(id) ON DELETE CASCADE`, `split VARCHAR(10)` (기존 Dataset.split 과 동일 enum 문자열), `created_at TIMESTAMPTZ`
   - `UNIQUE(group_id, split)`
2. 기존 `datasets` 에서 `DISTINCT (group_id, split)` 추출 → `dataset_splits` 로 INSERT (각 조합 1행, `id = gen_random_uuid()`)
3. `datasets.split_id UUID` 컬럼 추가 (초기 nullable)
4. `datasets.split_id` 를 `(group_id, split)` 조합으로 매핑해 UPDATE — 단일 SQL `UPDATE ... FROM dataset_splits WHERE ...`
5. `datasets.split_id NOT NULL` + FK 제약 추가 (`ON DELETE CASCADE` — group cascade 와 일관)
6. unique constraint 교체: `uq_dataset_group_split_version (group_id, split, version)` DROP → `uq_dataset_version_split_version (split_id, version)` 신설
7. `datasets.group_id`, `datasets.split` 컬럼 DROP
8. `datasets` → `dataset_versions` 테이블 RENAME
   - 외부 FK 참조 자동 추종 대상 (§2-7): `pipeline_executions.output_dataset_id`, `solutions.train_dataset_id / val_dataset_id / test_dataset_id`, `dataset_lineage.parent_id / child_id`. PostgreSQL 이 OID 기반으로 FK 를 추적하므로 `op.rename_table()` 한 줄로 포괄
9. downgrade: 역순 (table RENAME 복구 → group_id / split 컬럼 추가 → 데이터 역매핑 (split_id → (group_id, split)) → unique constraint 원복 → split_id DROP → dataset_splits DROP)

**주의 사항.**
- Batch 작업이므로 transactional DDL 하에 실행 (PostgreSQL 기본 동작). 중간 실패 시 롤백되어야 함.
- 029 downgrade 가 no-op 이었던 것과 달리, 030 downgrade 는 데이터 역매핑 필요 — 신중히 작성.
- `ALTER TABLE ... RENAME` 은 SQLAlchemy/Alembic 둘 다 FK constraint 자동 추종 (constraint 이름 자체는 유지됨, 참조 테이블명만 갱신).

### 4-2. ORM 변경 (`app/models/all_models.py`)

1. `DatasetSplit` 모델 신규 (`group_id`, `split`, `created_at`, 관계)
2. `Dataset` → `DatasetVersion` rename (모든 import / 참조 포함)
3. 관계 재배선:
   - `DatasetGroup.splits: list[DatasetSplit]`
   - `DatasetSplit.group: DatasetGroup`, `DatasetSplit.versions: list[DatasetVersion]`
   - `DatasetVersion.split: DatasetSplit`
4. `DatasetVersion.group` 경로 — association_proxy 로 `split.group` 을 투명하게 노출 (기존 `.group` 호출 코드 최소 수정, 3-3 가정)
5. 이벤트 리스너 재배선 (`app/models/events.py`, §2-5) — `DatasetVersion` mapper 에 `before_flush` 구독

### 4-3. 호출 계층 전수 조정

영향 빈도는 `grep` 으로 확인한 `Dataset.group_id` / `Dataset.split` / `Dataset(...)` 접근 수 (2026-04-23 기준). 정확한 작업량은 각 파일 일독 필요.

**백엔드 서비스.**

- `app/services/dataset_service.py` (1898 lines, **18건 참조**) — RAW 등록 (non-classification `register_raw_dataset`), 버전 해결 (`_next_version`), `_diff_head_schema`, 그룹 조회/삭제, 집계 서브쿼리(line 93~106). 신규 등록 시 `DatasetSplit` 선조회/생성 로직 추가가 핵심
- `app/services/pipeline_service.py` (1108 lines, **9건 참조**) — source 로드, `preview_head_schema`, `_validate_with_database`, `_validate_output_schema_compatibility` (024 신설). SSOT 검증 경로 유지

**백엔드 라우터.**

- `app/api/v1/dataset_groups/router.py` (299 lines, **2건**) — 그룹 목록 집계(`dataset_count` / `total_image_count`) 는 `DatasetGroup → DatasetSplit → DatasetVersion` 2단 JOIN 으로 재작성
- `app/api/v1/datasets/router.py` (363 lines, **5건**) — 데이터셋 CRUD (응답 shape 유지)
- `app/api/v1/pipelines/router.py` — `PipelineExecution` 만 import, Dataset 직접 참조 없음. rename 영향은 주석/변수명 수준
- `app/api/v1/lineage/router.py`, `app/api/v1/eda/router.py` — **stub 상태** (Phase 2-a/2-b 예정, `{"message": "...에서 구현 예정"}` 반환). 이번 rename 영향 없음 → 체크리스트 제외

**Celery tasks.**

- `app/tasks/pipeline_tasks.py` (346 lines, **2건**) — 파이프라인 실행 시 input version / output version 해결
- `app/tasks/register_classification_tasks.py` (310 lines) — classification RAW 등록. `DatasetSplit` 선조회/생성 로직 추가
- `app/tasks/register_tasks.py` (261 lines) — 비 classification RAW 등록. 동일하게 split 선조회/생성 필요
- `app/tasks/eda_tasks.py` — Dataset 직접 참조 없음 (stub)
- `app/tasks/celery_app.py` — 이벤트 리스너 import (`app.models.events`). 리스너 내부가 바뀌어도 import 구문은 불변

**lib/.**

- `lib/pipeline/*` — `DatasetMeta.dataset_id` 의 의미는 이제 `DatasetVersion.id`. 로직 변경 없이 주석 / 변수명만 정리
- `lib/classification/ingest.py` — 상동

**프론트엔드.**

- `frontend/src/types/dataset.ts` — 핵심 타입 파일. `Dataset` interface → `DatasetVersion` rename. 연관 타입 (`DatasetGroup.datasets?` 배열, lineage 응답 등) 도 함께 업데이트
- `frontend/src/types/index.ts`, `frontend/src/types/pipeline.ts` — `Dataset` 타입 re-export 또는 참조 있는지 확인
- `frontend/src/api/` — API 클라이언트. 응답 shape 유지 시 호출 경로 무변경
- 페이지 / 컴포넌트 (DatasetListPage, DatasetDetailPage, DatasetRegisterModal, LineageTab, SampleViewerTab 등) — 타입 rename 반영 + split 표시 로직 재검증

### 4-4. 테스트

- `backend/tests/` — 전수 통과 (2026-04-22 기준 446건). `backend/tests/test_pipeline_config.py` 에서 `Dataset` 이름 직접 사용 (rename 필요)
- 프론트 `npm run build` — pre-existing 11건 TS 에러는 022 §7 에서 기록된 기존 문제. 이번 변경이 신규 에러를 만들지 않는지만 검증

---

## 5. 영향 범위 체크리스트

구현 중 빠진 곳 발견 시 누적 추가. 체크박스는 작업 진행에 따라 갱신.

**DB / ORM.**
- [ ] Alembic 마이그레이션 (upgrade / downgrade 왕복)
- [ ] `DatasetSplit` ORM 모델 신규
- [ ] `Dataset` → `DatasetVersion` rename
- [ ] 관계 재배선 (`splits`, `versions`, `split`, `group` proxy)
- [ ] 이벤트 리스너 재배선 (`updated_at` 전파)

**백엔드 서비스 / 라우터.**
- [ ] `app/services/dataset_service.py` (18 refs) — RAW 등록 시 `DatasetSplit` 선조회/생성 + `_next_version` 시그니처 조정
- [ ] `app/services/pipeline_service.py` (9 refs) — source 로드 / preview / validate 경로
- [ ] `app/api/v1/dataset_groups/router.py` (2 refs) — 집계 쿼리 2단 JOIN 재작성
- [ ] `app/api/v1/datasets/router.py` (5 refs) — CRUD, 응답 shape 유지
- [ ] `app/api/v1/pipelines/router.py` — import / 주석 확인만

**Celery tasks.**
- [ ] `app/tasks/pipeline_tasks.py` (2 refs) — input/output version 해결
- [ ] `app/tasks/register_classification_tasks.py` — split 선조회/생성
- [ ] `app/tasks/register_tasks.py` — split 선조회/생성 (비 classification RAW)
- [ ] `app/tasks/celery_app.py` — 이벤트 리스너 import 경로 (`app.models.events`) 불변 확인

**lib/.**
- [ ] `lib/pipeline/*` — 주석 / 변수명 정리 (로직 변경 없음)
- [ ] `lib/classification/ingest.py`

**테스트.**
- [ ] `backend/tests/test_pipeline_config.py` — `Dataset` 직접 사용 있음, rename 반영

**프론트엔드.**
- [ ] `frontend/src/types/dataset.ts` — `Dataset` interface → `DatasetVersion` rename + 관련 타입 정리
- [ ] `frontend/src/types/index.ts`, `frontend/src/types/pipeline.ts` — 참조 / re-export 확인
- [ ] `frontend/src/api/` — 호출 경로 (응답 shape 유지 시 무변경)
- [ ] 페이지 / 컴포넌트 (DatasetListPage / DatasetDetailPage / DatasetRegisterModal / LineageTab / SampleViewerTab 등) — 타입 rename 반영

---

## 6. 회귀 검증 체크리스트

세션 종료 전 전부 확인.

**자동.**
- [ ] `cd backend && uv run pytest -q` — 446 pass 유지
- [ ] `make frontend-build` — pre-existing 외 신규 TS 에러 없음
- [ ] Alembic `upgrade head` → `downgrade -1` → `upgrade head` 왕복 성공
- [ ] `alembic current` = 신규 revision ID

**수동 스모크.**
- [ ] 그룹 목록 페이지 — 필터 / 정렬 / 집계 (`dataset_count` / `total_image_count`) 정상
- [ ] RAW 등록 (detection 계열) — 기존 위자드 3단계 정상
- [ ] Classification RAW 등록 — head_schema SSOT (024) 유지 확인
- [ ] 파이프라인 실행 (detection) — Phase A / B 완주
- [ ] 파이프라인 실행 (classification) — passthrough 포함
- [ ] Lineage 탭 렌더 — detection / classification 공유 `LineageTab` 정상
- [ ] 샘플 뷰어 — detection / classification 각 타입
- [ ] 024 §6-2 검증용 dataset `a55fe491-1625-460c-bd58-f9113fbf5990` preview-schema 정상 응답 유지
- [ ] 023 §9-10 테스트용 dataset 2건 조회 / lineage 확인
  - `hardhat_headcrop_visible_added` — `83f76037-df56-4575-a343-2ade37299225`
  - `hardhat_headcrop_original_merged` — `4d2afb95-f7e6-4297-afff-6c435b9af9cf`

---

## 7. 착수 후 누적 기록 (2026-04-23 세션)

### 7-1. 커밋 순서 (브랜치 `feature/change-dataset-db-schema`)

| # | SHA | 요약 |
|---|---|---|
| 1 | `851dc47` | docs — 핸드오프 023 §9 갱신 + 025 신규 (착수 전 결정 기록) |
| 2 | `75195a5` | feat(db) — Alembic 030 + ORM + 서비스 / 라우터 / Celery / FE 전수 조정 |
| 3 | `1f1aa1c` | fix(migrations) — env.py import 누락 복구 (alias 제거 여파) |
| 4 | (이 커밋) | docs — 025 §7 채움 + 설계서 v7.9 승격 + CLAUDE/MEMORY 포인터 갱신 |

모든 커밋에서 `cd backend && uv run pytest -q` 446/446 통과 확인.

### 7-2. 발견된 추가 영향 범위 (§5 체크리스트 밖)

1. **`dataset_group_summary` Materialized View (001_initial_schema.py line 197)** —
   `datasets.group_id` / `datasets.split` 에 의존. `DROP COLUMN` 실행 시
   `DependentObjectsStillExist` 로 차단됨. 030 upgrade 초반에 `DROP MATERIALIZED VIEW`
   선제 실행 + 말미에 3계층 JOIN 기반(`dataset_groups → dataset_splits → dataset_versions`)
   으로 재생성. downgrade 도 대칭.

2. **`backend/migrations/env.py` import 구문** — alias 제거 커밋(`75195a5`) 후 env.py
   가 여전히 `Dataset` 을 import 하고 있었다. Alembic 부팅 시 ImportError 로 backend
   컨테이너가 재시작 루프에 빠져 FE proxy 가 `EAI_AGAIN backend` 로 실패. `1f1aa1c`
   에서 `DatasetVersion` + `DatasetSplit` 로 교체.

3. **`association_proxy` 의 collection-of-collections 문제** — 초기 구현에서
   `DatasetGroup.datasets = association_proxy("splits", "versions")` 로 두었으나,
   SQLAlchemy 가 이를 list-of-InstrumentedList 로 돌려주어 Pydantic 직렬화가
   `items.N.datasets.M` 단위에서 깨짐. 해결책으로 `datasets` 를 **flat `@property`**
   로 전환 (`[v for s in self.splits for v in s.versions]`). association_proxy 는
   쿼리에 쓰지 않고 읽기/직렬화 전용으로만 유지.

4. **`DatasetVersion.split` 컬럼 이름 충돌** — 기존 `Dataset.split` (문자열) 과 신규
   `DatasetVersion.split_slot → DatasetSplit` relationship 의 이름이 충돌. relationship
   을 `split_slot` 으로 rename, `split` 은 `association_proxy("split_slot", "split")`
   로 문자열을 투명 노출. 결과적으로 Pydantic 스키마(`DatasetSummary.split: str`) 호환
   유지 + ORM 접근(`version.split_slot.group`) 도 자연스럽게 동작.

5. **`DatasetVersion.group` / `group_id` 도 association_proxy 로 유지** — 기존 호출
   코드(`dataset.group`, `dataset.group_id`)가 다수. 이를 전부 `version.split_slot.group`
   으로 바꾸지 않아도 되도록 `split_slot` 경유 association_proxy 로 노출. Celery sync
   세션에서 lazy load 로 자동 해결되며, async 세션에서는 `selectinload(split_slot)`
   선로드로 MissingGreenlet 방지.

6. **`events.py` 의 `before_flush` 리스너** — 기존 `instance.group_id` 직접 접근에서
   insert 직후(`split_id` 만 세팅, split relationship 은 미로드) 의 케이스를 다루기
   위해 `_resolve_group_id_for_version()` 헬퍼 신설. 3단계 fallback
   (`__dict__["split_slot"]` → `identity_map` → `session.execute(SELECT)`) 으로
   안전 해결.

7. **`GET /datasets` 라우터의 `pipeline_execution_id` 프로퍼티** — DatasetVersion 의
   `@property` 가 `self.pipeline_executions` 를 참조. async 세션에서 선로드 누락 시
   MissingGreenlet 발생. `list_datasets` 에 `selectinload(pipeline_executions)` 추가로
   해결.

8. **기존 Dataset ID 두 건 (`83f76037...`, `4d2afb95...`) 부재** — 023 §9-10 에서
   mock fixture 참조용으로 기록했으나 현재 DB 에 없음. `4d2afb95...` 은 오히려
   PipelineExecution ID 였던 것으로 확인 (§7-4 파이프라인 실행 검증에서 확인). 원 ID
   들을 automation 목업 fixture 에 쓰려면 재확보 필요 — 이번 세션 스코프 밖.

### 7-3. 설계 미세 조정 (§2 대비)

1. **`DatasetVersion.split` 을 association_proxy 문자열로 노출** — 원 설계는
   `DatasetVersion.split: DatasetSplit` relationship 이었으나, 기존 코드/Pydantic
   스키마 호환을 위해 relationship 명을 `split_slot` 으로 바꾸고 `split` 은 문자열
   proxy 로 분리 (§7-2-4).

2. **`DatasetGroup.datasets` 를 `@property` 로 전환** — association_proxy 의 중첩
   리스트 반환 이슈로 flat 파이썬 property 채택 (§7-2-3). 직렬화 전용, 쿼리 조건에는
   쓰지 않는다.

3. **`DatasetVersion.group` 은 association_proxy 유지** — scalar 경로
   (`split_slot.group`) 라 중첩 문제 없음. 기존 코드 호환.

### 7-4. 실데이터 검증

파이프라인 실행 2건으로 3계층 JOIN end-to-end 동작 확인.

**파이프라인 `fafbd6ad-c66a-4f1f-a7c2-9c9a9f5da60a`** (사용자 수동 실행):
```
id         | fafbd6ad-c66a-4f1f-a7c2-9c9a9f5da60a
status     | DONE
output     | b1e8f405-ac6e-4b33-b8ea-7a03ed95c549
  → split  | VAL
  → group  | fullcover_coco
  → version| 6.0
```

`pipeline_service._get_or_create_split` 이 기존 split 을 찾아 재사용 (group 의 기존
VAL split 에 새 버전 추가). `_next_version(split_id)` 가 5.0 → 6.0 major 증가. DAG
executor 경로 전체 (Phase A annotation + Phase B image materialization) 정상 완주.

### 7-5. 남은 작업 (이번 세션 이후)

- **main 머지** — `feature/change-dataset-db-schema` → `main`.
- **`docs_history/handoffs/025-...md` 아카이브 이동** — main 머지 후 `docs_for_claude/`
  → `docs_history/handoffs/` 로 이동. 023 / 024 도 같은 시점에 아카이브.
- **핸드오프 023 자동화 목업 재개** — 023 §9 결정 위에서 `feature/pipeline-automation-mockup`
  브랜치 재생성. 3계층 분리가 완료됐으므로 Pipeline 엔티티 신규 + automation_*
  컬럼 추가가 FK 무결성 하에 자연스럽게 설계 가능.
- **`Dataset.metadata.class_info` 축소 리팩토링** — 설계서 §5 item 26. 별도 세션.

---

## 8. 참조

- 설계서 (현행): `objective_n_plan_7th.md` (v7.8, 2026-04-22) — 본 작업 완료 시 v7.9 로 승격
- 직전 핸드오프: `docs_for_claude/024-head-schema-ssot-enforcement-handoff.md`
- 대기 후속 작업: `docs_for_claude/023-automation-mockup-tech-note.md` §9 (사용자 확정 결정 + 실착수 조건)
- 노드 SDK 가이드: `docs/pipeline-node-sdk-guide.md`
- CLAUDE.md — 네이밍 규칙 / 컨벤션 (한글 주석 / 풀네임 / async/sync 분리 / uv / ruff / eslint)
