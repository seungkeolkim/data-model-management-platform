# 통합 핸드오프 021 — cls_rotate_image 실구현 + 신규 Classification 노드 4종 stub 추가 + Binary label type 결정

> 최종 갱신: 2026-04-20
> 이전 핸드오프: `docs_history/handoffs/020-classification-filename-identity-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.5, §2-4 / §5 / §6-1 / §6-2 갱신)
> 이번 세션 브랜치: `feature/classification-dag-implementation-01`
> 주요 커밋:
> - `c43a0b3` docs: binary label type 미결내용 결정 및 문서 반영
> - `55a68a2` feat(manipulator): classification 이미지 변형 2종 + head 조작 2종 seed + 팔레트 노출 (stub)
> - `84e6b40` feat(manipulator): cls_rotate_image 실구현 + postfix rename 규약 확립 + 25건 테스트
> - `916964f` feat(manipulator): cls_add_head 실구현 + DynamicParamForm checkbox/text 타입 추가 + Alembic 024 + 29건 테스트
> - `56f784c` fix(pipeline-validator): cls_add_head head_name 체인 내 중복 검출 + 4건 테스트
> - `54fb15c` feat(manipulator): cls_set_head_labels_for_all_images 실구현 + Alembic 025 + 33건 테스트
> - `56bcd5a` fix(pipeline-service): cls_set_head_labels_for_all_images 정적 DB-aware 검증 + 12건 테스트 (pipeline id `a6e6b2a2-d0cd-4cf9-8ce9-b0f6b263829c` 재현 버그)
> - `9e33476` feat(manipulator): cls_crop_image 실구현 — direction(상단/하단) + crop_pct(1~99) 2-필드 UX, postfix `_crop_up/down_{pct:03d}` + Alembic 026 + 45건 테스트
> - `19118dc` feat(manipulator): cls_filter_by_class 실구현 + cls_remove_images_without_label 통합 제거 + Alembic 027 + 55건 테스트

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

### 1-4. `cls_add_head` 실구현 — DynamicParamForm checkbox 타입 신설

`cls_add_head` 는 head_schema 에 새로운 head 를 **맨 뒤**에 추가하고, 모든 기존 이미지의 신규 head
labels 를 `null` (unknown, §2-12) 로 초기화하는 단순한 annotation 변경 manipulator 다. 이미지
바이너리는 불변이므로 Phase B 는 lazy copy, postfix rename 규약(§6-1)과 무관.

#### 1-4-1. params UX 확정

세션 중 사용자가 직접 정의한 3-필드 폼:

| key | UI 타입 | 의미 | 기본값 |
|---|---|---|---|
| `head_name` | text | 신규 head 이름 (비어있지 않은 문자열, 기존 head 와 충돌 금지) | — (필수) |
| `multi_label` | **checkbox (신설)** | 체크 = multi-label head / 미체크 = single-label head | `False` |
| `class_candidates` | textarea | class 이름 목록. 줄바꿈 구분. list[str] 도 수용. trim 후 빈 줄 제외. 2개 이상, 중복 금지. 입력 순서 = 학습 output index (§2-4) | — (필수) |

023 seed 당시 params 는 `label_type: select("single"|"multi")` 였는데, 실구현 시 사용자 요구로
**`multi_label: checkbox (bool)`** 로 전환 — 더 직관적이고 true/false 의미가 선택 값 문자열에
의존하지 않는다. Alembic `024_cls_add_head_params` 마이그레이션으로 seed 갱신.

#### 1-4-2. DynamicParamForm 에 `checkbox` / `text` 타입 추가

`frontend/src/components/pipeline/DynamicParamForm.tsx` 의 `ParamFieldSchema.type` union 에
`'checkbox' | 'text'` 를 추가하고 각 렌더러 case 를 구현.

- `checkbox` → Ant Design `<Checkbox>`. `onChange(e.target.checked)` 로 `bool` 전달.
- `text` → `<Input>`. 기존에 `default` case 로 암시 처리되던 것을 명시 case 로 승격 — seed 에서
  `type: "text"` 라고 선언하는 곳이 여럿이라 (cls_merge_classes, cls_add_head 등) 정식으로 인정.

이 변경으로 앞으로 신규 manipulator 의 params 를 bool 타입으로 받을 때 별도 작업 없이 seed 에
`type: "checkbox"` 만 선언하면 된다. 기존 select-based bool 대체가 가능.

#### 1-4-3. 동작 요약

- `input_meta.head_schema` 가 `None` (detection) 이면 `ValueError`.
- `input_meta` 가 list 면 `TypeError` (단건 manipulator).
- 신규 head 이름이 기존 head 와 충돌하면 `ValueError` (메시지에 기존 head 목록 포함).
- `class_candidates` trim 후 2개 미만이면 `ValueError` ("2개 이상").
- 중복 class 이름이면 `ValueError`.
- 성공 시 head_schema 에 새 `HeadSchema` append, 모든 `image_records[*].labels[new_head_name] = None`.
  `file_name / width / height / extra` 는 그대로 복제.

#### 1-4-4. 테스트 (`backend/tests/test_cls_add_head.py`, 29 케이스)

- head_schema 말단 append + 기존 head multi_label/classes 보존
- 기존 이미지의 신규 head = null (기존 labels 가 `null`/`[]`/`[...]` 어떤 형태든 보존)
- `multi_label` 기본 False / True 명시 / 문자열 "true|True|1|yes|on" truthy / "false|False|0|no|off|''" falsy
- class_candidates textarea (공백 줄 제외) + list 입력
- 에러: head_name 누락/공백/충돌, class_candidates 누락/1개 이하/중복, list 입력, detection DatasetMeta
- deep copy 격리 (결과 조작이 원본 meta 에 전파되지 않음)
- 이미지 메타 보존 (image_id/file_name/width/height/extra)

`uv run pytest backend/tests/test_cls_add_head.py -q` → 29 / 29.
전체 `uv run pytest backend/tests -q` → **296 / 296** (이전 267 + 이번 29).

#### 1-4-5. UNIMPLEMENTED_OPERATORS 해제

`frontend/src/pipeline-sdk/definitions/operatorDefinition.tsx` 에서 `cls_add_head` 제거.
팔레트에 활성 버튼으로 노출 (CLS_HEAD_CTRL 카테고리 최상단 — `CATEGORY_ITEM_ORDER` 기준).

### 1-5. Static Pipeline Validator — `cls_add_head` 중복 head_name 검출

#### 1-5-1. 버그 재현

- Pipeline id `a30a723f-ee93-4d5d-9e42-badba0d405ac`.
- 체인 상 세 번째 `cls_add_head` 에 두 번째(첫 번째 혹은 두 번째 노드)와 같은 `head_name='is_person'`
  을 지정했는데, GUI 팔레트 편집 단계에서는 경고가 떴으나 **"검증" 버튼 (`validate_pipeline_config_static`)
  은 성공** 으로 판정, 제출까지 통과했다. 런타임은 `cls_add_head.transform_annotation` 에서
  `head_name already exists` 로 실패했지만 정적 검증에서 막지 못한 점이 회귀 위험.

#### 1-5-2. 수정 — `backend/lib/pipeline/pipeline_validator.py`

- 검증 항목 8번으로 `_validate_cls_add_head_duplicates(config, result)` 추가.
- 로직: `config.topological_order()` 로 DAG 순회 → 각 task 마다
  `TaskConfig.get_dependency_task_names()` 로 상위에서 누적된 head_name 집합을 합친 `inherited` 계산
  → 현재 task 가 `cls_add_head` 이고 `head_name` 이 `inherited` 에 이미 있으면
  `CLS_ADD_HEAD_DUPLICATE` ERROR 로 보고 → task 를 통과한 뒤 자기 head_name 도 누적에 더해 하위에
  전파.
- 한계: **source dataset 에 이미 존재하는 head_schema 와의 충돌은 정적 단계에서 잡지 않는다.**
  (source 의 head_schema 는 DB 조회가 필요 — app/ 레이어 또는 런타임 `transform_annotation` 쪽 책임.)
- 독립 브랜치(공통 upstream 없음)에서 같은 head_name 을 별도로 추가하는 경우는 허용 — 각 브랜치가
  결국 다른 출력 데이터셋이 되고, 실제 DB 충돌이 발생할 곳은 merge 시점이므로 그 쪽 검증 소관.
- 순환이면 `topological_order()` 가 ValueError → 다른 validator 가 선행 차단하므로 여기서는 조용히
  return.

#### 1-5-3. 테스트 (`backend/tests/test_pipeline_validator.py`, 4건 신규)

`TestValidateClsAddHeadDuplicates`:
1. `test_duplicate_head_name_in_chain_is_error` — 세 노드 체인에서 1 번째 / 3 번째가 동일
   `is_person` → `CLS_ADD_HEAD_DUPLICATE` 1 건 (pipeline `a30a723f-...` 재현).
2. `test_distinct_head_names_in_chain_pass` — `is_person` → `gender` 서로 다름 → 통과.
3. `test_same_head_name_on_independent_branches_pass` — 두 source 에서 각각 `is_person` 추가,
   공통 upstream 없음 → 허용.
4. `test_empty_head_name_is_not_duplicate_report` — head_name 공백은 이 validator 로 중복 판정
   안 함 (`cls_add_head.transform_annotation` 에서 ValueError 로 따로 잡힘).

`uv run pytest backend/tests -q` → **300 / 300** (이전 296 + 이번 4).

### 1-6. `cls_set_head_labels_for_all_images` 실구현 — params UX 단순화 + single-label assert 사전 차단

stub 4종 중 세 번째 실구현. 지정 head 의 labels 를 **모든 이미지에서 동일 값으로 overwrite** 하는
annotation-only manipulator (head_schema / file_name 불변 → Phase B lazy copy).

#### 1-6-1. params UX 확정 (023 seed → 025 로 swap)

세션 중 사용자가 단순화 요구: dropdown/select 대신 text + checkbox + textarea 만 쓴다.

| key | UI 타입 | 의미 | 기본값 |
|---|---|---|---|
| `head_name` | text | 대상 head 이름 (기존 head_schema 에 존재해야 함) | — (필수) |
| `set_unknown` | checkbox | 체크 = 해당 head 를 모든 이미지에서 `null` 로 초기화 (classes 무시) / 미체크 = classes 값으로 일괄 교체 | `False` |
| `classes` | textarea | set_unknown 미체크 시 사용. 줄바꿈 구분. single-label = 정확히 1개, multi-label = 0개 이상 (빈 값 = explicit empty §2-12) | — |

023 seed 당시 `action: select("set_null"|"set_classes")` 였는데 `set_unknown: checkbox (bool)` 로
전환 — 024 의 `cls_add_head` swap 과 같은 패턴. Alembic `025_cls_set_head_labels_params`.

#### 1-6-2. 동작 / 검증

- `input_meta.head_schema=None` (detection) → `ValueError`. list 입력 → `TypeError`.
- `head_name` 이 head_schema 에 없으면 `ValueError`.
- **set_unknown=True**: classes 가 함께 들어와도 무시. 모든 `image_records[*].labels[head_name] = None`.
- **set_unknown=False**: classes 파싱 후 검증
  - 중복 이름 → `ValueError`.
  - `head_schema.classes` 바깥 이름(신규 class) → `ValueError` (§2-4 SSOT — 새 class 가 필요하면 `cls_rename_class` / `cls_add_head` 를 먼저).
  - single-label head 에 0개 또는 2개 이상 → `ValueError` ("0개면 set_unknown 을 쓰라" 안내 포함).
  - multi-label head 는 0개 이상 모두 허용 (빈 리스트 = explicit empty §2-12).
- 원본 labels 에 target_head 키가 없어도(cls_add_head 직후 등) 이번 단계에서 채워진다.
- 다른 head labels 는 원형 유지. head_schema 도 변경 없이 깊은 복제.

#### 1-6-3. 테스트 (`backend/tests/test_cls_set_head_labels_for_all_images.py`, 33 케이스)

- set_unknown=True → target head 전부 null, 다른 head 보존, classes 무시
- single-label + 1 class, multi-label + 2 classes, multi-label + 0 classes(explicit empty)
- head_schema 불변, target_head 가 원본 labels 에 없을 때 새로 채움
- classes textarea trim / list 수용 / set_unknown truthy·falsy 문자열 파라미터화
- 에러: head_name 누락/공백/미존재, single-label + 0 or 2개, 바깥 class, 중복, list 입력, detection
- 원본 meta 불변, 이미지 메타(image_id/file_name/width/height/extra) 보존

`uv run pytest backend/tests -q` → **333 / 333** (이전 300 + 이번 33).

#### 1-6-4. UNIMPLEMENTED_OPERATORS 해제

`frontend/src/pipeline-sdk/definitions/operatorDefinition.tsx` 에서 `cls_set_head_labels_for_all_images` 제거. 팔레트에 활성 버튼으로 노출 (CLS_HEAD_CTRL 카테고리 최하단).

### 1-7. 정적 DB-aware 검증 확장 — cls_set_head_labels_for_all_images params × 상류 head_schema

#### 1-7-1. 버그 재현

- Pipeline id `a6e6b2a2-d0cd-4cf9-8ce9-b0f6b263829c`.
- 체인 말단에 `cls_set_head_labels_for_all_images` 가 source 의 single-label head `visibility`
  (classes=`[0_unseen, 1_seen]`) 에 대해 `set_unknown=False, classes="0_unseen\n1_seen"` 로 구성됨.
- `/pipelines/validate` 는 PASS 로 판정, `/pipelines/execute` 가 제출되어 runtime 에서만 실패
  (`SetHeadLabelsForAllImagesClassification.transform_annotation` 의 SINGLE_LABEL_ARITY 검증).

#### 1-7-2. 원인

`PipelineService._validate_with_database` 는 `cls_merge_datasets` 에 대해서만 DB 의 source
head_schema 를 `build_stub_source_meta` + `preview_head_schema_at_task` 로 시뮬레이션해 compat
체크를 수행하고 있었다. `cls_set_head_labels_for_all_images` 는 동일한 preview 가 필요했지만
미연결 — 정적 단계에서 params × head_schema 대조가 아예 빠져 있었다.

#### 1-7-3. 수정 — `lib/manipulators/cls_set_head_labels_for_all_images.py` + `app/services/pipeline_service.py`

1. **manipulator 리팩터.** `SetHeadLabelsForAllImagesClassification` 클래스 내 staticmethod
   검증을 모듈 레벨 함수 `validate_set_head_labels_params(head_schema, params) -> list[(code, message)]`
   로 추출. 반환값은 위반 목록으로, 코드 5종:
   - `HEAD_SCHEMA_MISSING` — detection 등 head_schema=None
   - `HEAD_NAME_MISSING` — 파라미터 누락/공백
   - `HEAD_NAME_NOT_FOUND` — head_schema 에 없는 head
   - `CLASSES_DUPLICATE`, `CLASSES_NOT_IN_SCHEMA`, `SINGLE_LABEL_ARITY` (set_unknown=False 일 때만)
   - `SET_UNKNOWN_INVALID` / `CLASSES_INVALID` — 파싱 실패

   `transform_annotation` 은 이 함수의 첫 원소를 ValueError 로 승격 (runtime 메시지 기존 유지).
   정적 검증은 리스트 전체를 `PipelineValidationIssue` 로 변환해 **한 번의 검증 호출로 여러
   이슈를 동시에 노출**.

2. **pipeline_service 확장.** `_validate_with_database` 에 검증 항목 5번으로
   `_validate_cls_set_head_labels_compatibility(config, result)` 추가.
   - 로직: config 내 `cls_set_head_labels_for_all_images` 태스크마다 상류 단일 입력의
     head_schema 를 계산 — `source:<id>` 면 `build_stub_source_meta`, task ref 면
     `preview_head_schema_at_task` 로 체인 시뮬레이션 → `validate_set_head_labels_params` 호출 →
     이슈마다 `SET_HEAD_LABELS_{CODE}` prefix 로 ERROR 수집.
   - preview 자체가 실패하면 (상류 operator NotImplementedError 등) WARNING 으로만 남기고 본
     검증 스킵 — 동일 원인의 이중 에러 방지. 패턴은 기존 `MERGE_UPSTREAM_PREVIEW_FAILED` 와 동일.
   - 소스 데이터셋 존재성(1~3번) 이 먼저 통과한 경우에만 실행 (same as cls_merge compat).

3. **runtime 동작은 그대로.** `transform_annotation` 의 ValueError 메시지/타입 변경 없음 —
   기존 manipulator 테스트 33/33 통과. 정적 검증은 추가되는 레이어이며 runtime 을 대체하지 않는다
   (API 우회 방어).

#### 1-7-4. 테스트 (`backend/tests/test_cls_set_head_labels_for_all_images.py`, 12건 신규)

기존 파일 말단에 §7 / §8 섹션 추가:
- **§7** `validate_set_head_labels_params` 순수 함수 — OK 케이스 3종, 5종 에러 코드별 1건씩,
  multi-issue 축적 1건.
- **§8** `test_validate_after_preview_catches_a6e6b2a2_scenario` — 실제 버그 파이프라인의 핵심
  조건(single-label head + 2 classes + set_unknown=False) 을 순수 함수에 주어 `SINGLE_LABEL_ARITY`
  가 수집되고 메시지에 `set_unknown` 유도 안내가 포함되는지 확인.

`uv run pytest backend/tests -q` → **345 / 345** (이전 333 + 이번 12).

### 1-8. `cls_crop_image` 실구현 — 수직축(상단/하단) 단일 crop + postfix 규약

**목표.** 최초 `023` seed 는 상하좌우 4방향 각각의 비율을 받는 4-필드 구조였으나, 실제 사용 흐름은
"한 번에 위/아래 중 한 영역만 잘라내기" 로 확인됨. UI/UX 단순화를 위해 2-필드 구조로 재정의:

- `direction`: select("상단" | "하단"), default "상단".
- `crop_pct`:  number(1~99, step=1), default 30. Ant Design `InputNumber` 의 ▲▼ 버튼으로 조정.

**파일명 postfix.** `_crop_{direction_code}_{crop_pct:03d}` — direction 은 내부적으로 Korean → English
(`상단→up`, `하단→down`) 로 정규화해 ASCII 만 사용. `crop_pct` 는 항상 3자리 zero-pad:

```
images/truck_001.jpg → images/truck_001_crop_up_030.jpg   (상단 30%)
images/truck_001.jpg → images/truck_001_crop_down_099.jpg (하단 99%)
```

**데이터 흐름.**
- `transform_annotation` — `record.height *= (100 - crop_pct) / 100` (정수 내림, 최소 1), `width` 유지.
- `source_storage_uri` / `original_file_name` 을 최초 1회만 기록 (rotate 와 동일 규약).
- `extra.image_manipulation_specs` 에 `{"operation": "crop_image_vertical", "params": {"direction":
  "up"|"down", "crop_pct": N}}` 누적.
- Phase B `ImageMaterializer._apply_crop_vertical` — `img.crop((0, cut_rows, w, h))` 또는
  `(0, 0, w, h - cut_rows)`. `cut_rows = int(h * crop_pct / 100)`, 최소 1 픽셀 보장.

**검증 규칙 (ValueError 차단).**
- `direction` 은 `"상단" | "하단" | "up" | "down"` 중 하나 (공백 trim 허용, 그 외 전부 차단).
- `crop_pct` 는 int-like 이며 [1, 99] 범위. 소수(`30.5`), bool, 범위 밖 정수 전부 차단.

**반영된 파일.**
- `backend/lib/manipulators/cls_crop_image.py` — stub → 전체 구현. `_parse_direction` / `_parse_crop_pct`
  / `_append_postfix_to_filename` 모듈 레벨 helper.
- `backend/lib/pipeline/image_materializer.py` — `_apply_image_operation` 분기에 `crop_image_vertical`
  추가 + `_apply_crop_vertical` 신설.
- `backend/migrations/versions/026_cls_crop_image_params.py` — params_schema 4→2 필드, description 갱신.
  downgrade 는 023 원형으로 복구.
- `frontend/src/pipeline-sdk/definitions/operatorDefinition.tsx` — `UNIMPLEMENTED_OPERATORS` 에서
  `'cls_crop_image'` 제거.
- `backend/tests/test_cls_crop_image.py` — 45건 신규. 방향별 동작 / spec 누적 / extra 보존 / 검증 에러
  (list input / invalid direction / invalid crop_pct) / helper 단위 / 파싱 파라미터라이즈 포함.

**Phase B operation 네이밍.** `crop_image_vertical` 로 직접 명시. 향후 horizontal crop 을 별도
operation 으로 추가할 여지를 남김 — §2-4 의 "det/cls 동일 operation 공유" 원칙과 호환.

### 1-9. `cls_filter_by_class` 실구현 + `cls_remove_images_without_label` 통합 제거

**배경.** 설계서 §5 의 "이미지 단위 필터 2종" (1. label 없는 이미지 제거 / 2. 특정 head 의 특정
class include·exclude 필터) 을 처음엔 별개 노드로 설계했으나, 사용자 확인으로 **두 기능은 단일
노드의 파라미터 조합으로 완전히 커버됨** 이 확인됐다 — "exclude 로 label 이 없는 이미지는 싹 다
날아갈 테니까". 두 seed 를 하나로 합치면 팔레트도 더 간결해진다.

#### 1-9-1. 최종 파라미터 스키마 (4필드)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `head_name` | text | ✓ | 대상 head 이름. head_schema 에 존재해야 함 |
| `mode` | select("include"\|"exclude") | ✓ | 매칭된 이미지를 남길지(include) 버릴지(exclude) |
| `classes` | textarea (줄바꿈 구분) | ✗ | 매칭 대상 class 이름 목록. any-match 정책(1개라도 매칭→match). 비우면 오직 `include_unknown` 로만 판정 |
| `include_unknown` | checkbox | ✗ | `labels[head] is None` 인 이미지도 매칭 대상에 포함 (체크 시 unknown 이 match 로 취급됨) |

v1 은 **match_policy 항상 "any" 고정.** 추후 `all` 이 필요하면 별도 파라미터로 확장.

#### 1-9-2. `null` vs `[]` 구분 규약 (§2-12 승계)

사용자 확정 — 이 둘을 혼동하면 "label 없는 이미지 제거" 같은 기본 동작이 어긋나므로 명문화:

- **`labels[head] is None` → unknown.** `include_unknown` 토글에 의해 match 여부가 결정됨.
- **`labels[head] == []` → explicit empty.** 이 이미지의 상태를 "현재 class 목록 중 어느 것에도
  해당하지 않음" 으로 정확히 알고 있는 것. unknown 이 아니며 `include_unknown` 에 영향받지 않고,
  오직 match_policy(any) 에 의해 처리됨 → `classes_set` 이 비어 있지 않은 한 교집합은 항상 False.

동일 convention 이 §2-12 / `cls_set_head_labels_for_all_images` 에도 동일하게 적용된다.

#### 1-9-3. 통합 사용 예시 — "label 없는 이미지만 제거"

```yaml
# 기존 cls_remove_images_without_label 과 완전 동일한 동작
- operator: cls_filter_by_class
  params:
    head_name: weather
    mode: exclude
    classes: ""           # 빈 목록
    include_unknown: true  # unknown 만 매칭 → exclude → null 인 이미지만 drop
