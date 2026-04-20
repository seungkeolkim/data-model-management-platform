# 통합 핸드오프 019 — `null` = unknown 규약 확정 + cls 강등·샘플링 실구현

> 최종 갱신: 2026-04-17
> 이전 핸드오프: `docs_history/handoffs/018-image-level-unknown-semantics-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.5)
> 이번 세션 브랜치: `feature/classification-dag-implementation-01`
> 주요 커밋:
> - `eb8379d` docs: 7차 설계서 v7.4 + 018 핸드오프 — image-level unknown 라벨 규약 확정
> - `c18a14a` refactor(classification): null=unknown 규약 코드 반영 — §2-12 확정
> - `3087bdc` feat(manipulator): cls_merge_classes 실구현 + 팔레트 활성화 + 경고 모달
> - `38b73c3` fix(pipeline-task): classification class_info 생성 시 null(unknown) labels 처리
> - `a7c1cba` feat(manipulator): cls_demote_head_to_single_label 실구현 + 팔레트 활성화 + 경고 모달
> - `535aace` feat(manipulator): cls_sample_n_images 실구현 + 팔레트 활성화

018 에서 옵션 A~D 로 열어두었던 image-level unknown 라벨 규약을 확정하고
코드 전면 반영을 완료했다. 이후 `cls_merge_classes` 실구현, 팔레트 활성화,
파이프라인 실행 시 null labels 버그 수정, `cls_demote_head_to_single_label` (multi→single 강등),
`cls_sample_n_images` (N장 랜덤 샘플) 실구현까지 진행했다.

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

### 1-3. `cls_merge_classes` 실구현 (`3087bdc`)

| 파일 | 변경 내용 |
|---|---|
| `lib/manipulators/cls_merge_classes.py` | stub → 실구현. head 내 class 병합 (single-label OR / multi-label OR). `_parse_source_classes` 로 textarea 줄바꿈 문자열 수용 |
| `tests/test_cls_merge_classes.py` | 17건 신규 (single/multi/null/schema/에러/textarea 파싱) |
| `migrations/versions/020_cls_merge_classes_params.py` | DB params_schema: `merged_into` → `target_class` 갱신 |
| `frontend/.../operatorDefinition.tsx` | `UNIMPLEMENTED_OPERATORS` 에서 제거 → 팔레트 활성화. `CONFIRM_WARNING_OPERATORS` 로 경고 모달 추가 |
| `frontend/.../types.ts` | `PaletteItem.confirmWarning` 필드 추가 |
| `frontend/.../NodePalette.tsx` | `confirmWarning` 분기 — `Modal.confirm` 으로 경고 후 추가 |

**테스트: 209건 전체 통과.**

### 1-4. 파이프라인 실행 null labels 버그 수정 (`38b73c3`)

| 파일 | 변경 내용 |
|---|---|
| `app/tasks/pipeline_tasks.py` | classification class_info 생성 시 `labels[head]=None`(unknown) 에서 `for class_name in None` 순회 에러 — `None` guard 추가 |

**배경**: §2-12 null 규약 반영 시 `pipeline_tasks.py` 가 누락되어, 파이프라인 정상 실행 후 class_info 메타데이터 생성 단계에서 `'NoneType' object is not iterable` 에러 발생.

### 1-5. `cls_demote_head_to_single_label` 실구현 (`a7c1cba`)

| 파일 | 변경 내용 |
|---|---|
| `lib/manipulators/cls_demote_head_to_single_label.py` | 신규. multi-label head → single-label 강등. `on_violation` param (skip/fail) |
| `tests/test_cls_demote_head_to_single_label.py` | 17건 신규 (정상 강등/null 보존/skip·fail/passthrough/에러) |
| `migrations/versions/021_seed_cls_demote_head.py` | DB seed — category `CLS_HEAD_CTRL`, select 타입 on_violation |
| `frontend/.../operatorDefinition.tsx` | `CONFIRM_WARNING_OPERATORS` 에 강등 경고 모달 추가 |
| `frontend/.../styles.ts` | 팔레트 순서 + 이모지(⬇️) 추가 |

**테스트: 226건 전체 통과.**

### 1-6. `cls_sample_n_images` 실구현 (`535aace`)

| 파일 | 변경 내용 |
|---|---|
| `lib/manipulators/cls_sample_n_images.py` | stub → 실구현. det_sample_n_images 와 동일 로직 (seed 고정 재현성) |
| `tests/test_cls_sample_n_images.py` | 12건 신규 (기본 샘플/전체 유지/seed 재현/head_schema 보존/null 보존/에러) |
| `migrations/versions/022_cls_sample_params_fix.py` | params_schema type "int" → "number" (DynamicParamForm 호환) |
| `frontend/.../operatorDefinition.tsx` | `UNIMPLEMENTED_OPERATORS` 에서 제거 → 팔레트 활성화 |

**테스트: 238건 전체 통과.**

### 1-7. 설계서 갱신 (`eb8379d` + 이후 갱신)

- `objective_n_plan_7th.md`: v7.3 → v7.4 → **v7.5**. §2-12 확정, §2-4 registry 현황 갱신, §5 작업 목록 갱신, §6 방법론 메모 신설.
- `018-handoff.md`: §2-5 확정 결과, §3-1 완료, §4 규약 갱신, §5 전부 결정 완료.

---

## 2. 현재 Registry 상태 (23종)

**Detection 12종 (전부 실구현):** 변동 없음.

**Classification 11종:**
- ✅ 실구현 9종: `cls_rename_head`, `cls_rename_class`, `cls_reorder_heads`, `cls_reorder_classes`, `cls_select_heads`, `cls_merge_datasets`, `cls_merge_classes`, `cls_demote_head_to_single_label`, `cls_sample_n_images`
- 🚧 stub 2종: `cls_filter_by_class`, `cls_remove_images_without_label`

---

## 3. 다음 작업 체크리스트

### 3-1. 잔여 Classification stub 실구현 (2종)

- `cls_filter_by_class` — 특정 class 포함/미포함 이미지 필터
- `cls_remove_images_without_label` — unknown(`null`) 이미지 제거. `[]`(explicit empty)는 대상 아님

### 3-2. Classification 이미지 변형 노드 (신규)

- `cls_crop_image` — 이미지 상하 Crop (상단 N%, 하단 M% 잘라 저장). SHA 재계산 + file_name 갱신 필요
- `cls_rotate_image` — 이미지 회전. det_rotate_image 와 동일 로직, classification 자료구조 대응
- Jpeg Quality 조정은 포함하지 않음
- ⚠️ 이미지 변형 시 SHA 변경 문제 — 설계서 §6-1 방법론 참조

### 3-3. Classification Annotation 기반 이미지 필터 (신규)

- 특정 head 의 특정 class 값 조건으로 이미지 필터링 (예: `visible` head 에서 `0_seen` 인 이미지만 유지)
- `cls_filter_by_class` 의 확장 또는 별도 노드로 구현

### 3-4. Classification Head 추가 노드 (신규)

- `cls_add_head` — 기존 데이터셋에 새 head 추가. 추가할 head 이름, class candidate 목록을 params 수신
- 기존 이미지의 신규 head labels 는 `null` (unknown, §2-12)

### 3-5. Classification Annotation 일괄 변경 노드 (신규)

- 특정 head 의 labels 를 일괄적으로 특정 값으로 설정 (예: `visible` head 를 전부 `null`(unknown) 으로 설정)

### 3-6. 이후 작업 (설계서 §5 참조)

- Automation 실구현 (15번)
- Detection manipulator 2종 (16번)
- Phase 3 / Step 2 이후 (18~22번)

### 3-7. 참조 문서

1. `objective_n_plan_7th.md §2-12` — `null` = unknown 확정 규약 (v7.5).
2. `docs/pipeline-node-sdk-guide.md §3` — manipulator 추가 레시피.
3. `backend/lib/classification/ingest.py` — `None` 초기화 지점.
4. `backend/lib/pipeline/io/manifest_io.py` — writer single-label assert.
5. `backend/lib/manipulators/cls_merge_datasets.py` — `_resolve_label_conflict` (`null` 기반).
6. `backend/lib/manipulators/cls_merge_classes.py` — head 내 class 병합 (실구현 완료).
7. `backend/lib/manipulators/cls_demote_head_to_single_label.py` — multi→single 강등 (실구현 완료).
8. `backend/lib/manipulators/cls_sample_n_images.py` — N장 랜덤 샘플 (실구현 완료).
9. `backend/tests/test_cls_merge_datasets.py` — 9건 회귀 테스트.
10. `backend/tests/test_cls_merge_classes.py` — 17건 단위 테스트.
11. `backend/tests/test_cls_demote_head_to_single_label.py` — 17건 단위 테스트.
12. `backend/tests/test_cls_sample_n_images.py` — 12건 단위 테스트.
13. `backend/app/tasks/pipeline_tasks.py:220-228` — classification class_info 생성 (`None` guard 포함).

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
| 강등 노드 이름 | ✅ 확정 — `cls_demote_head_to_single_label` (실구현 완료) |
| `cls_remove_images_without_label` 의 "without label" 대상 | ✅ 확정 — `null`(unknown) 만 대상. `[]` 는 제외 |
| 이미지 변형 시 SHA 사전 계산 | 🔓 미결 — 설계서 §6-1 에 접근법 (a)~(c) 정리. 구현 전 결정 필요 |
| Binary label type (BCEWithLogitsLoss) | 🔓 미결 — 설계서 §6-2 에 접근법 (a)~(c) 정리. Step 2 학습 진입 전 결정 필요 |
