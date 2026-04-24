# 핸드오프 024 — DatasetGroup.head_schema SSOT 단일 원칙 강제

> 기준일: 2026-04-22
> 브랜치: `feature/classification-dag-head-schema-view` (main 미머지)
> 직전 핸드오프 (아카이브): `docs_history/handoffs/022-classification-dag-chapter-closure-handoff.md` (main 머지 완료)
> 동시대 미진행 핸드오프: `docs_for_claude/023-automation-mockup-tech-note.md` (자동화 목업, 이번 세션에 착수 안 함 — 별도 재개 대기)
> 설계 반영: `objective_n_plan_7th.md` v7.8 (§2-8 갱신 + §5 항목 15-b / 24 / 25 / 26 추가)

---

## 0. 이 세션의 목적

표면 증상("classification 파이프라인 에디터에서 dataLoad 단독으로 선택 시 우측 속성 패널의 schema 프리뷰가 안 보임") 에서 출발해, 파고 내려가면서 **"같은 `DatasetGroup` 의 모든 `Dataset` 이 동일 `head_schema` 를 가진다"** 라는 설계적 전제가 코드와 DB 상태 양쪽에서 느슨하게 지켜지고 있었음을 확인하고, 이 규약을 **단일 원칙으로 명문화 + 구조적으로 강제**한 세션.

자동화 목업(브랜치 `feature/pipeline-automation-mockup`, 핸드오프 023) 을 만들기 위해 RAW → SOURCE 파이프라인을 준비하다가 이 버그를 발견해서 먼저 고친 것이라, 이후 자동화 목업은 이 수정 이후의 SSOT 가 채워진 상태에서 재개해야 한다.

---

## 1. 브랜치 개요

| 항목 | 값 |
|---|---|
| fork point (main) | `e0db197` — "docs: 023 파이프라인 자동화 목업 기술 검토 노트" |
| 커밋 수 (first-parent, main 제외) | 5 |
| 추가 Alembic 마이그레이션 | 1건 (`029_backfill_group_head_schema`) |
| 전체 회귀 테스트 | **446 / 446 pass** (`cd backend && uv run pytest -q`) |
| 설계서 판 | v7.7 → **v7.8** |
| FE 변경 | 없음 (기존 `SchemaPreviewSection` 분기가 그대로 활용됨) |

커밋 순서:

1. `965dc24 fix(pipeline): preview-schema — dataLoad 단독 선택 시 head_schema 표시 복원`
2. `9781972 refactor(pipeline): preview-schema task_kind 판정을 group.task_types 기반으로 전환`
3. `381878a feat(classification): head_schema SSOT 단일 원칙 강제 — Group 내 schema 동일 보장`
4. `67bfc5e chore(migrations): 029 — 기존 classification 그룹 head_schema NULL 백필`
5. `2439432 docs: 설계서 v7.8 — DatasetGroup.head_schema SSOT 단일 원칙 명문화 (§2-8)`

---

## 2. 증상 → 원인 → 규약 확정 경과

### 2-1. 1차 증상 — dataLoad 단독 프리뷰 안 보임

사용자 보고: "DAG 에디터에서 Load 데이터 노드 1개만 있을 때 우측 속성 탭의 head_schema 프리뷰가 안 보인다. 뒤에 아무 노드나 붙이면 보인다."

**원인** (커밋 `965dc24` 로 1차 수정):

`pipeline_service.preview_head_schema` 가 `config.get_all_source_dataset_ids()` 로 수집한 source id 만 DB 에서 로드했다. dataLoad 단독이면 `tasks={}` + `passthrough_source_dataset_id=null` 이라 해당 source id 가 config 에 한 번도 참조되지 않아 `source_meta_by_dataset_id` 가 비고, "모든 소스가 detection 이면 detection 반환" 조기 분기로 빠져 FE 가 섹션을 통째로 숨겼다.

**1차 수정**: `source:<id>` 타겟 분기를 detection 조기 반환보다 앞으로 이동 + `source_meta_by_dataset_id` 에 없으면 DB 에서 직접 로드. RAW 그룹(head_schema 있음) 에서는 이로써 dataLoad 단독도 schema 가 정상 표시됐다.

