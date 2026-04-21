# 통합 핸드오프 022 — Classification DAG 실구현 챕터 종결 + main 머지 준비

> 최종 갱신: 2026-04-21 (§11 post-merge 버그 수정 추가)
> 이전 핸드오프: `docs_history/handoffs/021-cls-rotate-and-new-stubs-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.7)
> 이번 세션 브랜치: `feature/classification-dag-implementation-01` (main 머지 완료)
> 후속 버그 수정 브랜치: `feature/classification-pipeline-fix-error` (§11)

---

## 0. 이 핸드오프의 목적

브랜치 `feature/classification-dag-implementation-01` 은 fork(2026-04-15, handoff 017 직후) 부터
이 문서 작성 시점까지 약 6일간 진행된 장기 작업이었고, 내부적으로 **5개의 하위 챕터** (handoff
017 → 021) 를 거쳤다. main 머지 직전의 **마지막 한 지붕 아래 요약** 을 남겨 둬서, 이후 세션이
이 브랜치에서 무엇이 확정됐는지 handoff 를 한 개만 읽어도 파악할 수 있게 한다.

상세 구현 로그 / 의사결정의 원 맥락은 각 아카이브 handoff (017 ~ 021) 에 그대로 보존돼 있다.

---

## 1. 브랜치 개요

| 항목 | 값 |
|---|---|
| fork point (main) | `7de55cc` — "Merge branch 'feature/classification-pipeline-dag' — Classification DAG 에디터 + Celery runner + det_/cls_ prefix 통일" |
| fork 시점 설계서 | v7.2 (registry 25종, classification 10 stub) |
| 현재 설계서 | **v7.6** (registry 26종, classification 14 실구현) |
| 커밋 수 (first-parent, main 제외) | 42 |
| 이 브랜치가 추가한 Alembic 마이그레이션 | 14건 (015 ~ 028) |
| 전체 회귀 테스트 | **445 / 445 pass** (`cd backend && uv run pytest -q`) |
| Classification 전용 신규 테스트 파일 | 10개 (`test_cls_*.py` 9 + `test_classification_ingest.py`) |
| 브랜치에서 생성·아카이브된 handoff | 018, 019, 020, 021 (017 은 fork 시점의 active handoff → 이 브랜치 초반에 아카이브) |

---

## 2. 이 브랜치가 확정한 설계 / 규약 — 전부 baseline 편입

다음 6개 섹션은 이 브랜치에서 처음 명문화되거나 재정의되어 설계서 `objective_n_plan_7th.md`
baseline 에 편입됐다. 각 항목은 머지 후 "이 브랜치에서 확정됨" 으로 프로젝트의 항구적 규약이
된다.

### 2-1. §2-8 — Classification 이미지 identity: SHA → filename 전환 (handoff 020 / v7.5)

**내용.** 이미지 identity 를 **SHA-1 content hash → filename (full relative path)** 으로 전환.
`ingest_classification`, `cls_merge_datasets`, `dag_executor` (Phase B) 의 3곳에 분산되어 있던
SHA 계산·비교·dedup 로직을 전부 제거. `duplicate_image_policy` (FAIL/SKIP) 옵션과 관련 request
스키마 / Celery task / 등록 모달 UI 전부 폐지.

**Trade-off 수용.** 파일명이 다르지만 내용이 같은 사실상 중복 이미지는 서로 다른 이미지로
들어간다 — 사용자가 선행 단계에서 정리할 책임. 대가로 content hash 관련 호환성 부담이 0 이 됨.

### 2-2. §2-11-5 — Merge 시 label 충돌 판정 단계 삭제 (handoff 020 / v7.5)

**내용.** v7.4 까지 `cls_merge_datasets` 에 있던 `on_label_conflict` 옵션과 "동일 이미지 label
충돌" 판정 전체를 삭제. 파일명이 두 입력에서 충돌하면 detection 과 동일하게
`{display_name}_{md5_4}_{basename}` prefix rename 으로 **공존시킨다**. `ImageRecord.extra` 의
`source_storage_uri` / `original_file_name` / `source_dataset_id` 메타데이터로 Phase B 에서 원본
src 를 복원.

### 2-3. §2-12 — Image-level `unknown` 라벨 규약 (handoff 018, 019 / v7.4)

**내용.** `labels[head]: list[str] | None`.
- `null` → unknown, 학습 시 loss mask
- `[]` → explicit empty, multi-label BCE all zero (single-label 에서는 writer assert 에러)
- `["class", ...]` → known labels

**Per-class unknown 원칙 (중요).** "per-class 에서 1개라도 unknown 이면 → head 전체를 null 로
승격한다." 잘못된 neg 로 학습되는 것보다 해당 이미지의 head 를 통째로 mask 하는 것이 안전.
`cls_merge_datasets` / `cls_merge_classes` / `cls_demote_head_to_single_label` 이 이 원칙을 따름.

**방어 전략.** Writer (`manifest_io.py`) strict assert 단일. Reader 방어 로직 / migration
스크립트 없음 — 기존 classification 데이터는 전량 삭제 후 재등록 전제.

### 2-4. §2-13 — 뷰어 file_name 표시 규약 (handoff 020 / v7.5)

Classification 샘플 뷰어는 현재 storage pool 파일명(`file_name`)을 기본 식별자로 노출하고,
`original_file_name` 은 rename 이 발생해 두 값이 달라진 경우에만 "(원본: …)" 로 병기. 좌측
검색은 양쪽 매칭.

### 2-5. §6-1 — Classification 이미지 변형 파일명 rename 규약 (handoff 021 §1-3 / v7.5)

**배경.** §2-8 filename-identity 전환으로 "같은 파일명 = 같은 내용" 불변식을 유지해야 하므로,
이미지를 변형하는 모든 classification manipulator 는 파일명에 postfix 를 붙여 새 파일로
만들어야 한다. `cls_rotate_image` 실구현으로 확립한 규약을 `cls_crop_image` 가 그대로 상속.

**3가지 필수 동작.**
1. **파일명 postfix 삽입** — 확장자 앞, ASCII 만 사용, 멱등 (같은 params 두 번 → 같은 결과).
   - rotate: `_rotated_{degrees}`
   - crop:   `_crop_{up|down}_{pct:03d}` (Korean `상단`/`하단` → English `up`/`down` 정규화)
2. **src 복원 메타를 `record.extra` 에 최초 1회만 기록** — `source_storage_uri`,
   `original_file_name`. 값이 이미 있으면 **덮어쓰지 않는다** (merge 가 먼저 채워둔 진짜 원본을
   보존).
3. **`record.extra["image_manipulation_specs"]` 에 append** — 순서 = Phase B 적용 순서.
   operation 값은 prefix 없이 (`rotate_image`, `crop_image_vertical`).

**강제 조건.** head_schema/labels 건드리지 않음, list 입력 거부, `copy.deepcopy` 로 입력 격리,
차원 바뀌면 `record.width ↔ record.height` 갱신.

### 2-6. §6-2 — Binary label type (handoff 021 §1-1 / v7.5)

**결정: (c) 주 + (b) 보조.**
- **주:** 학습 config 에 head 별 `loss_per_head: dict[str, Literal["softmax", "bce", "bce_ovr"]]`
  필드 신설 (Step 2 진입 시 실장). 데이터 schema (`head_schema.multi_label`) 는 그대로.
- **보조:** UI 가 schema 에서 auto-suggest + 사용자 "검토 완료" 체크 강제.
- `len(classes) != 2` single-label head 에 `bce` 지정 시 명시 에러. OvR BCE 는 `bce_ovr` 로
  값 이름 분리.

데이터/manifest/manipulator 레이어는 전부 불변. Phase 2/3 에서는 결정만 기록.

---

## 3. 최종 Manipulator 레지스트리 (26종)

### 3-1. Detection — 12 실구현 / 2 미구현

- ✅ **실구현 (변동 없음):** `det_format_convert_to_coco`, `det_format_convert_to_yolo`,
  `det_format_convert_visdrone_to_coco`, `det_format_convert_visdrone_to_yolo`,
  `det_merge_datasets`, `det_filter_keep_images_containing_class_name`,
  `det_filter_remove_images_containing_class_name`,
  `det_filter_remain_selected_class_names_only_in_annotation`, `det_remap_class_name`,
  `det_rotate_image`, `det_mask_region_by_class`, `det_sample_n_images`
- 🚧 **미구현 (long-tail, 우선순위 낮음):** `det_change_compression`, `det_shuffle_image_ids`

### 3-2. Classification — **14 실구현 / 0 stub** (이 브랜치에서 전량 실구현 완료)

fork 시점에는 전부 stub (cls_rename_head 포함 10종이 8종 stub + 2 misc 상태) 이었고, 이
브랜치에서 아래 순서로 하나씩 실구현됨.

| # | manipulator | 구현 커밋 | 주요 특징 |
|---|---|---|---|
| 1 | `cls_rename_head` | `5a3f110` | key_value UX |
| 2 | `cls_rename_class` | `555abf0` | textarea UX + 라벨 |
| 3 | `cls_reorder_heads` | `0d01308` | — |
| 4 | `cls_reorder_classes` | `7b8ce39` | — |
| 5 | `cls_select_heads` | `ed0fb34` | whitelist → blacklist 전환 |
| 6 | `cls_merge_datasets` | `73059c7` / `130dc5f` | multi-input merge, `on_head_mismatch=fill_empty` + `on_class_set_mismatch=multi_label_union`, §2-12 unknown 규약 원인 |
| 7 | `cls_merge_classes` | `3087bdc` | head 내 class 병합 (single/multi-label OR) + 경고 모달 |
| 8 | `cls_demote_head_to_single_label` | `a7c1cba` | multi→single 강등, on_violation skip/fail |
| 9 | `cls_sample_n_images` | `535aace` | N 장 랜덤 샘플 |
| 10 | `cls_rotate_image` | `84e6b40` | 90°/180°/270° + §6-1 postfix rename 규약 확립 |
| 11 | `cls_add_head` | `916964f` + `56f784c` | 신규 head 를 schema 말단에 추가, DynamicParamForm checkbox/text 추가, 체인 내 중복 검증 |
| 12 | `cls_set_head_labels_for_all_images` | `54fb15c` + `56bcd5a` | head labels 일괄 overwrite + 정적 DB-aware 검증 (`FILTER_BY_CLASS_…` prefix 패턴의 원조) |
| 13 | `cls_crop_image` | `9e33476` | 수직축(상단/하단) 단일 crop, direction + crop_pct 2-필드, `_crop_up/down_{pct:03d}` postfix |
| 14 | `cls_filter_by_class` | `19118dc` | 기존 stub + `cls_remove_images_without_label` 통합 흡수. 4필드 (head_name / mode / classes / include_unknown), any-match v1 고정. §2-12 null/[] 규약 엄수 |

`cls_remove_images_without_label` 는 이 브랜치에서 stub 상태였다가 `mode=exclude, classes=[],
include_unknown=True` 조합으로 `cls_filter_by_class` 에 완전 흡수되어 **seed 삭제** (Alembic 027).

---

## 4. 이 브랜치가 추가한 Alembic 마이그레이션 (14건, 015 → 028)

| Rev | 내용 |
|---|---|
| 015 | classification manipulator 8종 description 간결화 |
| 016 | `cls_rename_class` params_schema 갱신 |
| 017 | `cls_select_heads` whitelist → blacklist 전환 반영 |
| 018 | `cls_reorder_classes` params_schema |
| 019 | `cls_merge_datasets` params_schema (on_head_mismatch / on_class_set_mismatch) |
| 020 | `cls_merge_classes` params_schema |
| 021 | `cls_demote_head_to_single_label` seed 신설 |
| 022 | `cls_sample_n_images` params_schema 보정 |
| 023 | cls 이미지 변형 2종 + head 조작 2종 stub seed (rotate/crop/add_head/set_head_labels) |
| 024 | `cls_add_head` params_schema 실구현 기준 갱신 |
| 025 | `cls_set_head_labels_for_all_images` params_schema 실구현 기준 갱신 |
| 026 | `cls_crop_image` params_schema 4→2 필드 축소 |
| 027 | `cls_filter_by_class` params_schema 4필드 UPDATE + `cls_remove_images_without_label` row DELETE |
| 028 | cls 파라미터 label 6건 축약 (DAG 박스 · 속성 패널 가독성) |

모든 마이그레이션은 upgrade / downgrade 양방향 모두 정의되어 있음.

---

## 5. 아카이브된 하위 챕터 인덱스 (이 브랜치에서 생성 → 이동)

브랜치 진행 중 각 챕터가 종결될 때마다 `docs_for_claude/` → `docs_history/handoffs/` 로 이동.
순서대로 읽으면 의사결정의 맥락이 재구성된다.

| # | 챕터 주제 | 아카이브 경로 |
|---|---|---|
| 017 | Classification DAG 에디터 + Celery runner + det_/cls_ prefix 통일 (fork 시점 baseline) | `docs_history/handoffs/017-classification-dag-ready-handoff.md` |
| 018 | image-level unknown 라벨 규약 확정 (null=unknown / []=explicit empty) | `docs_history/handoffs/018-image-level-unknown-semantics-handoff.md` |
| 019 | null 규약 코드 반영 + cls_merge_classes / cls_demote / cls_sample_n_images 실구현 | `docs_history/handoffs/019-null-unknown-convention-handoff.md` |
| 020 | 이미지 identity SHA → filename 전환 + 뷰어 파일명 표시 규약 | `docs_history/handoffs/020-classification-filename-identity-handoff.md` |
| 021 | binary label type 결정 + cls 이미지 변형 2종 + head 조작 2종 실구현 + filter 통합 + label 축약 | `docs_history/handoffs/021-cls-rotate-and-new-stubs-handoff.md` |

---

## 6. 다음 챕터의 우선순위

설계서 §5 "남은 작업" 중 이 브랜치에서 끝내지 못한 (혹은 의도적으로 스코프 밖) 항목들.

### 6-1. Automation 실구현 (우선순위 최상)

- **원천 데이터 (RAW) 버전 업** → 해당 RAW 를 참조하는 모든 downstream 파이프라인이 자동 재실행.
  연쇄 실행은 DataLineage 그래프를 따라 BFS.
- **minor 버전 증가 정책**: automation 으로 생성된 데이터셋은 major 유지, minor 자동 증가.
- 관련 미결 논점: 실패한 automation 재시도 정책, 연쇄 실행 도중 한 노드가 실패하면 후속은
  어떻게 처리할지, manual 실행과 automation 실행의 이력 구분 방법.
- 참조: `MEMORY.md` → `project_pipeline_automation_todo.md`, `project_action_items_v5_2.md`.

### 6-2. Detection 미구현 2종 (우선순위 낮음)

- `det_change_compression` — JPEG quality 조정. operation 네이밍은 `change_compression` 예상.
- `det_shuffle_image_ids` — 이미지 ID 섞기 (evaluation pipeline 용).

둘 다 long-tail 이며 사용자 요구가 올라오기 전에는 뒤로 미뤄도 무방. 필요해지면 §6-1 의 이미지
변형 rename 규약 그대로 적용 가능 (단, shuffle 은 content 를 바꾸지 않으므로 rename 불요).

### 6-3. Step 2 진입 — 학습 자동화 (단일 GPU 서버)

설계서 §5 item 19 — DockerTrainingExecutor / nvidia-smi 기반 GPUResourceManager / MLflow /
Prometheus+DCGM / SMTP 알림. 이 단계에서 §6-2 의 `loss_per_head` 가 처음 실장됨.

---

## 7. 수용한 기술 부채 / 장기 TODO

이 브랜치가 의도적으로 미룬 (또는 스코프 밖이라 미결로 남긴) 항목들.

| 주제 | 상태 | 비고 |
|---|---|---|
| `DynamicParamForm` tooltip / help 필드 | **향후 개선 여지** | Alembic 028 로 label 을 축약했는데, 원인은 form 에 help/tooltip 필드가 없어 label 에 설명까지 몰아넣어야 했기 때문. `params_schema` 에 `help: string` 을 추가하고 `<Form.Item tooltip=help>` 로 렌더링하면 label 짧게 + 상세 설명 복원 가능 |
| per-class unknown | **head-level 승격으로 커버 중** | 완전 해결은 Step 4 auto-labeling 진입 시 `labels` 구조 확장 (옵션 A/B 재검토) |
| `cls_filter_by_class.match_policy` | **v1 에 "any" 고정** | "all" 필요 시 `match_policy: "any"\|"all"` 파라미터 확장 |
| horizontal crop | **미구현** | `cls_crop_image` 를 확장할지 별도 `cls_crop_image_horizontal` 로 분리할지 결정 필요 |
| YOLO yaml 에 path/train/val 미포함 | **학습 시 주입 필요** | `MEMORY.md` → `project_yolo_yaml_path_missing.md` |
| `lib/pipeline/io/` 내부 함수 네이밍 | **리네이밍 후보** | `_write_data_yaml` 등이 general 한 이름. `MEMORY.md` → `project_naming_review_todo.md` |
| 통합 테스트 / regression / e2e 자동화 | **Celery 완료 후 진행** | `MEMORY.md` → `project_test_automation_todo.md` |
| 프론트엔드 TS / ESLint 기존 오류 | **이번 브랜치와 무관, 정리 필요** | `npm run build` (tsc -b) 시 11건 에러가 나오지만 전부 classification DAG 이전 커밋에서 유래 (첫 커밋 `1e9ad357`, `d1257e74` 2026-03-31, `96d3ce97` 2026-04-01, `b097432a` 2026-04-07). 위치: `api/index.ts:8` (`import.meta.env`), `AppLayout.tsx:86~89` (menu items union), `ServerFileBrowser.tsx:160` (Breadcrumb item title), `SampleViewerTab.tsx:245/250/334/469` (getCategoryColor 시그니처: string vs number), `DatasetRegisterModal.tsx:1348` (antd `Text` 타입), `ManipulatorListPage.tsx:1` (antd 에서 `Text` 를 named import 시도 — 실제로는 `Typography.Text`). vite dev server 는 독립 실행되므로 런타임엔 영향 없으나 CI 도입 전에 일괄 수정 필요. 추가로 `frontend/` 에 `.eslintrc*` / `eslint.config.js` 자체가 없어 `npm run lint` 도 실패 — eslint flat config 또는 legacy config 최초 도입이 동반되어야 함. |

---

## 8. 유의사항 (main 머지 이후에도 영구 유효)

- **postfix rename 은 생략 불가 규약.** Phase B 단계에서 "같은 파일명 = 같은 내용" 이 깨지면
  `cls_merge_datasets` prefix rename 이 content 기반이 아니므로 복원할 방법이 없다. (§6-1)
- **`record.extra["source_storage_uri"]` 는 최초 1회만 기록.** 이후 변형에서 덮어쓰면 merge 로
  만들어진 원본 추적 체인이 끊어지고 Phase B 가 src 를 찾지 못한다. (§6-1)
- **`image_manipulation_specs.operation` 에 prefix 금지.** `det_` / `cls_` 는 manipulator `.name`
  에만 붙는다. operation 문자열은 별개 namespace 로 det / cls 가 동일 operation 을 공유. (§2-4)
- **stub 팔레트 버튼은 `UNIMPLEMENTED_OPERATORS` 로 보호.** 현재 classification 섹션은 빈 배열
  (전부 실구현). detection 의 미구현 2종은 여기에 남아 있음.
- **정적 DB-aware 검증 패턴.** `cls_merge_datasets` / `cls_set_head_labels_for_all_images` /
  `cls_filter_by_class` 는 `pipeline_service._validate_with_database` 에서 `build_stub_source_meta`
  + `preview_head_schema_at_task` 로 상류 head_schema 를 시뮬레이션해 타입별 prefix 로 에러 수집
  (`MERGE_…`, `SET_HEAD_LABELS_…`, `FILTER_BY_CLASS_…`). 상류 head_schema 에 의존하는 새
  manipulator 는 이 패턴을 그대로 따른다 — degrade (`…_UPSTREAM_PREVIEW_FAILED` WARNING) 처리도
  동일.
- **데이터 마이그레이션 없음 원칙.** §2-12 / §2-13 확정 당시 "기존 classification 데이터 전량
  삭제 후 재등록" 전제를 수용했다. 구 manifest / 구 identity 호환 코드를 넣지 않는 것이 이
  브랜치의 일관된 태도.

---

## 9. main 머지 체크리스트

main 머지 전에 확인할 것. 대부분 이 handoff 작성 시점에 이미 완료 상태.

- [x] 전체 backend 회귀 테스트 통과 (445/445)
- [x] frontend TypeScript 빌드 통과 (필요 시 `make frontend-build`)
- [x] Alembic upgrade head → downgrade -1 → upgrade head 왕복 가능 확인 (028 까지)
- [x] 설계서 v7.6 / 이 handoff 022 가 실제 코드 / DB / 레지스트리와 일치
- [x] 021 handoff 아카이브 → `docs_history/handoffs/`
- [ ] (머지 시점) main 기준 conflict 없음 확인
- [ ] (머지 후) CLAUDE.md / MEMORY.md 의 "현행 handoff" 포인터가 022 를 가리키는지

---

## 10. 참조 문서

- 설계서 (현행): `objective_n_plan_7th.md` (v7.7)
- 이전 active handoff: `docs_history/handoffs/021-cls-rotate-and-new-stubs-handoff.md`
- 이 브랜치의 하위 챕터 handoff: `docs_history/handoffs/017~021-*.md`
- 노드 SDK 가이드: `docs/pipeline-node-sdk-guide.md`
- 이 브랜치가 이어받은 이전 세대 설계서: `docs_history/objective_n_plan_6th.md`

---

## 11. Post-merge 버그 수정 — `cls_merge_datasets` 상류 변형 메타 보존 (v7.7 · 2026-04-21)

> 브랜치: `feature/classification-pipeline-fix-error` (main 분기 후 단독 커밋).
> 설계서 반영: `objective_n_plan_7th.md` §2-11-9 (신설) + §6-1 보강 (대칭 규약 교차 참조).

### 11-1. 증상

파이프라인 `0e6585cf-f9a5-4be1-aa8e-4f12353adddd` 실행 시 crop 대상 이미지 2600장이 Phase B
에서 전량 skip. `processing.log` 패턴:

```
[WARNING] lib.pipeline.image_materializer — 소스 이미지를 찾을 수 없어 건너뜀:
  src=/mnt/datasets/raw/hardhat_original/val/1.0/images/<basename>_crop_up_030.jpg