```

`labels[weather] == []` 인 이미지는 그대로 유지 (match_policy 에 의해 매칭되지 않아 drop 안됨).

#### 1-9-4. 반영된 파일

- `backend/lib/manipulators/cls_filter_by_class.py` — stub → 전체 구현.
  - 모듈 레벨 `validate_filter_by_class_params(head_schema, params) -> list[(code, message)]` —
    runtime + 정적 공용 순수 함수. 코드 9종:
    `HEAD_SCHEMA_MISSING`, `HEAD_NAME_MISSING`, `HEAD_NAME_NOT_FOUND`, `MODE_INVALID`,
    `CLASSES_INVALID`, `CLASSES_DUPLICATE`, `CLASSES_NOT_IN_SCHEMA`, `INCLUDE_UNKNOWN_INVALID`,
    `FILTER_MATCHES_NOTHING` (classes 가 비어있는데 include_unknown=false → no-op 차단).
  - helper: `_parse_head_name`, `_parse_mode`, `_parse_classes`, `_parse_include_unknown`,
    `_record_matches`.
  - `transform_annotation` — `validate_filter_by_class_params` 첫 원소를 ValueError 로 승격.
    record 단위로 `_record_matches` 호출 후 `mode` 에 따라 keep/drop. 0건 결과 시 WARNING 로그.
- `backend/lib/manipulators/cls_remove_images_without_label.py` — **삭제.** pkgutil 자동 발견
  레지스트리가 파일 삭제만으로 자동 정리됨 (`MANIPULATOR_REGISTRY` 에서 즉시 빠짐).
- `backend/migrations/versions/027_cls_filter_by_class_unified.py`:
  - UPDATE `cls_filter_by_class` params_schema → 상기 4필드 구조, description 갱신.
  - DELETE `cls_remove_images_without_label` row.
  - downgrade 는 023 stub params 복구 + `cls_remove_images_without_label` row 재삽입
    (`gen_random_uuid()`, `IMAGE_FILTER`, `[PER_SOURCE, POST_MERGE]`, `[CLASSIFICATION]`,
    `[CLS_MANIFEST]`, output `CLS_MANIFEST`).
- `backend/app/services/pipeline_service.py`:
  - `_validate_with_database` docstring 에 6번 항목 추가 + call 추가.
  - 신규 `_validate_cls_filter_by_class_compatibility` — `cls_set_head_labels` compat 과 동형
    (build_stub_source_meta + preview_head_schema_at_task → validate_filter_by_class_params).
    이슈마다 `FILTER_BY_CLASS_{CODE}` prefix 로 ERROR 수집. preview 실패 시
    `FILTER_BY_CLASS_UPSTREAM_PREVIEW_FAILED` WARNING 으로 degrade.
- `frontend/src/pipeline-sdk/styles.ts` — `MANIPULATOR_EMOJI.cls_filter_by_class = '🧮'` 추가.
- `frontend/src/pipeline-sdk/definitions/operatorDefinition.tsx` — `UNIMPLEMENTED_OPERATORS` 에서
  `'cls_filter_by_class'`, `'cls_remove_images_without_label'` 제거 → classification 섹션이 빈
  배열이 됨 (주석 `// classification — (현재 없음; 모든 cls_* 실구현 완료)` 로 기록).