### 2-2. 2차 증상 — SOURCE/FUSION 은 여전히 안 보임

위 수정 후에도 `hardhat_bodyonly_upperbody` (SOURCE) / `hardhat_classification_final_data` (FUSION) 등의 dataset 을 선택하면 schema 가 안 보였다. DB 조회 결과:

```
 name                              | dataset_type | has_head_schema
 hardhat_bodyonly                  | RAW          | t
 hardhat_headcrop                  | RAW          | t
 hardhat_original                  | RAW          | t
 hardhat_classification_final_data | FUSION       | f   ← NULL
 hardhat_bodyonly_lowerbody        | SOURCE       | f   ← NULL
 hardhat_bodyonly_upperbody        | SOURCE       | f   ← NULL
 hardhat_headcrop_visible_added    | SOURCE       | f   ← NULL
 hardhat_original_upperbody        | SOURCE       | f   ← NULL
```

**RAW 3개만 head_schema 가 있고, 파이프라인이 출력한 5개는 전부 NULL.** 사용자의 `Dataset.metadata.class_info` 를 직접 확인해보니 per-dataset 레벨에는 스키마가 정상 저장되어 있었다(`heads=[{name, multi_label, class_mapping, per_class_image_count}]`). 그러나 그룹 레벨 SSOT 컬럼이 비어 있음.

**추적 결과**: `pipeline_tasks._execute_pipeline` 의 classification 성공 블록이 `Dataset.metadata` 만 갱신하고 `output_dataset.group.head_schema` 는 건드리지 않았다. 신규 classification 그룹이 파이프라인으로 만들어질 때마다 이 컬럼이 NULL 인 채로 남는 구조적 버그.

### 2-3. 설계 논의 — Group SSOT vs Dataset SSOT

사용자가 "왜 Group 에서 조회하지, Dataset 마다 있는데?" 라고 질문해서, SSOT 위치를 재검토하는 논의로 확장됐다. 근거 문서 3곳에서 이미 "DatasetGroup.head_schema = 유일 SSOT" 가 확정되어 있음을 확인:

- 설계서 §2-8: "DatasetGroup.head_schema JSONB 신규 (migration 009, classification만 사용 — detection은 NULL)"
- 핸드오프 015 §1: "DatasetGroup.head_schema JSONB 컬럼 추가 (**classification 전용 SSOT**)"
- `project_classification_head_schema_contract.md` (memory): "class-index 매핑은 데이터 스키마의 책임 ... ONNX metadata 까지 전파"

**논의 결론 (사용자 확정)**: 학습 플랫폼으로 확장한다는 전제에서는 Group SSOT 가 맞다. 실험 run 비교 · 모델 레지스트리 · 롤백 · Auto-labeling 기준이 모두 그룹 단위로 성립하기 때문.

단 이전까지 애매하게 허용되던 **NEW_HEAD / NEW_CLASS warning 후 허용 정책** 이 "과거 학습 결과 해석을 조용히 변이시키는 회색지대" 였음을 짚었다. 사용자가 **"Group 내 schema 전부 동일, 예외 없음, 다르면 반드시 새 그룹으로 분기"** 를 단일 원칙으로 확정.

"PROCESSED / FUSION 에서 schema 변경이 필요하면 새 그룹으로 분기한다" 는 운용은 dataset_type (RAW/SOURCE/PROCESSED/FUSION) 의 의미 태그 수준에 머무르고, 강제 제약은 type 무관으로 동일하게 적용.

---

## 3. 확정된 규약 — v7.8 단일 원칙

### 3-1. 원칙

> **같은 `DatasetGroup` 의 모든 `Dataset` 은 동일 `head_schema` 를 가진다. type 무관, RAW 포함 예외 없음. `head_schema` 가 달라지는 순간 반드시 새 `Group` 으로 분기한다.**

### 3-2. 데이터 소스 SSOT 관계

