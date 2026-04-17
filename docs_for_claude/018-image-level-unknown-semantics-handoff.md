# 통합 핸드오프 018 — Classification image-level `unknown` 라벨 규약 확정

> 최종 갱신: 2026-04-17
> 이전 핸드오프: `docs_history/handoffs/017-classification-dag-ready-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.4, §2-12 확정)
> 이번 세션 브랜치: `feature/classification-dag-implementation-01`
> 주요 커밋:
> - `73059c7` cls_merge_datasets 실제 구현 + 호환성 검증 공유화
> - `130dc5f` cls_merge_datasets — fill_empty 로 채운 head 를 unknown 으로 처리 (버그 수정 + 회귀 테스트 9종)

017 이후 `cls_merge_datasets` 실구현과 한 건의 중대 버그 수정이 진행되며,
그 과정에서 **image-level "unknown" 라벨 규약이 multi-label 쪽에서는 정의되어
있지 않다** 는 근간급 갭이 드러났다. 다음 세션에서는 이 갭부터 해소한다 —
`cls_merge_classes` 실구현과 multi→single **강등** 노드(이름 미배정) 가 모두
이 결정에 의존한다.

---

## 1. 이번 세션(016→018)에서 적용된 변경

### 1-1. `cls_merge_datasets` 실구현 (`73059c7`)

`objective_n_plan_7th.md §2-11` 규약(옵션 3종)을 완전 구현.

- `backend/lib/pipeline/cls_merge_compat.py` — FE/BE 공용 호환성 검증 모듈 신설
  (규칙 drift 방지). `check_merge_schema_compatibility` / `resolve_merge_params`
  / `preview_head_schema_at_task` 제공.
- `backend/lib/manipulators/cls_merge_datasets.py` — `accepts_multi_input=True`.
  Head/class union + multi_label_union 승격 + SHA dedup + file_name 충돌 rename +
  3옵션 기반 label 충돌 판정.
- `backend/app/services/pipeline_service.py` — `_validate_cls_merge_compatibility`
  가 각 merge 입력의 head_schema 를 `preview_head_schema_at_task` 로 계산한 뒤
  동일 compat 규칙을 돌려 `PipelineValidationIssue` 로 분배.
- `backend/migrations/versions/019_cls_merge_params.py` — params_schema 3옵션 select
  (`on_head_mismatch` / `on_class_set_mismatch` / `on_label_conflict`).
- `frontend/src/pipeline-sdk/definitions/mergeDefinition.tsx` — taskType 별
  `det_/cls_merge_datasets` 디스패치 + `multi_label_union` 승격 확인 모달(§2-11-4).
- `backend/tests/test_cls_merge_datasets.py` — 9 케이스 (이번 세션에서 추가).

### 1-2. `fill_empty` 가 만들어낸 head 를 "unknown" 으로 처리 (`130dc5f`)

**증상** — 동일 SHA 5613 장을 merge 하면 전부 생존해야 할 시나리오에서 3125 장이
`single_label_mismatch(head=wear)` 로 드롭됐다. 입력 A 는 head `wear`, 입력 B 는
`hardhat_wear` 만 있어 fill_empty 로 양쪽이 서로 상대 head 를 `[]` 로 채운
상태였다.

**원인** — `_resolve_label_conflict` 가 per_input_labels 수집 단계에서 head 가
**해당 입력의 원본 schema 에 없었던 것** 과 **있었는데 라벨이 비어있는 것** 을
구분하지 않고 모두 `labels.get(head_name, []) = []` 로 취급했다. 그래서
`distinct_label_sets={('0_no_helmet',), ()}` 가 되어 single-label 충돌로 판정.

**수정** — per_input_labels 수집 시 `head_name not in original_classes_per_input[input_index]`
occurrence 를 건너뛰어 "unknown 기여" 로 분류. 모든 입력이 head 를 갖지 않으면
`[]` 로 확정(fill_empty 취지 유지). 재실행으로 5613장 생성 확인.

### 1-3. `cls_merge_classes` stub 재확인

여전히 stub. 구현은 §2-12 결정(=image-level unknown 정의) 확정 후 진행.

### 1-4. multi→single **강등** 노드 — 설계서에만 이름 없이 언급된 상태

`§2-11-4` 의 "이후 `cls_merge_classes` / multi→single 변환 노드로 해소 책임은
사용자" 문구 외에 이름·스펙 모두 없음. 이것도 §2-12 결정에 의존.

---

## 2. 드러난 근간급 갭 — image-level `unknown` 규약

### 2-1. 현재 상태(묵시 규약)

`backend/lib/classification/ingest.py:314` 에서 `labels_out` 을 모든 head 에
대해 `[]` 로 초기화한 뒤, 해당 이미지가 발견된 class 폴더만 채워 넣는다.

```python
labels_out: dict[str, list[str]] = {head.name: [] for head in heads}
head_class_seen: dict[str, set[str]] = {head.name: set() for head in heads}
for occ in record["occurrences"]:
    if occ.head_name in head_class_seen:
        head_class_seen[occ.head_name].add(occ.class_name)