- `backend/tests/test_cls_filter_by_class.py` — **55건 신규.** 11개 섹션:
  - §1~2 include / exclude 기본 동작 + 다중 class
  - §3 include_unknown 토글 (null label 대응, 양방향)
  - §4 `[]` ≠ unknown 명시 테스트 (핵심 규약 검증)
  - §5 multi-label any-policy
  - §6 통합 use case — `label 없는 이미지 제거` (mode=exclude, classes=[], include_unknown=True)
  - §7 head_schema / storage_uri / categories 보존
  - §8 deep copy isolation
  - §9 에러 케이스 7종 (list input / missing head / head not found / class not in schema /
    no-op / invalid mode / duplicate classes)
  - §10 `validate_filter_by_class_params` 순수 함수 — 코드별 1건 + OK 2건 + 다중 이슈 축적
  - §11 parsing helper 파라미터라이즈 (`_parse_mode`, `_parse_classes`, `_parse_include_unknown`)

**테스트 결과.** `backend/tests` 전체 회귀 — **445 / 445 pass.** (이전 390 + 55 = 445.
`test_cls_remove_images_without_label.py` 는 원래 없었음 — stub 상태였기 때문에.)

---

## 2. Registry 상태 (26종)

- Detection: **12 실구현**
- Classification: **14 실구현 + 0 stub** (이전 13 + 2 stub 에서 `cls_filter_by_class` 실구현 전환,
  `cls_remove_images_without_label` 통합 흡수로 seed 제거)
  - 실구현 (14): `cls_rename_head`, `cls_rename_class`, `cls_reorder_heads`, `cls_reorder_classes`, `cls_select_heads`, `cls_merge_datasets`, `cls_merge_classes`, `cls_demote_head_to_single_label`, `cls_sample_n_images`, `cls_rotate_image`, `cls_add_head`, `cls_set_head_labels_for_all_images`, `cls_crop_image`, **`cls_filter_by_class` (신규 — 기존 stub + remove_images_without_label 흡수)**

---

## 3. 다음 작업 체크리스트 (우선순위)

1. **Automation 실구현** (lineage + minor 버전 증가 규약)
2. **Detection 미구현 2종** — `det_change_compression`, `det_shuffle_image_ids` (long-tail).
3. **Step 2 진입 시 `loss_per_head` 스키마 실장** — §6-2 결정 반영.
4. **(future) horizontal crop 필요 시** — `cls_crop_image` 를 확장할지 별도 `cls_crop_image_horizontal`
   로 분리할지 결정. 현재는 수직축만.
5. **(future) filter match_policy "all"** — 현재 v1 은 any 고정. 필요 시 `cls_filter_by_class` 에
   `match_policy: "any"|"all"` 파라미터로 확장.

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