| 저장소 | 위치 | 역할 |
|---|---|---|
| **`DatasetGroup.head_schema`** | DB JSONB | **진리 SSOT.** class-index 계약의 유일 출처 |
| `Dataset.metadata.class_info.heads` | DB JSONB | 해당 Dataset 생성 시점의 스냅샷 + per-dataset 통계(`per_class_image_count`, `skipped_collisions`). 구조 필드(`name`/`multi_label`/`class_mapping`) 는 SSOT 카피 — 생성 경로(`register_classification_tasks`, `pipeline_tasks`)에서 SSOT 와 동일하게 만들어야 한다 |
| `head_schema.json` | FileSystem | Dataset 버전 디렉토리 안의 SSOT 스냅샷. 오프라인 학습 / K8S 컨테이너가 DB 접근 없이 읽을 수 있는 배포 편의용. **FS 레이아웃은 변경하지 않았다** — 버전별 `<group>/<split>/<version>/head_schema.json` 유지 (DB 유실 시 복구 포인트 겸 "특정 버전만 복사" UX 보존) |

### 3-3. 두 진입로에서의 강제

| 진입로 | 강제 지점 | 동작 |
|---|---|---|
| RAW 등록 | `dataset_service._diff_head_schema(existing, incoming)` | 어떤 차이든 `ValueError` 즉시 차단. 이전의 NEW_HEAD / NEW_CLASS warning 허용은 폐지. `_merge_head_schema` 호출도 제거됨 (diff 통과 = 기존과 동일이므로 건드릴 필요 없음) |
| 파이프라인 실행 — 정적 검증 | `pipeline_service._validate_output_schema_compatibility(config, result)` (신설) | `preview_head_schema_at_task` 로 출력 schema 를 미리 계산해 기존 동명 그룹의 `head_schema` 와 `_diff_head_schema` 로 비교. 불일치 → `OUTPUT_SCHEMA_MISMATCH` ERROR. 신규 그룹이거나 기존 그룹이 detection 이면 skip |
| 파이프라인 실행 — 완료 시 | `pipeline_tasks._execute_pipeline` (classification 성공 블록) | 신규 그룹(`group.head_schema IS NULL`) 인 경우 결과 head_schema 로 setdefault 초기화. 이미 값이 있으면 건드리지 않음 (정적 검증에서 사전 차단) |

### 3-4. 판정 기준 — task_types 기반

`preview_head_schema` 의 classification/detection 판정을 `head_schema` 존재 여부가 아니라 **`DatasetGroup.task_types`** 기반으로 전환. classification 그룹인데 head_schema 가 NULL 인 상태를 detection 으로 숨기지 않고 `HEAD_SCHEMA_MISSING` 경고로 가시화. "이 상태가 왜 생겼는지" 를 숨기지 않는 것이 디버깅 관점에서 안전하고, 원칙상으로도 "그룹 타입은 task_types 가 결정" 이 자연스럽다는 사용자 지적 수용.

---

## 4. 코드 변경 상세

### 4-1. `backend/app/services/pipeline_service.py`

두 번에 걸쳐 수정 (`965dc24` + `9781972` + `381878a`).

- `preview_head_schema`:
  - `_is_classification_group(task_types)` 내부 헬퍼 추가 — `"CLASSIFICATION" in (task_types or [])`.
  - 소스 로드 루프에서 `source_meta_by_dataset_id` + `source_task_types_by_dataset_id` 동시 수집.
  - `source:<id>` 분기를 detection 조기 반환보다 앞으로 이동 + config 참조 없는 id 에 대해 DB 직접 로드(fallback) 추가.
  - task_kind 판정을 `head_schema` 유무 → `group.task_types` 기반으로 전환. classification 그룹인데 head_schema NULL 이면 `HEAD_SCHEMA_MISSING` error_code 로 경고(섹션 숨김 안 함).
  - `task_<id>` 분기도 `any_classification_group` 기반으로 전환 + `head_schema` 가 None 이면 `HEAD_SCHEMA_MISSING` 경고.
