# 통합 핸드오프 017 — Classification DAG 에디터 + Celery 실행 경로 완성 후

> 최종 갱신: 2026-04-15
> 이전 핸드오프: `docs_history/handoffs/016-group-list-enhance-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.2, §2-4·§2-10 갱신)
> 이번 세션 브랜치: `feature/classification-pipeline-dag`
> 주요 커밋:
> - `3a4dcb5` Classification DAG 에디터 + manipulator 8종 stub
> - `7d57bfa` Load→Save 직결(passthrough) 파이프라인 + Classification 최소 실행 경로
> - `85bd3d0` head_schema/labels IO 정합성 + manipulator 네이밍 정리
> - `41176f0` passthrough 모드 pipeline.png 생성
> - `245df5e` cls_ prefix 통일 (classification 10종)
> - `179f675` det_ prefix 통일 (detection 14종) + migration 014 + rotate_image operation 버그 수정
> - `ccb61f8` pipeline-node-sdk-guide 전면 재작성

016 이후 **Classification 파이프라인 실행 경로(DAG UI + Celery runner + passthrough)** 와
**manipulator 네이밍 규약(cls_/det_ prefix) + 가이드 재작성** 이 완료됐다.
Classification manipulator 실체는 **전부 stub** 인 상태. 다음 세션부터는 **Classification operator 를 하나씩 실구현** 한다.

---

## 1. 016 → 017 사이 적용된 변경

### 1-1. Classification DAG 에디터 기본 + manipulator 8종 stub (`3a4dcb5`)

| 영역 | 변경 |
|------|------|
| Frontend | 파이프라인 에디터에서 Classification 그룹도 Data Load / Save 대상으로 선택 가능 |
| Frontend | Operator 팔레트가 `compatible_task_types` 에 CLASSIFICATION 포함된 manipulator 만 노출 (SDK 기존 분기 재활용) |
| Backend | classification 전용 manipulator 8종 stub 추가 (`rename_head/class`, `reorder_heads/classes`, `select_heads`, `filter_by_class`, `merge_classes`, `remove_images_without_label`) |
| Seed | migration 010 에 `SCHEMA` 카테고리 도입 (head_schema 조작 전용) |

### 1-2. Load→Save 직결(passthrough) 파이프라인 + Classification 최소 실행 경로 (`7d57bfa`)

- `PipelineConfig.tasks` 가 비어 있는 경우(passthrough) 를 정식 실행 모드로 수용
- `OutputConfig.passthrough_source_dataset_id` 추가 — Load 노드의 source dataset 을 그대로 새 Dataset 으로 복제
- DAG executor: Load→Save 직결 시 annotation/이미지 바이너리 모두 무변경 복사, lineage 엣지 1개 생성
- Celery runner 가 classification task_kind 를 인식 (DatasetMeta.head_schema 존재 여부로 분기)
- GUI 에디터: Load 1개 + Save 1개만 있는 그래프가 client validation 통과하도록 허용

**end-to-end 검증 완료**: classification RAW → passthrough 실행 → SOURCE 생성 → lineage 1 edge.

### 1-3. head_schema / labels IO 정합성 + manipulator 네이밍 정리 (`85bd3d0`)

- `manifest.jsonl` 의 `labels` 는 항상 `list[str]` — 단일 라벨도 `["helmet"]` 형태 유지 (IO 왕복 무손실)
- `head_schema.json` 은 DatasetGroup.head_schema 의 불변 스냅샷 — passthrough/복제 시 그대로 복사
- 일부 manipulator 이름을 서술형으로 정리 (prefix 붙이기 전 단계)

### 1-4. passthrough 모드 pipeline.png 생성 (`41176f0`)

- 기존 `pipeline.png` 생성기가 `tasks` 비어있을 때 예외 없이 Load→Save 2-노드 그래프를 렌더링하도록 수정
- classification passthrough 실행 산출물 디렉토리에도 `pipeline.png` 가 남음

### 1-5. Classification 네이밍 통일 — `cls_` prefix (`245df5e`)

- 10종 전부 `cls_` prefix 로 일괄 rename:
  - `cls_filter_by_class`, `cls_merge_classes`, `cls_merge_datasets`,
    `cls_remove_images_without_label`, `cls_rename_class`, `cls_rename_head`,
    `cls_reorder_classes`, `cls_reorder_heads`, `cls_sample_n_images`, `cls_select_heads`
- migration 013 에서 manipulators 테이블 + 기존 pipeline_executions.config 내부 operator 문자열도 동기 rename

### 1-6. Detection 네이밍 통일 — `det_` prefix + rotate_image operation 버그 수정 (`179f675`)

- detection 14종 전부 `det_` prefix 로 일괄 rename (migration 014)
- **중대 버그 수정**: `det_rotate_image.py` 의 `ImageManipulationSpec.operation` 문자열이 sed 일괄치환으로 `"det_rotate_image"` 로 잘못 바뀌어 있었음 → `"rotate_image"` 로 복구
  - operator(=manipulator.name, prefix 대상) 와 operation(=ImageMaterializer dispatch key, prefix **없음**) 은 별개 namespace. 가이드 §2에 규약 명시
  - Celery worker 는 auto-reload 하지 않음 → 파일 수정 후 `docker compose restart celery-worker` 필요 (트러블슈팅 기록)

### 1-7. pipeline-node-sdk-guide 전면 재작성 (`ccb61f8`)

- `docs/pipeline-node-sdk-guide.md` 를 현행 구현 기준으로 싹 다시 씀 (635+ / 205-)
- 구성: 0. 구조 한눈에 / 1. 용어표 / 2. 이름 규약(prefix + operation 분리) / 3. A경로 Manipulator 추가 / 4. B경로 NodeKind 추가 / 5. 함정 Q&A / 6. 파일 수정 지점 요약표 / 7. 유지보수 메모
- UnitManipulator ABC 실 signature(`transform_annotation(input_meta, params, context=None)`, `build_image_manipulation(image_record, params)`, `accepts_multi_input` 등) 반영
- MANIPULATOR_REGISTRY 자동 발견, assertRegistryCompleteness, MATCH_ORDER, placeholder claim cascade 등 실구현 계약 명시

**브랜치 상태**: `feature/classification-pipeline-dag` — 미머지, PR/머지 여부 사용자 판단 대기.

---

## 2. 현재 baseline 스냅샷 (2026-04-15 post-session)

016 baseline 에 위 변경 반영.

- **백엔드**: FastAPI async + Celery sync 동일. Celery runner 가 classification task_kind 인식. passthrough 모드 정식 지원.
- **데이터 모델**: 스키마 변동 없음. head_schema / manifest.jsonl / head_schema.json 불변식 유지.
- **파이프라인**: Detection 14종(`det_` prefix) + Classification 10종(`cls_` prefix) = **총 24종** registry 등록. **Classification 10종은 전부 stub** — transform_annotation 이 input_meta 를 그대로 반환하거나 NotImplementedError.
- **실행 경로**: Detection 파이프라인은 기존과 동일. Classification 은 Load→Save 직결 passthrough 만 end-to-end 검증 완료. operator 를 한 개라도 물리면 stub 이 no-op 이므로 결과가 Load 와 동일하게 나옴.
- **GUI**: 에디터가 Classification 그룹을 입력으로 받고 Classification 전용 manipulator 팔레트를 노출함. Save 노드의 `annotation_format` 에 `CLS_MANIFEST` 포함.
- **문서**: pipeline-node-sdk-guide 현행화 완료 → 다음 세션부터 이 가이드를 A경로(Manipulator 추가) 레시피로 그대로 사용 가능.

---

## 3. 남은 작업 (우선순위 순)

### 3-1. Classification operator 실구현 [1순위 — 다음 세션 주제]

> 이번 세션 직후 즉시 착수 예정. 가이드 §3 A경로 레시피를 따라 10종을 하나씩 실구현.

현재 10종 모두 stub(`transform_annotation` 이 passthrough) 이다. 우선순위는 **IO 바이너리 불변 → head_schema 조작 → 실제 레이블 조작 → 이미지 바이너리 변경** 순으로 리스크를 낮추는 방향 권장.

**3-1-a. 1차 묶음 — 바이너리 불변 + manifest/head_schema 만 수정 (쉬움)**
- `cls_rename_head` — head name rename. head_schema.heads[*].name + manifest labels 키 동시 갱신.
- `cls_rename_class` — 특정 head 내 class rename. schema 의 classes 배열 + manifest labels 값 동시 갱신.
- `cls_reorder_heads` — head 순서 재배열. schema 의 heads 순서만 변경. (학습 인덱스 계약 영향 없음 — head 는 이름 기반 매핑)
- `cls_reorder_classes` — 특정 head 의 classes 순서 재배열. **학습 인덱스 계약 깨짐 — 반드시 warning**. single-label/multi-label 관계없이 라벨 자체는 이름 기반이라 manifest 는 무변동.
- `cls_select_heads` — 특정 head 들만 유지. schema 에서 drop + manifest labels 에서 해당 키 제거.

**3-1-b. 2차 묶음 — 레코드 단위 필터 (중간)**
- `cls_filter_by_class` — (head, class) 포함/제외 필터. single-label head 기준 drop 시 이미지 자체 제외. multi-label head 는 해당 label 만 제거할지, 이미지 제외할지 policy 결정 필요.
- `cls_remove_images_without_label` — 특정 head 라벨이 비어 있는 이미지 제외.
- `cls_sample_n_images` — n 장 무작위 샘플. seed 옵션 필요. stratified 여부는 별도 manipulator 후보.

**3-1-c. 3차 묶음 — 그룹 머지 + 클래스 머지 (어려움)**
- `cls_merge_classes` — 같은 head 내 여러 class 를 하나로 통합. manifest labels 값 rewrite + schema classes 축소.
- `cls_merge_datasets` — 여러 classification Dataset 병합. `accepts_multi_input=True`. 핵심 이슈:
  - 입력 간 head_schema 정합(head 이름/순서/class 순서/multi_label 플래그 일치)을 어떻게 강제할 것인가
  - SHA-1 중복 이미지 처리 정책 (FAIL / SKIP / PREFER_LEFT 등)
  - manifest 병합 전략 (append + dedup)

**3-1-d. IO/실행 계층 선행 점검**
- `lib/pipeline/io/` 에 `CLS_MANIFEST` 파서/라이터가 passthrough 경로에 한해서만 있음 → operator 가 붙는 순간 **manifest 전체 rewrite 경로** 가 필요. 바이너리 불변 case 에서도 `manifest.jsonl` 은 반드시 재작성되어야 함.
- `head_schema.json` 은 operator 결과 schema 의 스냅샷으로 매번 재작성.
- DatasetGroup.head_schema 와 새로 생성되는 Dataset 의 schema snapshot 이 어긋날 때의 정책 확정(그룹 schema 우선? Dataset snapshot 이 upstream 인가?) — 현재는 passthrough 라 문제가 드러나지 않음.
- `ImageMaterializer` 의 operation dispatch 에 classification 측에서 필요한 image 변환(예: crop, resize) 이 아직 없음. 이미지 바이너리 변경을 동반하는 cls augment manipulator 는 **2단계** 에서 도입 (현재 10종에는 없음).

**3-1-e. 정합성 audit (가능하면 operator 본격 구현 전에)**
- `storage_uri` 하위의 `images/{sha}.{ext}` 실파일 ↔ `manifest.jsonl` 라인 ↔ `head_schema.json` class 집합 간 일관성 검증 유틸
- 등록된 classification Dataset 전수에 대해 audit 통과 확인 → operator 단위 테스트의 baseline 으로 사용

### 3-2. Automation 실구현 [2순위 — 정책 확정 대기]

016 §3-2 승계. lineage 조정 + minor 버전 증가 규약 확정 후 진행.

### 3-3. 미구현 Detection Manipulator 2종 [3순위]

- `det_change_compression` — JPEG/PNG 재인코딩
- `det_shuffle_image_ids` — COCO image_id 셔플

### 3-4. 버전 정책 운영 검증

Automation 과 함께.

### 3-5. 잔여 백로그 (p3 이하)

016 §3-5 승계.

### 3-6. Phase 3 — 2차 수용 준비 & UX 정리

016 §3-6 승계.

---

## 4. 유의사항 / 규약

016 §4 전부 승계. 이번 세션에서 추가/확인된 사항:

- **Manipulator 네이밍 prefix 규약 (절대 준수)**
  - detection 14종 = `det_` prefix, classification 10종 = `cls_` prefix. 향후 segmentation 은 `seg_` / detection+segmentation 겸용은 `detseg_` 등 도메인 prefix 사용.
  - prefix 는 `manipulator.name` 에만 붙는다. `ImageManipulationSpec.operation` 문자열에는 **절대로 prefix 붙이지 말 것**. operator(DAG/registry 키) 와 operation(ImageMaterializer dispatch 키) 은 별개 namespace. 이번 세션 rotate_image 버그 재발 방지.
  - 새 manipulator seed 시 migration 에서 manipulators.name + pipeline_executions.config jsonb 내부 operator 문자열 양쪽을 동시에 갱신해야 lineage 호환. 014/013 migration 패턴 그대로 복제.
- **Celery worker 는 auto-reload 하지 않음**
  - backend 는 uvicorn `--reload` 로 즉시 반영되지만, celery-worker 컨테이너는 그렇지 않다. manipulator/taskdefinition 수정 후 **반드시 `docker compose restart celery-worker`** (또는 `make up-build`).
- **classification stub 상태**
  - 현재 10종 manipulator 가 실 로직 없음. 에디터에서 배치해서 실행하면 no-op 처럼 동작해 Load 결과가 그대로 Save 된다. 이 현상을 "버그" 로 오판하지 말 것 (stub 의도).
- **passthrough 모드**
  - `PipelineConfig.tasks` 빈 dict + `OutputConfig.passthrough_source_dataset_id` 설정이 정식 실행 모드. GUI 에서 Load→Save 직결 시 자동 생성.
  - manipulator 를 하나라도 배치하면 passthrough 모드가 아님. operator 구현 시 이 경로로 빠지지 않도록 test 케이스 분리.
- **pipeline-node-sdk-guide 재작성본 기준**
  - 다음 세션부터는 가이드 §3 A경로 레시피(파일 1개 + seed 1건) 를 그대로 따라가면 됨. 가이드에 없는 패턴이 필요하면 **먼저 가이드를 갱신** 후 구현 (역방향 금지).

---

## 5. 다음 세션 착수 체크리스트

다음 세션에서 Classification operator 실구현 시작 시 먼저 확인할 것:

1. 이번 브랜치(`feature/classification-pipeline-dag`) 머지 여부 확정 (미머지면 rebase/merge 정책 결정)
2. `docs/pipeline-node-sdk-guide.md` §3 통독 — A경로 Manipulator 추가 레시피
3. `lib/manipulators/cls_*.py` stub 10종 전수 훑어 실구현 목표 signature 확인
4. `lib/classification/ingest.py` 의 SHA-1 / manifest / head_schema 계약 재독 — operator 가 재작성 시에도 동일 불변식을 유지해야 함
5. `lib/pipeline/io/` 에 CLS_MANIFEST 쓰기 경로가 operator 결과를 처리할 수 있는지 먼저 실측 (passthrough 외)
6. 정합성 audit 유틸이 아직 없으면 **먼저** 만들고 기존 classification Dataset 들이 통과하는지 확인 → 이후 operator 를 하나씩 붙이며 audit 재검증
7. 첫 operator 는 **바이너리 불변 + manifest/schema 조작만** 인 `cls_rename_head` 또는 `cls_select_heads` 권장 (리스크 최소)