for head in heads:
    labels_out[head.name] = sorted(head_class_seen[head.name])
```

즉, 어떤 이미지가 `{head}/{class}/` 하위 어디에도 없으면 → `labels[head] = []`.
설계 대화에서 결정됐던 의도는 **single-label head 에서 `labels[head] = []` = unknown (판단 안 함)**.
이 규약은 코드에만 존재하고 `objective_n_plan_7th.md` 본문에는 명문화되어 있지 않았다 (이번 v7.3 §2-12 에서 명시).

### 2-2. 문제 — multi-label 에서 `[]` 의 의미

| 시맨틱 | single-label `labels[h] = []` | multi-label `labels[h] = []` |
|---|---|---|
| **ingest 설계 의도** | unknown (판단 안 함) | 어떤 class 폴더에도 안 들어감 |
| **학습 시 자연스러운 해석** | "판단 없음 — target masked" | **전부 neg** (BCE all zero) |
| **현 merge 구현에서의 해석** | ingest + `original_classes_per_input` 로 unknown 간접 복원 (fix 130dc5f 후) | pos 리스트로만 사용 — class 별 pos/explicit_neg/unknown 은 head schema(데이터셋-수준) 로 판정 |

두 경로가 같은 저장 형태(`list[str]`, 빈 리스트 허용)를 공유하는데,
**multi-label 의 image-level unknown 은 표현 자체가 없다**.

추가로:

- **Multi-label head 의 per-class unknown 불가**. head.classes=[a, b, c] 중 a=pos
  이고 b 는 판단 안 됐고 c 는 판단 없음 — 현 schema 는 `[a]` 로만 쓸 수밖에 없고
  그 순간 b/c 는 자동 neg 로 학습된다.
- **single-label head 의 "이 이미지에 해당 없음 (N/A)"** 도 현재 unknown 과
  구분 불가. 예: `helmet_color` head 가 있는 데이터셋에서 helmet 자체가 없는
  이미지 — "해당 없음" 과 "판단 안 함" 이 똑같이 `[]` 로 표현됨.

### 2-3. 영향 범위 (왜 근간을 흔드는지)

| 도메인 | 영향 |
|---|---|
| **학습 target** | multi-label 은 BCE 전부 이진 → unknown 을 loss mask 로 배제하는 기법 적용 불가 |
| **Auto-labeling / 부분 라벨링 파이프라인** (Step 4) | 확신 낮은 class 를 unknown 으로 남기는 표현 불가 → 전부 hard negative 로 강제 학습됨 |
| **merge 의미론** | 130dc5f 에서 dataset-level schema 를 참고해 간접 복원. **동일 dataset 내 image 별로 head 판단 가능 여부가 다른 경우** 여전히 표현 불가 |
| **Multi-label 승격 후 강등** | 승격된 head 에서 image 별로 일부 class 가 unknown 이어야 할 때 정보 손실 — 강등 노드가 근본적으로 데이터를 잃거나 잘못 결정해야 함 |
| **`cls_merge_classes`** | source_classes 중 일부만 찍힌 이미지에서 나머지의 unknown 여부를 구분해야 의미 있음. 현 스키마로는 구분 불가 |

### 2-4. 설계 옵션 (결정 전 초안)

**옵션 A — 값을 class 상태 dict 로 확장 (강한 표현력, 파급 큼)**
```jsonc
"labels": {
  "wear":  {"helmet": "pos", "no_helmet": "neg"},
  "color": {"red": "pos", "blue": "unknown", "black": "neg"}
}
```
- manipulator/IO/merge/학습 target 전부 재작업 필요.
- 완전. 추후 soft label(확률값) 확장 여지도 열림.

**옵션 B — 기존 pos list + unknown set 별도 저장 (호환성 유지, 증분)**
```jsonc
"labels":          {"wear": ["helmet"], "color": ["red"]},
"unknown_classes": {"color": ["blue"]}
```
- 기본은 closed-world 유지, unknown 만 opt-in 기록.
- 기존 manipulator/IO 대부분 무변경.

**옵션 C — Head-level unknown 마스크만 (경량)**
```jsonc
"labels":        {"wear": ["helmet"]},
"unknown_heads": ["color"]
```
- head 단위로 "이 이미지에 대해 해당 head 판단 안 함" 만 표현.
- per-class unknown 불가 — auto-labeling 부분 라벨 시나리오 해결 못 함.

**옵션 D — 구조 불변, 규약만 재정의**
- `labels` dict 에 head key **없음 = unknown**, **빈 리스트 = 명시적 empty(all neg)**.
- manifest_io / merge / 학습 loader 해석만 바뀜.
- multi-label 내 per-class unknown 은 여전히 불가.

### 2-5. ~~결정 시 고려해야 할 요건~~ → 확정 완료 (2026-04-17)

**결정: `null` = unknown (head-level)** — 옵션 A~D 어디에도 정확히 해당하지 않는 별도 방식.

- `labels[head] = null` → unknown (학습 시 loss mask)
- `labels[head] = []` → explicit empty (multi-label: BCE all zero)
- Single-label head 제약: `null` 또는 `[class 1개]`만 허용, `[]` 및 그 외는 writer assert 에러
- Per-class unknown 미지원 → **head 전체 `null` 승격** 원칙 ("조금 덜 학습" > "잘못 학습")
- 기존 classification 데이터 전량 삭제 후 재등록 → reader 방어/migration 불요
- Step 4 auto-labeling 진입 시 per-class unknown 필요하면 옵션 A/B 확장 재검토

상세는 `objective_n_plan_7th.md §2-12` (v7.4 확정) 참조.

---

## 3. 다음 작업 체크리스트

### 3-1. ~~설계 결정~~ ✅ 완료 (2026-04-17)

`null` = unknown 규약 확정. `objective_n_plan_7th.md §2-12` 에 명문화 완료.
3. 기존 classification 데이터셋 migration 전략 정의 (필요 시):
   - ~~옵션 B 선택 시~~ / ~~옵션 A 선택 시~~ → 해당 없음. `null` 규약 채택, 기존 데이터 삭제 후 재등록.

### 3-2. 코드 반영 범위 (`null` 규약 확정 기준)

| 파일 | 필요 작업 | 상태 |
|------|-----------|------|
| `lib/classification/ingest.py` | head 초기화 `[]` → `None` | 미착수 |
| `lib/pipeline/io/manifest_io.py` | writer 에 single-label assert 추가 (`null` or `[1개]`만 허용) | 미착수 |
| `lib/manipulators/cls_merge_datasets.py` | `fill_empty` → `None`, `_resolve_label_conflict` 단순화 (`original_classes_per_input` 우회 제거, `null` 직접 체크) | 미착수 |
| `lib/manipulators/cls_rename_class.py` | `None` guard 추가 | 미착수 |
| `lib/manipulators/cls_reorder_classes.py` | `None` guard 추가 | 미착수 |
| `backend/tests/test_cls_merge_datasets.py` | `[]` → `None` 반영 | 미착수 |
| `lib/manipulators/cls_merge_classes.py` | **stub → 실구현** — per-class unknown 시 head 전체 `null` 승격 | 후속 |
| `lib/manipulators/cls_demote_*.py` | **신규** — multi→single 강등 | 후속 |

**reader 방어 로직 / migration 스크립트: 불요** — 기존 classification 데이터 전량 삭제 후 재등록.

### 3-3. 강등 노드 — 이름 후보 (미결정)

§2-11-4 가 `multi→single 변환` 이라고만 부르고 이름 미배정. manipulator 네이밍
메모리(`feedback_manipulator_naming.md`) 기준 "동작 대상 + 조건 + 방법" 을
모두 담은 서술형 snake_case:

- `cls_demote_head_to_single_label` — 명료
- `cls_collapse_multi_label_to_single` — 의미 강조
- `cls_reduce_head_to_single_label` — 중립

동작 규약(초안):
- params: `head_name: str`, `strategy: "keep_first" | "keep_only_if_single" | "error_on_multi"`
- head 의 `multi_label` 플래그를 False 로.
- 이미지별 labels 가 2개 이상이면 strategy 에 따라 처리 (첫 값 유지 / drop_image / error).
- 이미지별 `labels[head]` 가 `null` (unknown) 이면 `null` 유지 (§2-12 확정 규약).

### 3-4. 참조 문서

1. `objective_n_plan_7th.md §2-10, §2-11, §2-12` (§2-12 **확정**, v7.4).
2. `docs/pipeline-node-sdk-guide.md §3` — manipulator 추가 레시피(변경 없음).
3. `backend/lib/classification/ingest.py:314` — `[]` 초기화 지점 → `None` 으로 변경 예정.
4. `backend/lib/manipulators/cls_merge_datasets.py:449-539` — `_resolve_label_conflict` → `null` 기반 단순화 예정.
5. `backend/lib/pipeline/cls_merge_compat.py` — 공유 호환성 검증.
6. `backend/tests/test_cls_merge_datasets.py` — 기존 9 회귀 테스트.

---

## 4. 유의사항 / 규약 (017 승계 + 갱신)

017 §4 전부 승계. v7.4 확정 후 갱신:

- **`null` = unknown, `[]` = explicit empty** 가 공식 규약 (§2-12 확정). 모든 classification 코드는 이 규약을 따른다.
- **single-label head 에서 `[]` 는 writer assert 에러**. `null` (unknown) 또는 `[class 1개]` (known) 만 허용.
- **per-class unknown 발생 시 head 전체 `null` 승격**. "조금 덜 학습" > "잘못 학습".
- **기존 classification 데이터셋 전량 삭제 후 재등록**. reader 방어 / migration 스크립트 불요.
- **branch 상태**: `feature/classification-dag-implementation-01` — 미머지. PR/머지 여부는 사용자 판단.

---

## 5. ~~열린 질문~~ → 결정 완료 (2026-04-17)

| 질문 | 결정 |
|------|------|
| 옵션 A/B/C/D 중 어느 방향? | **별도 방식 — `null` = unknown** (head-level, 구조 최소 변경) |
| per-class unknown 필수? | **아니오** — head-level 승격 원칙으로 대체. Step 4 진입 시 재검토 |
| 기존 manifest migration? | **불요** — 전량 삭제 후 재등록 |
| 강등 노드 이름? | 미결정 — 후보 3종 (§3-3) |
| single-label N/A vs unknown 구분? | **구분 안 함** — 둘 다 `null`. Step 4 이후 필요 시 확장 |