- `_validate_with_database`: 기존 cls compat 3종 뒤에 `_validate_output_schema_compatibility` 호출 추가.
- `_validate_output_schema_compatibility` (신설):
  - 기존 동명 그룹 조회 (name + dataset_type 키, `_find_or_create_dataset_group` 과 동일).
  - 신규 그룹이면 skip. detection 그룹이면 skip.
  - classification 그룹인데 head_schema NULL 이면 `OUTPUT_GROUP_HEAD_SCHEMA_MISSING` warning (이번 실행이 setdefault 로 초기화해줄 것).
  - 그 외는 passthrough/tasks 분기로 출력 head_schema 를 계산해 `_diff_head_schema` 로 비교. `ValueError` → `OUTPUT_SCHEMA_MISMATCH` ERROR.

### 4-2. `backend/app/services/dataset_service.py`

`_diff_head_schema` 단순화 + 엄격화:

- 반환 타입은 기존 시그니처 호환 (`list[ClassificationHeadWarning]`) 유지되지만, 정상 흐름에서는 항상 빈 리스트만 반환.
- head 추가/삭제, class 변경 (순서/추가/제거), multi_label 변경 — 어떤 차이든 수집한 뒤 하나라도 있으면 묶어 `ValueError` 로 raise.
- 호출부에서 `_merge_head_schema` 호출 제거 (diff 통과 = 기존과 동일이므로 group.head_schema 건드릴 필요 없음). `_merge_head_schema` 함수 자체도 삭제.

### 4-3. `backend/app/tasks/pipeline_tasks.py`

classification 성공 블록 말미에 `output_dataset.group.head_schema` setdefault 초기화 추가:

```python
if output_dataset.group is not None and output_dataset.group.head_schema is None:
    output_dataset.group.head_schema = {
        "heads": [
            {"name": head.name, "multi_label": head.multi_label, "classes": list(head.classes)}
            for head in head_schema
        ],
    }
```

- Celery 의 sync 세션에서 `output_dataset.group` relationship 은 lazy load 됨 (세션 살아있음).
- 이미 값이 있으면 건드리지 않음 — 불일치 방지는 `_validate_output_schema_compatibility` 에서 실행 전 이미 차단하므로 여기선 중복 검사 불요.

### 4-4. `backend/migrations/versions/029_backfill_group_head_schema.py` (신규)

일회성 데이터 백필. upgrade 결과 로그:

```
[029 backfill] 대상 그룹 수=5
[029 backfill][OK] group=hardhat_classification_final_data — 2 heads 복원: hardhat_wear(2cls), visibility(2cls)
[029 backfill][OK] group=hardhat_headcrop_visible_added — 2 heads 복원: hardhat_wear(2cls), visibility(2cls)
[029 backfill][OK] group=hardhat_original_upperbody — 2 heads 복원: hardhat_wear(2cls), visibility(2cls)
[029 backfill][OK] group=hardhat_bodyonly_upperbody — 1 heads 복원: visibility(2cls)
[029 backfill][OK] group=hardhat_bodyonly_lowerbody — 1 heads 복원: visibility(2cls)
[029 backfill] 완료 — restored=5, skipped=0, total_targets=5
```

- 소스: 각 그룹의 `created_at` 최초 Dataset 의 `metadata.class_info.heads`.
- 변환: `class_mapping` ({"0": "a", "1": "b"}) 를 key 의 int 정렬로 `classes` (["a", "b"]) 로 복원.
- downgrade 는 no-op — 되돌리면 §2-8 단일 원칙 위반 상태로 회귀하므로 의도적으로 비워 둠.

### 4-5. `objective_n_plan_7th.md` (설계서 v7.8)

- 헤더 v7.7 → v7.8. 기준일 2026-04-22.
- v7.8 블록 추가 (배경 + 변경 요약 + 브랜치/회귀 수치).
- §2-8 재작성:
  - "head_schema 일관성 (동일 그룹 신규 버전 등록 시)" → **"head_schema SSOT 단일 원칙"** 으로 교체.
  - 이전 NEW_HEAD / NEW_CLASS warning 허용 정책 폐지 명시.
  - 데이터 소스 SSOT 관계 표 + 두 진입로 강제 위치 표 추가.
- §5 남은 작업:
  - 15-b 항목으로 이번 세션 완료 기록.
  - 16 Automation 항목에 `docs_for_claude/023-automation-mockup-tech-note.md` 참조 링크 추가.
  - 24 / 25 / 26 항목 신설 — 후속 사용성 개선 TODO (후술).

