# 통합 핸드오프 019 — `null` = unknown 규약 확정 + 코드 반영 완료

> 최종 갱신: 2026-04-17
> 이전 핸드오프: `docs_history/handoffs/018-image-level-unknown-semantics-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.4, §2-12 확정)
> 이번 세션 브랜치: `feature/classification-dag-implementation-01`
> 주요 커밋:
> - `eb8379d` docs: 7차 설계서 v7.4 + 018 핸드오프 — image-level unknown 라벨 규약 확정
> - `c18a14a` refactor(classification): null=unknown 규약 코드 반영 — §2-12 확정

018 에서 옵션 A~D 로 열어두었던 image-level unknown 라벨 규약을 확정하고
코드 전면 반영을 완료한 세션이다. 기존 옵션 어디에도 해당하지 않는 별도
방식(`null` = unknown)을 채택했으며, 기존 classification 데이터는 사용자가
전량 삭제 후 재등록하기로 합의했다.

---

## 1. 이번 세션에서 적용된 변경

### 1-1. 설계 결정 — `null` = unknown 규약 (§2-12 확정)

018 §2-4 의 옵션 A~D 를 검토한 뒤 별도 방식을 채택:

| `labels[head]` 값 | 의미 | 학습 시 해석 |
|---|---|---|
| `null` | unknown — 판단 안 함 | 해당 head loss mask (학습에서 제외) |
| `[]` | explicit empty — 명시적 전부 neg | multi-label: BCE all zero, single-label: **허용 안 함** |
| `["class", ...]` | known label(s) | 정상 학습 대상 |

**핵심 원칙:**
- **타입**: `dict[str, list[str] | None]`
- **Single-label head 제약**: `null` 또는 `[class 1개]`만 허용. `[]` 및 그 외는 writer assert 에러.
- **Per-class unknown 미지원**: 1개라도 unknown 이면 head 전체를 `null` 로 승격. "조금 덜 학습" > "잘못 학습".
- **방어 전략**: writer strict assert 단일. reader 방어 없음, migration 없음.
- **기존 데이터**: 전량 삭제 후 재등록 (사용자 수행).

### 1-2. 코드 반영 (`c18a14a`)

| 파일 | 변경 내용 |
|---|---|
| `lib/pipeline/pipeline_data_models.py` | `ImageRecord.labels` 타입 `dict[str, list[str] \| None] \| None` + docstring |
| `lib/classification/ingest.py` | head 초기화 `[]` → `None` (unknown) |
| `lib/pipeline/io/manifest_io.py` | reader: `null` → `None` 보존. writer: single-label assert 추가 |
| `lib/manipulators/cls_merge_datasets.py` | `_align_labels_to_merged_heads` 누락 head → `None`. `_resolve_label_conflict` — `null` 직접 체크로 단순화 |
| `lib/manipulators/cls_rename_class.py` | `None` guard |
| `lib/manipulators/cls_reorder_classes.py` | `None` guard |
| `lib/manipulators/cls_select_heads.py` | `None` guard |
| `lib/manipulators/cls_rename_head.py` | `None` guard |
| `tests/test_cls_merge_datasets.py` | fill_empty assertion `[]` → `None`, docstring |

**테스트: 192건 전체 통과.**

### 1-3. 설계서 갱신 (`eb8379d`)

- `objective_n_plan_7th.md`: v7.3 → **v7.4**. §2-12 "결정 대기" → **확정**. §2-8/2-10/2-11-3/2-11-5 관련 문구 갱신. §5 작업 목록 갱신.
- `018-handoff.md`: §2-5 확정 결과, §3-1 완료, §4 규약 갱신, §5 전부 결정 완료.

---

## 2. 현재 Registry 상태 (22종)

**Detection 12종 (전부 실구현):** 변동 없음.

**Classification 10종:**
- ✅ 실구현 6종: `cls_rename_head`, `cls_rename_class`, `cls_reorder_heads`, `cls_reorder_classes`, `cls_select_heads`, `cls_merge_datasets`
- 🚧 stub 4종: `cls_filter_by_class`, `cls_remove_images_without_label`, `cls_sample_n_images`, `cls_merge_classes`

---

## 3. 다음 작업 체크리스트

### 3-1. `cls_merge_classes` 실구현 + multi→single 강등 노드 신설

- `cls_merge_classes`: head 내 class 통합. per-class unknown 발생 시 head 전체 `null` 승격.
- 강등 노드 이름 확정: **`cls_demote_head_to_single_label`**
- 동작 규약(초안): params `head_name`, `strategy: keep_first|keep_only_if_single|error_on_multi`. `labels[head]=null` 이면 `null` 유지.

### 3-2. 잔여 Classification stub 실구현 (3종)

- `cls_filter_by_class` — 특정 class 포함/미포함 이미지 필터
- `cls_remove_images_without_label` — unknown(`null`) 이미지 제거. `[]`(explicit empty)는 대상 아님 (single-label 에선 writer assert 에러, multi-label 에선 정상 값)
- `cls_sample_n_images` — N장 랜덤 샘플링
- 선행: `lib/pipeline/io/` CLS_MANIFEST 쓰기 경로 재검증

### 3-3. 이후 작업 (설계서 §5 참조)

- Automation 실구현 (9번)
- Detection manipulator 2종 (10번)
- Phase 3 / Step 2 이후 (12~16번)

### 3-4. 참조 문서

1. `objective_n_plan_7th.md §2-12` — `null` = unknown 확정 규약 (v7.4).
2. `docs/pipeline-node-sdk-guide.md §3` — manipulator 추가 레시피.
3. `backend/lib/classification/ingest.py` — `None` 초기화 지점.
4. `backend/lib/pipeline/io/manifest_io.py` — writer single-label assert.
5. `backend/lib/manipulators/cls_merge_datasets.py` — `_resolve_label_conflict` (`null` 기반).
6. `backend/tests/test_cls_merge_datasets.py` — 9건 회귀 테스트.

---

## 4. 유의사항 / 규약 (018 승계 + 갱신)

018 §4 전부 승계. 이번 세션 갱신:

- **`null` = unknown, `[]` = explicit empty 코드 반영 완료**. 모든 classification manipulator 가 `None` guard 를 포함한다.
- **single-label head 에서 `[]` 는 manifest_io writer assert 에러**. 디스크에 기록되기 전에 차단됨.
- **per-class unknown → head 전체 `null` 승격**. 신규 manipulator 도 이 원칙을 따라야 한다.
- **기존 classification 데이터 전량 삭제 후 재등록** 합의됨. reader 방어/migration 스크립트 불요.
- **branch 상태**: `feature/classification-dag-implementation-01` — 미머지. PR/머지 여부는 사용자 판단.

---

## 5. 열린 질문

| 질문 | 상태 |
|------|------|
| 강등 노드 이름 | ✅ 확정 — `cls_demote_head_to_single_label` |
| `cls_remove_images_without_label` 의 "without label" 대상 | ✅ 확정 — `null`(unknown) 만 대상. `[]` 는 제외 (single-label: writer assert 에러, multi-label: all neg 정상 값) |
