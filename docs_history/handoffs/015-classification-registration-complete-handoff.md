# 통합 핸드오프 015 — Classification 등록 완료 후

> 최종 갱신: 2026-04-14
> 이전 핸드오프: `docs_history/handoffs/014-node-sdk-complete-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (§2-8 Classification 등록 반영)
> 이번 세션 브랜치: `feature/add-classification-data` (미머지, PR 대기)

014 시점 이후 **Classification 데이터 등록** 전 과정이 구현·테스트되었다. 014 잔여 TODO의 1순위(Classification 데이터 입력)가 종결되어 이 핸드오프에서는 제거되고, 대신 **UI 분화(Display)** 작업이 다음 1순위로 이동한다.

---

## 1. 014 → 015 사이 적용된 변경

| 영역 | 변경 | 위치 |
|------|------|------|
| DB | `DatasetGroup.head_schema JSONB` 컬럼 추가 (classification 전용 SSOT) | `migrations/versions/009_add_head_schema.py`, `app/models/all_models.py` |
| Enum | `AnnotationFormat`: `CLS_FOLDER` 제거, `CLS_MANIFEST` 신규 | `app/schemas/dataset.py`, `frontend/src/types/dataset.ts` 외 |
| 순수 로직 | `lib/classification/ingest.py` — SHA-1 content hash, flat `images/{sha}.{ext}` 풀, `manifest.jsonl`, `head_schema.json` 생성 | `backend/lib/classification/` |
| 중복 처리 | `ImageOccurrence` 전수 추적 — 파일명이 달라도 어느 폴더의 어떤 파일이 충돌인지 양쪽 기록 | `lib/classification/ingest.py` |
| 중복 처리 | `IntraClassDuplicate` — 같은 (head, class) 폴더 내 동일 SHA 중복 경고 수집 | `lib/classification/ingest.py` |
| Celery | `register_classification_dataset` task — PROCESSING→READY/ERROR 전이, 실패 시 `dest_root/process.log` 보존 (자식만 정리) | `app/tasks/register_classification_tasks.py` |
| Service | `DatasetGroupService.register_classification_dataset` + `_diff_head_schema` / `_merge_head_schema` (순서 변경/삭제 차단, NEW_HEAD/NEW_CLASS warning) | `app/services/dataset_service.py` |
| API | `POST /dataset-groups/register-classification` 202 응답 + warnings | `app/api/v1/dataset_groups/router.py` |
| Pydantic | `ClassificationHeadSpec`, `DatasetRegisterClassificationRequest/Response`, `ClassificationHeadWarning`, `DuplicateImagePolicy` (FAIL/SKIP) | `app/schemas/dataset.py` |
| Frontend API | `datasetGroupsApi.registerClassification()` + 전용 타입 | `frontend/src/api/dataset.ts`, `frontend/src/types/dataset.ts` |
| Frontend UI | `DatasetRegisterModal` classification 분기 — 2레벨 폴더 스캔, editor 패널(head/class 순서·이름·multi_label), FAIL/SKIP 라디오, has_subdirs 차단, class-없는-head 경고, 완료 안내는 detection과 동일 | `frontend/src/components/dataset/DatasetRegisterModal.tsx` |
| 관측 | 실패 시 `process.log`에 원인·조치 기록 (FAIL: 양쪽 occurrence / UNEXPECTED: traceback / SKIP·intra-class: 상세 목록) | `app/tasks/register_classification_tasks.py` |

**검증 완료**: hardhat_classification/val (5,613장) 등록 성공 (0.94s). `hardhat_duplicated` 그룹으로 FAIL/SKIP 정책 + intra-class duplicate 케이스 실측 확인. `process.log`에 충돌 양쪽 파일명/절대경로 모두 노출됨을 확인.

**브랜치 상태**: `feature/add-classification-data` — 아직 main 미머지. PR 생성 및 main 병합은 사용자 판단 대기.

---

## 2. 현재 baseline 스냅샷 (014 §2에 위 변경 반영)

- **백엔드**: FastAPI + async SQLAlchemy. Celery(sync 세션)로 파이프라인 실행, Detection RAW 등록, **Classification RAW 등록** 분담.
- **RAW 등록 경로 분기**:
  - Detection: `POST /dataset-groups/register` + `app/tasks/register_tasks.py`
  - Classification: `POST /dataset-groups/register-classification` + `app/tasks/register_classification_tasks.py`
- **데이터 저장 구조**:
  - Detection: 이미지 디렉토리 + 어노테이션 파일(COCO JSON / YOLO txt) 복사
  - Classification: `images/{sha}.{ext}` 단일 풀 + `manifest.jsonl` + `head_schema.json`
- **DB 모델 확장**: `DatasetGroup.head_schema JSONB` (classification만 사용, detection은 NULL). 나머지 테이블 스키마 변경 없음.
- **중복 검출 규약 (classification)**:
  - SHA-1은 **파일 바이너리 내용** 해시. 파일명·EXIF·경로 무관
  - single-label head에서 동일 SHA가 여러 class → FAIL(중단) / SKIP(양쪽 제외)
  - 동일 (head, class) 내 중복 → intra-class warning (pool에는 첫 파일만)
  - 모든 충돌은 `ImageOccurrence` 전체(class/파일명/절대경로)로 기록
- **파이프라인·에디터·버전 정책 등 나머지 사항**: 014와 동일 (변동 없음).

---

## 3. 남은 작업 (우선순위 순)

### 3-1. Display / UI 분화 [1순위 — 다음 세션 주제]

> 이번 세션 직후 즉시 착수 예정. 이 핸드오프의 **핵심 다음 작업**.

Classification 등록은 되지만 **조회 쪽 UI가 detection 가정으로 짜여 있어 classification 데이터가 어색하게 보인다**. 두 갈래로 분리 필요.

**3-1-a. 메인 데이터셋 그룹 목록 — 필터 & 정렬**

현재 `frontend/src/pages/DatasetGroupListPage.tsx`(또는 `DatasetListPage.tsx`, 확인 필요)가 그룹 목록을 단순 리스트로 노출. 고도화 필요 항목:

- **필터**:
  - `task_types` (DETECTION / CLASSIFICATION / SEGMENTATION / ZERO_SHOT)
  - `dataset_type` (RAW / SOURCE / PROCESSED / FUSION)
  - `annotation_format`
  - 이름 검색 (백엔드는 이미 `search` 쿼리 지원 — `app/api/v1/dataset_groups/router.py:list_dataset_groups`)
- **정렬**: 이름 / 최근 생성 / 최근 수정 / 데이터셋 개수 / 총 이미지 수
- 백엔드 API (`GET /dataset-groups?page&page_size&dataset_type&search`)는 이미 페이지네이션·검색 지원. 필터/정렬 신설 시 쿼리 확장 필요 여부 판단 후 추가.

**3-1-b. 그룹/데이터셋 상세 — Classification vs Detection UI 분기**

현재 `frontend/src/pages/DatasetDetailPage.tsx`, `DatasetListPage.tsx`는 detection 전제. 다음 요소들이 classification에서는 부적절:

- `class_count` (int) — classification은 NULL. 대신 `metadata.class_info.heads[]` 표시 필요
- `annotation_files` — detection은 COCO/YOLO 파일, classification은 `manifest.jsonl` 1개
- EDA (`EdaStatsResponse` — class_distribution / bbox_area_distribution) — bbox_area는 classification 무의미
- Sample viewer — bbox overlay는 classification에 없음. 대신 head별 label tag 표시

**권장 설계 방향**:
1. 그룹/데이터셋의 `dataset_type` 또는 `task_types[0]`를 기준으로 **탭 또는 컴포넌트 스왑**
2. 공용 요소(메타 / 버전 / split 목록 / 상태)는 단일 컴포넌트
3. detection-only / classification-only 섹션은 `<DetectionSpecificPanel>`, `<ClassificationSpecificPanel>` 등으로 분리
4. `metadata.class_info.heads[]` + `head_schema` JSONB 렌더링 전용 컴포넌트 신설
5. `process.log` viewer (ERROR 상태의 classification dataset에서 링크로 노출)

**유의사항**:
- classification dataset 응답에도 `metadata.class_info.heads[]` / `skipped_conflicts` / `intra_class_duplicates` / `error.process_log_relpath` 가 이미 포함되므로 프론트에서 활용만 하면 됨
- 기존 detection 페이지의 빈 상태/에러 패턴을 먼저 파악해서 톤 맞출 것
- EDA가 bbox 전제인지 확인 필요 — classification이면 head별 class distribution으로 대체해야 함

### 3-2. Automation 실구현 [2순위]

6차 설계서 §6 시나리오. 014 §3-2와 동일.
- `PipelineTemplate` — DB에 템플릿 저장
- `find_downstream_templates(source_dataset_id)` — lineage 역추적
- `dispatch_automation_run(template, is_automation=True)` — Celery, minor 증가
- 실패/중복 방지: 동일 `(template_id, source_version)` 재실행 스킵

### 3-3. Classification 파이프라인 확장 [3순위]

현재 모든 manipulator가 detection 가정(bbox 조작 / COCO·YOLO 파서). Classification은 RAW 등록만 가능하고 파이프라인 실행은 불가.

- `CLS_MANIFEST` 포맷을 읽는 IO 파서/라이터 추가 (`lib/pipeline/io/`)
- Classification 전용 manipulator 후보: `augment_image_classification`, `filter_by_class_count`, `remap_head_class`, `split_by_class_ratio`
- 기존 공통 manipulator(`sample_n_images`, `merge_datasets`) 는 classification 호환 여부 재검토
- `compatible_task_types` / `compatible_annotation_fmts` seed 갱신

### 3-4. 미구현 Manipulator 2종 (detection용) [4순위]

014 §3-3과 동일.
- `change_compression` — JPEG/PNG 재인코딩
- `shuffle_image_ids` — COCO image_id 셔플

### 3-5. 버전 정책 운영 검증

014 §3-4와 동일. Automation과 함께 검증.

### 3-6. 잔여 백로그 (p3 이하)

014 §3-5 그대로 계승. 추가로:
- Classification dataset의 `storage_uri` 이하 구조(`images/{sha}.{ext}` + `manifest.jsonl` + `head_schema.json` + `process.log`)에 대한 admin viewer
- head_schema 일관성 위반 시 사용자에게 diff 시각화 (현재는 ValueError 문자열만)
- `metadata.class_info.intra_class_duplicates` 가시화 (warning 뱃지)

### 3-7. Phase 3 — 2차 수용 준비 & UX 정리 (예정)

014 §3-6 그대로.

---

## 4. 유의사항 / 규약

014 §4 전부 승계. 추가:

- **Classification 등록 후속 UI 작업 시**: `Dataset.annotation_format === 'CLS_MANIFEST'` 또는 `DatasetGroup.head_schema != null` 을 분기 키로 사용. `class_count` 유무로 판단하지 말 것 (classification에서는 NULL이지만 detection도 NULL일 수 있음).
- **head_schema 스키마 변경 금지**: 이미 운영되는 계약 — `{heads:[{name, multi_label, classes:[...]}]}`. 확장 시 `heads[].*` 옵션 필드 추가만 허용. 기존 키 이름 변경 금지.
- **SHA-1 정책**: 파일 바이너리 해시. 재인코딩/리사이즈/메타 변경은 다른 이미지로 판정됨 — classification manipulator 도입 시 이 점 인지.
- **process.log**는 사용자가 읽는 파일. 구조/문구 바꿀 때 detection `processing.log` 와 혼동 주의(파일명이 다르다: classification=`process.log`, pipeline 실행=`processing.log`).
- **브랜치 `feature/add-classification-data` 미머지 상태** — UI 분화 작업 시작 전 PR 생성/머지 여부 사용자 확인 후 진행.