---

## 5. 기타 설계 결정 (이번 세션 중 확정된 부가 결정)

### 5-1. FS 레이아웃 `head_schema.json` 위치 — **버전별 유지**

사용자가 "group 레벨 / split 레벨로 올리면?" 제안했으나, 의도("특정 버전만 복사해 가져가 쓰기")와 현재 레이아웃이 이미 부합 (`<group>/<split>/<version>/head_schema.json` 을 `mv` 하면 따라감). split 레벨로 올리면 오히려 특정 버전만 복사할 때 안 따라감. 파일 크기도 수백 바이트라 중복 부담 0. **변경 없음.**

### 5-2. `Dataset.metadata.class_info` 축소 — **이번엔 범위 밖**

"Dataset.metadata.class_info.heads 에서 스키마 구조 필드(name/multi_label/class_mapping) 를 들어내고 per_head_class_counts 만 남기는 리팩토링" 은 SSOT 원칙에 더 부합하지만, 실제 범위가 **BE 생성 경로 2곳 + FE 타입·뷰어 2곳 + Alembic data migration** 까지 묶여 이번 세션에 넣으면 다른 변경과 섞이는 위험이 있다. 구조는 **동일 내용 copy 로 유지** + SSOT 시맨틱만 §2-8 에 명시. 실제 축소는 별도 세션 (§5 항목 26).

### 5-3. class_info 의 현 상태 시맨틱

- `Dataset.metadata.class_info.heads` 는 이제 "Dataset 생성 시점의 group.head_schema 스냅샷 + per-dataset 통계" 역할이다.
- 생성 경로 2곳 (`register_classification_tasks.register_classification_dataset`, `pipeline_tasks._execute_pipeline`) 이 SSOT 와 동일한 구조로 만들므로 불일치할 구조적 경로가 없다.
- 외부에서 수동으로 DB 를 건드리지 않는 한 SSOT 와 class_info.heads 는 동일하다고 가정해도 안전.

---

## 6. 검증

### 6-1. 회귀 테스트

- `cd backend && uv run pytest -q` → **446 passed in 0.61s** (4번 반복 확인, 각 커밋 뒤)

### 6-2. 실데이터 검증

8개 classification 그룹 (FUSION 1 + RAW 3 + SOURCE 4) 모두 백필 후 `head_schema IS NOT NULL` 확인.

이전에 `HEAD_SCHEMA_MISSING` 경고 받던 dataset:

- `a55fe491-1625-460c-bd58-f9113fbf5990` (hardhat_bodyonly_upperbody / VAL / 1.0) → curl 검증 시 `{"task_kind":"classification","head_schema":[{"name":"visibility","multi_label":false,"classes":["0_unseen","1_seen"]}],"error_code":null,"error_message":null}` 정상 반환.

### 6-3. Alembic 왕복

`028 → 029 upgrade` 성공. `029 downgrade` 는 no-op (의도됨). `alembic current` = `029_backfill_group_head_schema (head)`.

---

## 7. 후속 TODO (설계서 §5 항목 24 / 25 / 26)

이 브랜치가 의도적으로 미룬 항목들. 모두 우선순위 낮음. 먼저 필요해지는 시점에 별도 세션으로.

### 7-1. `24` — Group 명 변경 기능

REST `PATCH /dataset-groups/{id}` (name 필드 수정) + 스토리지 경로 `mv` + 해당 그룹 Dataset 행들의 `storage_uri` 갱신. 규모는 작음 (폴더 mv + DB UPDATE 소량). 사용자가 기존 그룹명을 유지·교체하고 싶을 때의 편의.

### 7-2. `25` — RAW 등록 시 자동 rename 제안 UX

신규 등록 schema 가 기존 동명 그룹과 다르면 "기존 그룹을 `<name>_deprecated_<YYMMDD>_<HHMM>` 로 rename 하고 새 그룹으로 등록할까요?" 모달. `_deprecated_*` 는 네이밍일 뿐 시스템 의미 없음. 7-1 위에 얹는 UI 레이어.

