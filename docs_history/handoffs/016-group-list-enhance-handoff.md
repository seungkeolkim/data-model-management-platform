# 통합 핸드오프 016 — 그룹 목록 UI 개편 + Dataset 변경 시 그룹 updated_at 자동 갱신 완료 후

> 최종 갱신: 2026-04-15
> 이전 핸드오프: `docs_history/handoffs/015-classification-registration-complete-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.1, §2-7-b 반영)
> 이번 세션 브랜치: `feature/enhence-datasetgroup-list-web-ui`
> 주요 커밋: `0c101d9` (필터·정렬·reset), `6655588` (updated_at 자동 갱신 + 컬럼 개편)

015 이후 **Display/UI 분화 잔여 작업(그룹 목록 필터·정렬)** 이 마무리되고,
Dataset 변경 시 부모 그룹 `updated_at` 을 자동 갱신하는 세션 이벤트 리스너가 추가됐다.
다음 세션부터는 **Classification DAG 파이프라인 구축 + 업로드/저장 정합성 강화** 로 넘어간다.

---

## 1. 015 → 016 사이 적용된 변경

### 1-1. 데이터셋 그룹 목록 UI 개편 (`0c101d9`, `6655588`)

| 영역 | 변경 | 위치 |
|------|------|------|
| API | `GET /dataset-groups` 쿼리 확장: 다중 `dataset_type` / `task_type` / `annotation_format`, `sort_by`, `sort_order` | `app/api/v1/dataset_groups/router.py` |
| Service | `list_groups` 가 활성 Dataset 집계 서브쿼리를 LEFT JOIN 해 `dataset_count` / `total_image_count` 정렬까지 지원. 같은 필터 내부는 OR, 서로 다른 필터 간은 AND | `app/services/dataset_service.py` |
| Service | `task_types` JSONB 배열 필터는 `@>` (contains) 의 OR 로 표현. 정렬은 `::text` 캐스팅 후 사전식 | 같은 파일 |
| Axios | `paramsSerializer: { indexes: null }` — FastAPI `list[str]` 쿼리 반복 키(`?k=a&k=b`) 에 맞춤 | `frontend/src/api/index.ts` |
| Frontend UI | 필터 바(3종 `Select mode="multiple"` + 검색 + reset filter). 컬럼 헤더 클릭 서버 측 정렬 | `frontend/src/pages/DatasetListPage.tsx` |
| Frontend UI | 컬럼 순서: 사용 목적 → 그룹명 → 데이터 유형 → 포맷 → Split → 총 이미지 → 상태 → 등록일 → 최종 수정일 → 액션 | 같은 파일 |
| Frontend UI | 사용 목적 태그 색상 분화: DETECTION=geekblue / CLASSIFICATION=magenta / SEGMENTATION=cyan / ZERO_SHOT=gold | 같은 파일 |
| Frontend UI | "최종 수정일" 컬럼 추가 (`updated_at`, `YYYY-MM-DD HH:mm`) | 같은 파일 |

### 1-2. Dataset 변경 시 DatasetGroup.updated_at 자동 갱신 (`6655588`)

| 영역 | 변경 | 위치 |
|------|------|------|
| ORM 이벤트 | `Session.before_flush` 리스너 신설 — flush 에 포함된 Dataset 의 new/dirty/deleted 를 감지해 부모 DatasetGroup.updated_at 을 현재 시각으로 갱신 | `app/models/events.py` (신규) |
| 등록 | FastAPI 프로세스와 Celery worker 양쪽에서 `import app.models.events` 로 리스너 활성화 | `app/main.py`, `app/tasks/celery_app.py` |
| 인덱스 | 추가하지 않음 (사용자 결정 — 현재 규모에서 불필요) | - |

**검증 완료**
- `dataset_type=RAW&dataset_type=SOURCE`, `task_type=CLASSIFICATION&task_type=DETECTION`, `annotation_format=COCO&annotation_format=CLS_MANIFEST` 다중 필터 OR 동작 확인
- `sort_by=total_image_count&sort_order=desc` 로 활성 Dataset 이미지 수 정렬 확인
- 허용 외 `sort_by=invalid` → 422
- PATCH `/datasets/{id}` 직후 부모 그룹 `updated_at` 이 현재 시각으로 갱신됨

**브랜치 상태**: `feature/enhence-datasetgroup-list-web-ui` — 미머지, PR/머지 여부 사용자 판단 대기.

---

## 2. 현재 baseline 스냅샷

015 baseline 에 위 변경 반영. 나머지는 변동 없음.

- **백엔드**: FastAPI async + Celery sync. `list_groups` 는 다중 필터 + 서버 측 정렬 + 활성 Dataset 집계 LEFT JOIN.
- **데이터 모델**: DatasetGroup / Dataset 등 스키마 변경 없음. `DatasetGroup.updated_at` 은 ORM onupdate + 세션 리스너 이중 관리.
- **파이프라인**: Detection 12종 manipulator + DAG SDK. Classification 은 RAW 등록만 가능 (파이프라인 실행 불가 상태 유지).
- **프론트**: 그룹 목록이 Classification/Detection 혼재를 전제로 필터·정렬·색상 분화됨. 상세 뷰어도 dataset_type/task_types 기반 분화 완료.
- **Automation**: 정책 미확정 (lineage 조정 + minor 버전 증가 규약 필요) — 구현 대기.

---

## 3. 남은 작업 (우선순위 순)

### 3-1. Classification DAG 파이프라인 + 업로드/저장 정합성 [1순위 — 다음 세션 주제]

> 이번 세션 직후 즉시 착수 예정. 이 핸드오프의 **핵심 다음 작업**.

Classification 은 현재 RAW 등록만 되고 파이프라인은 실행 불가 상태다.
동시에 업로드/저장 경로에 실측되지 않은 가정이 섞여 있어, 파이프라인 도입 전에 정합성 기반 다지기가 필요하다.

**3-1-a. Classification IO 계층**
- `lib/pipeline/io/` 에 `CLS_MANIFEST` 파서/라이터 추가
  - 입력: `manifest.jsonl` + `head_schema.json` + `images/{sha}.{ext}` 풀
  - 출력: 동일 레이아웃. SHA-1 재계산 불필요 (이미지 바이너리 보존 시), rotate/compress 등 바이너리 변경 시는 재계산
- `DatasetMeta` / `ImageRecord` 모델에 classification 라벨 필드(`labels: dict[str, list[str]]`) 반영 가능성 검토
  - 통일포맷 유지 원칙을 따르되, detection `annotations` 와 classification `labels` 를 어떻게 공존시킬지 설계 필요
- 파이프라인 executor 가 양쪽 task_type 을 분기 없이 다룰 수 있는지 확인 (현재는 bbox 전제의 Phase A 가 있음)

**3-1-b. Classification 전용 manipulator (제안)**
- `augment_image_classification_{flip,crop,colorjitter,...}` — 이미지 바이너리 변경 → SHA 재계산 + manifest 업데이트
- `filter_by_head_class` — 특정 head/class 포함/제외
- `remap_head_class` — head_schema 의 class rename (DatasetGroup.head_schema diff 와의 관계 설계 필요)
- `split_by_class_ratio` — class 분포 기반 stratified split
- `merge_datasets` / `sample_n_images` 재검토 — classification 호환 여부 실측
- seed 갱신: `compatible_task_types` / `compatible_annotation_fmts` 에 `CLS_MANIFEST` 추가

**3-1-c. 업로드/저장 정합성 강화**
- 등록 시점의 SHA-1 중복 정책(FAIL/SKIP) 이 파이프라인 산출물 경로에서도 일관되게 적용되는지 확인 — 현재 `lib/classification/ingest.py` 에만 존재
- `head_schema` 불변식 (기존 class 순서 변경/삭제 금지) 을 manipulator(예: remap_head_class) 에서도 동일 규칙으로 강제
- `manifest.jsonl` 라인 불변식 — sha, filename(`images/{sha}.{ext}`), original_filename, labels 필수. labels 는 head 이름 키만 허용 (schema 외 키 금지)
- `storage_uri` 하위 레이아웃 실측 검증 유틸: `images/{sha}.{ext}` 실파일 존재 ↔ manifest 라인 ↔ head_schema class 집합 간 일관성 점검 (정합성 audit 엔드포인트 후보)
- Detection 측도 동일 원칙 점검 — `annotation_files` JSONB 와 실파일 존재 여부가 어긋날 수 있음

**3-1-d. GUI 에디터 대응**
- Data Load 노드가 classification 그룹을 선택할 수 있어야 함 (현재는 annotation_format / task_types 필터로 차단될 가능성)
- Save 노드의 `annotation_format` 옵션에 `CLS_MANIFEST` 포함
- Operator 팔레트에서 `compatible_task_types` 에 CLASSIFICATION 포함된 manipulator 만 노출 (SDK 이미 지원)

### 3-2. Automation 실구현 [2순위 — 정책 확정 대기]

6차 설계서 §6 시나리오. lineage 조정 작업(별도)과 minor 버전 증가 규약 확정 후 진행.
- `PipelineTemplate` DB
- `find_downstream_templates(source_dataset_id)` — lineage 역추적
- `dispatch_automation_run(template, is_automation=True)` — Celery, minor 증가
- 실패/중복 방지

### 3-3. 미구현 Manipulator 2종 (detection용) [3순위]

014 §3-3 과 동일.
- `change_compression` — JPEG/PNG 재인코딩
- `shuffle_image_ids` — COCO image_id 셔플

### 3-4. 버전 정책 운영 검증

Automation 과 함께 검증.

### 3-5. 잔여 백로그 (p3 이하)

015 §3-6 계승. 추가 사항 없음.

- Classification storage admin viewer (`images/{sha}.{ext}` + `manifest.jsonl` + `head_schema.json` + `process.log`)
- head_schema 일관성 위반 diff 시각화
- `metadata.class_info.intra_class_duplicates` / `skipped_conflicts` 뱃지

### 3-6. Phase 3 — 2차 수용 준비 & UX 정리

014 §3-6 그대로.

---

## 4. 유의사항 / 규약

015 §4 전부 승계. 이번 세션에서 추가/확인된 사항:

- **DatasetGroup.updated_at 자동 갱신 리스너**
  - `Session.before_flush` 전역 리스너라서 ORM 경로의 Dataset mutation 에 자동 반응한다. **Core bulk 문(`update(Dataset).where(...).values(...)` 등) 은 트리거하지 않으므로** 해당 코드 경로에서는 부모 그룹을 별도로 dirty 상태로 만들거나 UPDATE 문을 명시적으로 보내야 한다.
  - 현재 코드베이스에서는 `delete_group` 만 Core bulk 를 쓰는데, 그 플로우는 `group.deleted_at = now` 로 그룹이 ORM 경로로 dirty 가 되므로 `onupdate=_now` 가 함께 작동해 updated_at 이 갱신된다. 향후 Core bulk Dataset 수정을 도입할 때는 반드시 그룹 갱신을 같이 넣을 것.
  - Celery worker 프로세스에서도 반드시 `import app.models.events` 가 로드되어야 한다 (`app/tasks/celery_app.py` 에 이미 포함).
- **그룹 목록 필터/정렬 API 계약**
  - 다중 값은 반복 키(`?k=a&k=b`) 방식. 프론트 Axios 는 `paramsSerializer: { indexes: null }` 로 설정됨 — 다른 list 쿼리 API 도입 시 동일 규약 유지.
  - `sort_by` 화이트리스트(`_SORTABLE_COLUMN_KEYS`) 밖의 값은 `updated_at` 으로 폴백. 새 정렬 컬럼 도입 시 서비스 + 라우터 pattern + 프론트 타입 세트로 갱신.
  - 인덱스는 의도적으로 추가하지 않은 상태. 규모가 커지면 `(deleted_at, updated_at)`, `(deleted_at, name)` 등 복합 인덱스를 고려.
- **태스크 타입 태그 색상 규약**
  - 목록 페이지에서 이미 확정된 색상 매핑(`TASK_TYPE_TAG_COLOR`) 을 상세 페이지/뷰어에서도 통일할 것. 재정의 대신 공용 상수화 권장 (차후 리팩토링 후보).

---

## 5. 다음 세션 착수 체크리스트

다음 세션에서 Classification DAG 파이프라인 + 정합성 작업 시작 시 먼저 확인할 것:

1. 이번 브랜치(`feature/enhence-datasetgroup-list-web-ui`) 머지 여부 확정
2. `lib/pipeline/` 현재 구조 재독: `executor.py`, `dag_executor.py`, `io/`, `models.py`
3. `lib/classification/ingest.py` 의 SHA-1 / manifest / head_schema 계약 재독
4. `docs/pipeline-node-sdk-guide.md` 통독 (새 manipulator 추가 규약)
5. Classification DAG 설계 문서 초안 작성 → 사용자 리뷰 후 구현 (통일포맷 내부 표현을 어떻게 확장할지, detection 과의 분기 지점 결정)
6. 정합성 audit 유틸 먼저 만들고, 현 기존 Classification 등록 결과가 audit 을 통과하는지 확인 → 이후 manipulator 구현
