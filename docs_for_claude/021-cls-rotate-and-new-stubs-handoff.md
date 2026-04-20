# 통합 핸드오프 021 — cls_rotate_image 실구현 + 신규 Classification 노드 4종 stub 추가 + Binary label type 결정

> 최종 갱신: 2026-04-20
> 이전 핸드오프: `docs_history/handoffs/020-classification-filename-identity-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.5, §2-4 / §5 / §6-1 / §6-2 갱신)
> 이번 세션 브랜치: `feature/classification-dag-implementation-01`
> 주요 커밋:
> - `c43a0b3` docs: binary label type 미결내용 결정 및 문서 반영
> - `55a68a2` feat(manipulator): classification 이미지 변형 2종 + head 조작 2종 seed + 팔레트 노출 (stub)
> - (미커밋) feat(manipulator): cls_rotate_image 실구현 + postfix rename 규약 확립 + 25건 테스트

020 의 filename-identity 전환(§2-13)이 끝난 상태에서, 고정 rename 규약 덕분에 이미지 변형 manipulator 도
detection 과 동일한 "변형 시 파일명에 postfix 를 붙여 새 이미지로 만든다" 규약으로 구현할 수 있게 됐다.
이번 세션은 (1) 미결이던 binary label type 방법론을 (c)주+(b)보조 로 확정하고, (2) 이미지 변형 2종 + head
조작 2종 팔레트 버튼을 seed + stub 까지 노출하고, (3) `cls_rotate_image` 를 제일 먼저 실구현한다.

---

## 1. 이번 세션에서 확정한 변경

### 1-1. Binary label type 결정 (§6-2, 커밋 `c43a0b3`)

v7.4~v7.5 까지 "`single-label + len(classes)==2` head 를 softmax 로 학습할지 BCE 로 학습할지 schema
만으로는 구분할 수 없다" 는 미결 논점이 남아 있었다.

- **결정: (c) 주 + (b) 보조.** 데이터 schema 는 현 `HeadSchema.multi_label: bool` 그대로 유지하고,
  loss 선택은 **학습 config 의 head 별 `loss_per_head` 필드**로 분리한다. (a) schema 에 `label_type`
  필드를 추가해 등록 시점부터 binary 를 강제하는 안은 폴더 규약(§2-8) 파급과 "같은 데이터로 softmax / BCE
  양쪽 실험" 요구를 충족하지 못해 기각.
- **주 (c) — 학습 config `loss_per_head: dict[str, Literal["softmax", "bce", "bce_ovr"]]`.**
  Step 2 `TrainingExecutor` 진입 시점에 실장. Phase 2 / 3 에서는 코드 변경 없음.
- **보조 (b) — UI auto-suggest + 사용자 검토 강제.** `multi_label=True → bce`,
  `multi_label=False & len==2 → softmax/bce 둘 다 후보 (명시 선택 필수)`,
  `multi_label=False & len>2 → softmax 기본, bce_ovr 선택 가능`. 묵시 기본값으로 학습이 제출되지
  않도록 "검토 완료" 체크를 강제.
- **정책.** `len(classes) != 2` 인 single-label head 에 `bce` 지정 시 명시 에러. OvR BCE 는
  값 이름 `bce_ovr` 로 분리해서 의도를 기호로 강제한다.

### 1-2. 신규 Classification 노드 4종 stub + seed + 팔레트 노출 (커밋 `55a68a2`)

설계서 §5 의 "이미지 변형 2종", "Head 추가 노드", "Annotation 일괄 변경 노드" 에 해당하는 노드들을
**Python 구현체는 stub, DB seed + 팔레트 버튼은 정식 노출** 로 먼저 들여놓았다. 노드 네이밍은 사용자가
일부 수정한 뒤 확정.

| manipulator name | 카테고리 | 역할 | 비고 |
|---|---|---|---|
| `cls_crop_image` | AUGMENT | 이미지 상하좌우 Crop 비율 지정 | 네이밍 확정 — 상하/좌우 crop 은 한 노드 안의 옵션으로 제공 (분리하지 않음) |
| `cls_rotate_image` | AUGMENT | 90°/180°/270° 고정 회전 | det_rotate_image 참조. 이번 세션 `1-3` 에서 실구현 |
| `cls_add_head` | CLS_HEAD_CTRL | 신규 head 추가 (기존 이미지 labels = `null`) | §2-12 `null`=unknown 규약 승계 |
| `cls_set_head_labels_for_all_images` | CLS_HEAD_CTRL | 특정 head 의 labels 일괄 덮어쓰기 (set_null / set_classes) | 원안 `cls_annotate_head_all_images` 에서 리네이밍 — "set_head_labels" 가 동작을 더 정확히 기술 |

**반영된 파일.**
- `backend/lib/manipulators/cls_{crop_image,rotate_image,add_head,set_head_labels_for_all_images}.py` — stub. `NotImplementedError` + params_schema 주석만 기술
- `backend/migrations/versions/023_seed_cls_image_and_head_ops.py` — 4건 seed. `scope=[PER_SOURCE, POST_MERGE]`, `compatible_task_types=[CLASSIFICATION]`, `compatible_annotation_fmts=[CLS_MANIFEST]`, `output_annotation_fmt=CLS_MANIFEST`
- `frontend/src/pipeline-sdk/styles.ts`:
  - `CATEGORY_ITEM_ORDER.CLS_HEAD_CTRL` 에 `cls_add_head` (최상단), `cls_set_head_labels_for_all_images` (최하단) 추가
  - `CATEGORY_ITEM_ORDER.AUGMENT = ['cls_crop_image', 'cls_rotate_image']` 신설
  - `MANIPULATOR_EMOJI` 에 `cls_crop_image=✂️ / cls_rotate_image=↩️ / cls_add_head=➕ / cls_set_head_labels_for_all_images=📝` 추가
- `frontend/src/pipeline-sdk/definitions/operatorDefinition.tsx`
  - `UNIMPLEMENTED_OPERATORS` 에 4건 전부 추가 (팔레트에서는 클릭 가능하지만 파이프라인 실행 시 NotImplementedError 로 차단)

팔레트 등장 위치는 `CATEGORY_STYLE` key order (`CLS_HEAD_CTRL` → … → `AUGMENT` → `MERGE`) + 각 카테고리 내부의 `CATEGORY_ITEM_ORDER` 로 제어된다. 이번 변경으로 순서:
- `CLS_HEAD_CTRL`: `cls_add_head` → `cls_select_heads` → `cls_rename_head` → `cls_reorder_heads` → `cls_demote_head_to_single_label` → `cls_set_head_labels_for_all_images`
- `AUGMENT`: `cls_crop_image` → `cls_rotate_image` (det 용은 아직 없음)

### 1-3. `cls_rotate_image` 실구현 — postfix rename 규약 확립

stub 4종 중 가장 단순한 `cls_rotate_image` 를 먼저 실구현해서, 앞으로 `cls_crop_image` 등
**이미지 바이너리를 변형하는 모든 manipulator 가 따를 공통 규약** 을 확립했다.

#### 1-3-1. 동작 요약

- **params.** `degrees: int ∈ {90, 180, 270}`. 기본값 180. 그 외 값은 `ValueError`.
- **Phase A (`transform_annotation`).**
  1. 90°/270° 회전 시 `record.width ↔ record.height` 교환 (180° 는 불변).
  2. `record.file_name` 에 `_rotated_{degrees}` postfix 를 확장자 앞에 삽입.
     예: `images/truck_001.jpg` → `images/truck_001_rotated_180.jpg`.
     이는 v7.5 filename-identity (§2-13) 의 **"같은 파일명 = 같은 내용" 불변식**을 지키기 위한 핵심.
     이미지 내용이 변하면 반드시 새 파일명을 부여해야 검색/캐시/merge 경로가 깨지지 않는다.
  3. **src 복원용 메타데이터를 최초 변형 시에만 `record.extra` 에 기록**:
     - `record.extra["source_storage_uri"] = rotated_meta.storage_uri` (입력 dataset 의 storage_uri)
     - `record.extra["original_file_name"] = record.file_name` (rename 이전 이름)
     - 이미 키가 있으면 덮어쓰지 않는다 — `cls_merge_datasets` 가 먼저 채워 둔 원본 추적 체인을
       유지하기 위함.
  4. `record.extra["image_manipulation_specs"]` 배열에 `{operation: "rotate_image", params: {degrees}}` append (기존 spec 이 있으면 그 뒤로 쌓임).
  5. head_schema / labels 는 건드리지 않는다 (회전은 class label 과 무관).
- **Phase B (`build_image_manipulation`).**
  - `ImageManipulationSpec(operation="rotate_image", params={"degrees": N})` 반환.
  - 실제 픽셀 회전은 `lib/pipeline/image_materializer.py._apply_rotate` 가 PIL transpose 로 수행 — 기존 detection 경로에서 이미 쓰던 구현이라 추가 작업 없음.
- **입력 타입.** `cls_rotate_image` 는 단건 `DatasetMeta` 만 받는다. list 입력은 `TypeError` (merge 가 아니므로).

#### 1-3-2. 불변식 — 이미지 변형 manipulator 공통 규약 (새 노드도 이 규약을 따라야 함)

앞으로 `cls_crop_image`, `cls_change_compression` 등 이미지 변형 manipulator 를 추가할 때
반드시 지켜야 할 패턴. 이번 `cls_rotate_image` 로 확정됐다.

1. **파일명 postfix rename 필수.** 변형 종류별로 고정 prefix/postfix 문자열을 확장자 앞에 삽입.
   `_rotated_{degrees}`, `_cropped_{t}_{b}_{l}_{r}` 형태. 경로 prefix (`images/deep/nested/`) 는
   유지 — `os.path.splitext` 한 번으로 처리.
2. **src 복원 메타데이터는 `record.extra` 에 기록하고 최초 1회만.** Phase B 가 원본 src 를 찾기
   위한 유일한 단서. merge 가 먼저 채워뒀다면 그대로 보존 (체인을 끊지 않는다).
3. **`record.extra["image_manipulation_specs"]` 에 append.** 기존 spec 이 없으면 빈 배열에서
   시작, 있으면 순서대로 쌓임. Phase B `ImageMaterializer` 가 이 순서대로 변환을 적용.
4. **head_schema / labels 는 건드리지 않는다** (classification 이미지 변형은 annotation 과 독립).
5. **deep copy 로 입력 격리.** `copy.deepcopy(input_meta)` 로 시작. 호출자가 원본을 다시 쓸 수
   있게 한다.
6. **list 입력 거부.** 이미지 변형은 단건 transform. merge 와 의도를 혼동하지 않도록
   `isinstance(input_meta, list)` 일 때 TypeError.

#### 1-3-3. 테스트 (`backend/tests/test_cls_rotate_image.py`, 25 케이스)

- 각도별 동작: 180° dim 유지, 90°/270° dim swap, dim 이 None 이면 swap skip
- head_schema / labels 보존 (null 포함)
- `image_manipulation_specs` 최초 push + 기존에 있으면 append
- `extra.source_storage_uri / original_file_name` 최초 기록 + merge 가 채워둔 경우 덮어쓰지 않음
- deep copy 격리 (결과 수정이 원본 meta 에 전파되지 않음)
- 기본값 (degrees 누락 시 180)
- list 입력 TypeError, `{0, 45, 360, -90, 181}` 각각 ValueError
- `build_image_manipulation` 반환 스펙 (degrees 기본값 / 명시값)
- `_append_postfix_to_filename` 헬퍼 단위 (경로 prefix 유지, 확장자 없음 케이스)

`uv run pytest backend/tests/test_cls_rotate_image.py -q` → 25 / 25.
전체 `uv run pytest backend/tests -q` → 267 / 267 (기존 242 + 이번 25).

#### 1-3-4. UNIMPLEMENTED_OPERATORS 해제

`frontend/src/pipeline-sdk/definitions/operatorDefinition.tsx` 의 `UNIMPLEMENTED_OPERATORS` 배열에서
`cls_rotate_image` 를 제거. 나머지 3종 (`cls_crop_image`, `cls_add_head`,
`cls_set_head_labels_for_all_images`) 은 stub 유지.

---

## 2. Registry 상태 (27종)

- Detection: **12 실구현**
- Classification: **10 실구현 + 5 stub**
  - 실구현 (10): `cls_rename_head`, `cls_rename_class`, `cls_reorder_heads`, `cls_reorder_classes`, `cls_select_heads`, `cls_merge_datasets`, `cls_merge_classes`, `cls_demote_head_to_single_label`, `cls_sample_n_images`, **`cls_rotate_image` (신규)**
  - stub (5): `cls_filter_by_class`, `cls_remove_images_without_label`, `cls_crop_image`, `cls_add_head`, `cls_set_head_labels_for_all_images`

---

## 3. 다음 작업 체크리스트 (우선순위)

1. **`cls_add_head` 실구현** — 신규 head 를 head_schema 말단에 append, 모든 기존 이미지의 해당 head
   labels 는 `null` (unknown, §2-12). params 는 head 이름 + class candidate 목록. 023 seed 의
   params_schema 가 이미 들어가 있으므로 Python 구현만 채우면 된다.
2. **`cls_crop_image` 실구현** — 규약 1-3-2 를 그대로 따른다. postfix 는 `_cropped_{t}_{b}_{l}_{r}`,
   90°/270° 의 dim swap 대신 `width *= (1 - (left+right)/100)`, `height *= (1 - (top+bottom)/100)` 의
   정수 반올림. Phase B 쪽 `_apply_crop` 이 이미 있는지 먼저 확인 필요 (없으면 추가).
3. **`cls_set_head_labels_for_all_images` 실구현** — `action ∈ {set_null, set_classes}`.
   `set_classes` + multi_label=False + len(classes) > 1 이면 single-label assert 로 ValueError.
4. **`cls_filter_by_class` / `cls_remove_images_without_label`** — annotation 기반 필터 2종.
   이미지 변형과 달리 Phase B 는 건드리지 않는다 (record 제거만).
5. **Automation 실구현** (lineage + minor 버전 증가 규약)
6. **Detection 미구현 2종** — `det_change_compression`, `det_shuffle_image_ids` (long-tail).
7. **Step 2 진입 시 `loss_per_head` 스키마 실장** — §6-2 결정 반영.

---

## 4. 유의사항

- **postfix rename 은 생략 불가 규약.** Phase B 단계에서 "같은 파일명 = 같은 내용" 이 깨지면
  `cls_merge_datasets` prefix rename 도 content 기반이 아니므로 복원할 방법이 없다.
- **`record.extra["source_storage_uri"]` 는 최초 1회만 기록.** 이후 변형에서 덮어쓰면 merge 로
  만들어진 원본 추적 체인이 끊어지고 Phase B 가 src 를 찾지 못한다. 새 이미지 변형 노드를 추가할
  때도 이 순서를 반드시 준수.
- **`image_manipulation_specs.operation` 에 prefix 금지.** `det_`/`cls_` prefix 는 manipulator
  `.name` 에만 붙는다. `operation` 문자열은 (`rotate_image`, `crop_image`, ...) 별개 namespace
  로, detection 과 classification 이 동일 operation 을 공유할 수 있다 (§2-4).
- **stub 팔레트 버튼은 `UNIMPLEMENTED_OPERATORS` 로 보호.** 실구현 완료 시 해당 배열에서 해당
  이름을 제거. 빼먹으면 실행 시 NotImplementedError 가 프론트까지 노출되는 것처럼 보이지 않아
  디버깅이 어려워진다.

---

## 5. 참조 문서

- 설계서: `objective_n_plan_7th.md` §2-4 (registry 27종), §2-13 (filename-identity), §5 (남은 작업), §6-1 (이미지 변형 rename 규약 신설), §6-2 (binary label type 결정)
- 이전 핸드오프: `docs_history/handoffs/020-classification-filename-identity-handoff.md`
- 노드 SDK 가이드: `docs/pipeline-node-sdk-guide.md`