### 7-3. `26` — `Dataset.metadata.class_info` 축소 리팩토링

`heads` 에서 스키마 구조 필드(name/multi_label/class_mapping) 제거, `per_head_class_counts` 만 남김. 뷰어는 group.head_schema + 통계 조합으로 렌더. 범위:

- BE 생성 경로 2곳 (`register_classification_tasks.py`, `pipeline_tasks.py`)
- FE 타입 (`ClassificationClassInfo` / `ClassificationHeadInfo`)
- FE 뷰어 2곳 (`classificationDefinition.tsx` 의 `HeadDetailContent`, `dataLoadDefinition.tsx` 의 class info 표시)
- Alembic data migration (기존 row 에서 heads 축소)

한 번에 묶어야 깨지지 않으므로 반드시 단일 세션에서 일괄 처리.

---

## 8. 자동화 목업과의 관계 (핸드오프 023)

핸드오프 023 (`feature/pipeline-automation-mockup`) 는 이번 세션 시작 시점에 "자동화 모델 확정 + 목업 스코프 + 진입 전 결정 필요 7건" 까지 정리하고 **기술 검토 노트만** main 에 머지된 상태였다. 사용자가 목업을 만들려고 RAW → SOURCE 파이프라인을 준비하다가 preview-schema 버그를 발견해 자동화 목업을 일시 중단하고 이번 세션으로 분기했다.

이번 세션이 끝난 시점에는 `feature/pipeline-automation-mockup` 브랜치가 삭제된 상태이며, 본격 착수 전 재생성 + `024` 의 SSOT 보장 위에서 진행해야 한다. 자동화 목업 재개 시 참조할 문서는:

- 자동화 동작 모델: `docs_for_claude/023-automation-mockup-tech-note.md` §1-1 / §6
- 목업 진입 전 블로킹 결정 7건: 같은 문서 §7

---

## 9. 유의사항 (main 머지 후에도 영구 유효)

- **`_diff_head_schema` 의 NEW_HEAD / NEW_CLASS warning 허용은 폐지됐다.** 과거 핸드오프 015 §4 의 "분기 키: `Dataset.annotation_format === 'CLS_MANIFEST'` 또는 `DatasetGroup.head_schema != null`" 도 여전히 유효하지만, 이제 preview-schema 는 **`DatasetGroup.task_types` 기반 판정** 이 주경로다. head_schema 유무는 보조 신호 (NULL = 무결성 이슈 경고 대상).
- **`pipeline_tasks._execute_pipeline` 의 group.head_schema setdefault 는 "신규 그룹 안전망" 용도.** 같은 그룹에 다른 schema 로 파이프라인을 돌리는 건 `_validate_output_schema_compatibility` 에서 이미 `OUTPUT_SCHEMA_MISMATCH` 로 차단되므로 이 시점에는 재검사 없이 setdefault 만 수행.
- **FS 의 `head_schema.json` 은 DB 가 유실됐을 때의 복구 포인트이기도 하다.** 이번 세션 알렘빅 029 는 `metadata.class_info.heads` 에서 복원했지만, 혹시 그것마저 비어있으면 `<storage>/.../head_schema.json` 을 파싱하는 대안 경로를 만들 수도 있다 (현재는 필요 없음).
- **Dataset.metadata.class_info.heads 는 SSOT 스냅샷이므로 수동으로 건드리지 말 것.** 필요하면 SSOT(Group) 를 바꾸고 파이프라인을 재실행하는 것이 정석.

---

## 10. 참조

- 설계서 (현행): `objective_n_plan_7th.md` (v7.8, 2026-04-22)
- 이전 통합 핸드오프 (main 머지 완료): `docs_history/handoffs/022-classification-dag-chapter-closure-handoff.md` (main 머지 후 아직 이동 안 됐을 수 있음. 자동화 목업 브랜치에서 이동 예정이었으나 이번 세션이 먼저 들어감)
- 동시대 미진행: `docs_for_claude/023-automation-mockup-tech-note.md`
- Classification 스키마 계약 배경 memory: `project_classification_head_schema_contract.md`
- 노드 SDK 가이드: `docs/pipeline-node-sdk-guide.md`