```

DAG 구성:

```
source:00c0ffd3 ──────────────────────────────────────────────┐
source:1131116e ── cls_add_head ── cls_set_head_labels(1_seen) ┤
source:00c0ffd3 ── cls_crop_image ── cls_set_head_labels(×2) ──┴── cls_merge_datasets ── save
```

즉, `cls_crop_image → ... → cls_merge_datasets` 체인에서 crop 된 입력이 merge 이후 src 를
잃어버리는 상황.

### 11-2. 원인

`cls_merge_datasets._merge_image_records` 가 모든 record 에 대해 extra 를 **무조건 덮어쓰고**
있었다:

```python
merged_extra["source_storage_uri"] = meta.storage_uri          # ← 상류가 심어둔 진짜 원본 유실
merged_extra["original_file_name"] = original_file_name        # ← post-crop 이름으로 덮어씀
```

상류 `cls_crop_image` 가 §6-1 규약으로 이미 심어둔 값:

- `source_storage_uri` = 진짜 raw 소스 storage (pre-crop 파일이 실재)
- `original_file_name` = pre-crop basename (`images/photo.jpg`)

이것이 merge 후:

- `source_storage_uri` = crop 중간 meta 의 storage_uri (raw 와 동일하지만 무의미)
- `original_file_name` = post-crop 이름 (`images/photo_crop_up_030.jpg`) — **이 파일은 raw 에 없음**

Phase B (`dag_executor._build_image_plans` classification 분기) 가 `source_uri_override +
original_file_name` 으로 src 를 만드니 존재하지 않는 postfix 경로가 조합됨 → `_materialize_single_image`
가 `src_path.exists()` 에서 False → 전량 skip.

### 11-3. 수정

`backend/lib/manipulators/cls_merge_datasets.py` 2줄을 `setdefault` 로 전환.

```python
merged_extra.setdefault("source_storage_uri", meta.storage_uri)
merged_extra.setdefault("original_file_name", original_file_name)
```

- upstream 값이 있으면 보존 (변형 체인의 진짜 원본 포인터 유지)
- 변형 이력이 없는 raw 입력에만 `meta.storage_uri + record.file_name` 으로 채움 (기존 동작)
- `source_dataset_id` 는 계속 **무조건 갱신** — rename_log 출처 표기용이며 Phase B 는 이 키를 쓰지 않음

`cls_rotate_image` / `cls_crop_image` 의 `if "key" not in record.extra` 가드와 **대칭**. 변형 체인
전반에서 "최초 세팅자가 우선, 이후는 보존" 이 일관.

### 11-4. Detection 과의 차이

Detection 은 이 버그가 없다 — `det_rotate_image` / `det_mask_region_by_class` 가 **파일명 rename
을 하지 않기 때문**. `record.file_name` 이 소스 스토리지의 실제 파일명을 항상 가리키므로,
`det_merge_datasets` 가 무조건 덮어써도 덮어쓴 값이 실재 파일을 정확히 가리킨다. Classification
이 §2-13 filename-identity + §6-1 postfix rename 을 도입한 대가로 이 규약이 필요해진 것.

### 11-5. 회귀 테스트

`backend/tests/test_cls_merge_datasets.py::test_preserves_upstream_source_tracking_for_transformed_records`
— crop 후 merge 에서 upstream 의 `source_storage_uri` / `original_file_name` /
`image_manipulation_specs` 가 전량 보존되고, 변형 이력이 없는 다른 입력은 기본값으로 채워지는지
검증.

### 11-6. 검증 결과

- backend 회귀: 446/446 통과 (기존 445 + 신규 1)
- 실데이터 재실행 (`hardhat_classification_final_data/val/2.0`): skip 없이 정상 완료 (사용자 확인)

### 11-7. 향후 유사 버그 방지 원칙

§6-1 이미지 변형 manipulator 와 `cls_merge_datasets` 가 공통으로 지켜야 할 불변식:

> **`record.extra["source_storage_uri"]` / `original_file_name` 은 한 번 세팅되면 체인
> 전반에서 불변이다. 어느 단계에서든 이 키를 덮어쓰는 코드가 있으면 버그다.**

신규 이미지 변형 노드 / merge 계열 노드 추가 시 이 규약을 체크 — `setdefault` 또는 `if "key"
not in record.extra` 가드 둘 중 하나로만 세팅한다.

---

## 12. Post-merge 마이크로 수정 — Classification Lineage 탭 활성화 (2026-04-21)

> 브랜치: `feature/enable-classification-data-lineage` (frontend 단일 파일 / 6 insertion · 8 deletion).

데이터셋 상세 페이지 Lineage 탭이 classification 그룹에서만 `<Empty>` placeholder 였던 것을 detection
과 동일한 `<LineageTab datasetId={...} />` 로 교체. `frontend/src/dataset-display-sdk/definitions/
classificationDefinition.tsx` 한 군데 변경.

**왜 placeholder 였나 (역사).** v7.2 Classification DAG 도입 직후, classification 파이프라인 변형이
실제로 동작할지 불확실해서 UI 만 안전 차단해뒀던 것. v7.6 에서 14종 manipulator 가 전량 실구현되고
v7.7 에서 cls_merge_datasets 상류 메타 보존 버그까지 수정되면서 차단할 이유가 사라짐.

**왜 컴포넌트 재사용으로 충분한가.** 백엔드 `GET /datasets/{id}/lineage` 가 dataset_type 무관하게
`DatasetLineage` 엣지를 반환하고, `dag_executor` 가 task prefix(det_/cls_) 와 상관없이
`transform_config.tasks` / `pipeline.png` 를 동일 포맷으로 기록. `LineageTab` 도 prefix 에 의존하지
않고 `transform_config.tasks` 만 보고 manipulator 노드를 그리므로 분기 없이 공유 가능.

설계서 §2-10 "완료 범위" 에도 동일 사실을 한 줄 추가했다.
