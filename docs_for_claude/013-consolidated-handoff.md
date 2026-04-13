# 통합 핸드오프 — 001~012 누적 정리

> 최종 갱신: 2026-04-13
> 이전 핸드오프: `docs_history/handoffs/001~012-*.md` (아카이브)
> 설계 현행: `objective_n_plan_5th.md` (v5.2)

이 문서는 001~012 핸드오프에서 **아직 유효한 후속 작업**만 추려 통합한 것이다. 완료되어 main에 반영된 구현 히스토리와 invalidate된 설계(polling 모달, 3단계 semver, FILTER 단일 카테고리, category_id 기반 로직, `filter_final_classes`/`rotate_180`/`filter_invalid_class_name` 등 구 네이밍, multi-format 검증 등)는 생략했다. 완료 항목은 `objective_n_plan_5th.md` §2 참고.

---

## 1. 현재 시스템 스냅샷 (요약)

- **백엔드**: FastAPI + async SQLAlchemy + Alembic. Celery worker는 sync 세션(`SyncSessionLocal`)으로 파이프라인 실행 및 RAW 등록 처리. Broker/Backend = PostgreSQL.
- **파이프라인 모델**: DAG 기반 `PipelineConfig` (tasks dict). 내부는 **통일포맷** — `Annotation.category_name: str`, `DatasetMeta.categories: list[str]`. 포맷별 ID는 IO 경계(파서/라이터)에서만 처리.
- **MANIPULATOR_REGISTRY (12종)**: format_convert 4종(모두 no-op), merge_datasets, annotation/image 필터 3종, remap_class_name, rotate_image, mask_region_by_class, sample_n_images.
- **GUI 파이프라인 에디터**: React Flow + Zustand `nodeDataMap` 단일 소스. 4종 커스텀 노드(DataLoad/Operator/Merge/Save). Merge 외 노드는 입력 엣지 1개로 강제 (v5.2).
- **버전 정책**: `{major}.{minor}`. major=수동(사용자 등록/실행), minor=automation 예약(미구현).
- **검증 체계**: 정적(`lib/pipeline/pipeline_validator.py`) + DB(`app/services/pipeline_service.py`). 입력 수 제한은 클라이언트 `onConnect`에서 차단.
- **실행 제출/상세**: Celery 태스크 dispatch 후 즉시 202, `ExecutionSubmittedModal` 확인 모달. 이력 행 클릭 → `ExecutionDetailDrawer` (공유 컴포넌트). Config JSON 확인/복사 + JSON → DAG 복원 지원.

---

## 2. 우선순위 TODO (v5.2 액션 아이템)

### 2-1. 노드 추가 SDK화 + 가이드 문서 [1순위]

DataLoadNode / OperatorNode / MergeNode / SaveNode + Manipulator의 구현 인터페이스를 일원화하여 신규 노드 추가를 쉽게 만든다. 완료 후 `docs_for_claude/` 하위에 "새 노드 만드는 법" 가이드 md 작성.

**검토 포인트:**
- 현재 4종 노드는 타입별 별개 컴포넌트 + `nodeDataMap` 개별 타입 → 공통 베이스가 없음
- Manipulator는 `UnitManipulator` ABC + `REQUIRED_PARAMS` + `params_schema` (DB seed) + MANIPULATOR_REGISTRY 등록이 분산되어 있음
- 목표: 한 파일에 노드 정의만 추가하면 팔레트/캔버스/검증/config 변환까지 자동 연결되는 형태

### 2-2. Classification 데이터 입력 [2순위]

현재 전 구성요소가 **Detection only**. Classification 데이터셋 등록/관리/파이프라인 플로우를 신규 설계 + 구현. RAW 등록 위자드, annotation 파서, manipulator 스펙, 샘플 뷰어/EDA 모두 재검토 필요.

### 2-3. 원천 소스 버전업 시 파이프라인 자동 수행 [3순위]

`objective_n_plan_5th.md` §7-2 Automation 시나리오의 실구현. 원천 SOURCE가 `1.0 → 2.0`으로 올라가면 downstream 파이프라인이 사전 등록된 config로 자동 재실행되며 출력 데이터셋의 **minor 버전이 증가** (`1.0 → 1.1`). 연쇄 실행 포함.

**필요 구성:**
- 파이프라인을 "템플릿"으로 저장하는 모델 (현재는 1회성 execution만 존재)
- 원천→downstream 의존 그래프 (DatasetLineage 역방향 탐색)
- `is_automation` 플래그 → `_next_version()`이 minor 증가로 분기

### 2-4. 버전 정책 점검 [4순위, 2-3 진행 중 병행]

현행 `{major}.{minor}` 정책이 실제 운영에서 문제 없는지 재검토. 수동/자동 동시 발생 시 충돌 동작, 삭제된 버전과 재생성 순번 등.

### 2-5. Detection / Attribute Classification 모델 학습 [Step 2]

Docker 컨테이너 기반, config 동적 주입. Step 2(학습 자동화) 진입점. 2-1 & 2-2 완료 이후.

---

## 3. 기존 장기 TODO (보류 / 백로그)

### 백엔드 / Manipulator
- **미구현 manipulator (DB seed만 존재, 코드 없음)**: `change_compression` (AUGMENT), `shuffle_image_ids` (SAMPLE). GUI는 클릭 시 "미구현" 모달 표시 중.
- **신규 manipulator 후보**: IoU 기반 겹치는 annotation 제거 / IoU 기반 마스킹.
- **sample_n_images 배치 위치 검토** — 필터 전/후, merge 전/후에 따라 결과가 달라짐. GUI 권장 위치 안내 또는 검증 경고 여부 결정 필요.

### GUI
- **검증 결과 노드별 하이라이트** — validate API의 `issue_field`를 개별 노드에 매핑하여 시각적 피드백.
- **MergeNode params_schema 기반 폼** — 현재 merge는 params 없이 동작. 향후 확장 대비 (보류 가능).

### 인프라 / 운영
- **YOLO `data.yaml` path 주입** — Step 2 학습 자동화 시 실제 이미지 경로 주입 필요. 현재 `data.yaml`은 데이터셋 루트에 생성되나 path/train/val 키 없음.
- **네이밍 점검** — `_write_data_yaml` 등 general한 함수명 리네이밍 (별도 세션).
- **기존 데이터셋 뷰어/EDA 전수 검증** — 모든 READY 데이터셋에서 샘플 뷰어/EDA 정상 동작 확인 (통일포맷 전환 후 스키마 v2 캐시 재생성 여부).
- **테스트 자동화** — Celery 안정화 이후 integration / regression / e2e 테스트 추가.
- **S3StorageClient** — Step 3 K8S 전환 시 구현.
- **DB seed 정비** — 코드 구현된 12종과 seed 전체 정합성 재확인.

---

## 4. 작업 시 반드시 지킬 원칙 (핸드오프 누적 학습)

### 4-1. 아키텍처 원칙
- **`lib/` → `app/` import 금지.** 파이프라인/Manipulator 순수 로직은 DB/FastAPI 무의존 유지.
- **DB 세션 이중 구조.** FastAPI는 `AsyncSession`(asyncpg), Celery는 `SyncSessionLocal`(psycopg2). 혼용 금지.
- **Celery hot reload 없음.** 코드 변경 시 `docker restart mlplatform-celery` 필수.
- **소프트 삭제.** `deleted_at IS NULL` 필터 누락 금지. 단 `_next_version()`은 삭제 포함 조회로 버전 연속성 보존.

### 4-2. 네이밍 / 코드 스타일
- 한 글자·한 단어 함수/변수명 금지. 풀네임 + 한글 주석 필수 (CLAUDE.md).
- Manipulator 네이밍 패턴: `{동작}_{대상}_{조건}` (예: `filter_keep_images_containing_class_name`).

### 4-3. GUI 패턴
- **노드 컴포넌트는 store 직접 구독.** React Flow의 `node.data` prop은 store 변경 시 갱신 안 됨:
  ```tsx
  const nodeData = usePipelineEditorStore((s) => s.nodeDataMap[id] ?? null)
  ```
- **노드 내부 폼은 `className="nopan nodrag"`만 적용.** `onMouseDown stopPropagation`은 Ant Design Select를 차단하므로 금지.
- **useEffect dependency는 실질 값만.** 객체 참조를 넣으면 store 업데이트 → 리렌더 무한 루프.

### 4-4. 통일포맷 원칙
- 파이프라인 내부는 전부 `category_name: str` 기반. 포맷별 ID는 파서(로드)와 라이터(저장)에서만 처리.
- COCO writer: 표준 80클래스는 `NAME_TO_COCO_ID`, 커스텀은 91번부터 순차. YOLO writer: 알파벳순 0-based.
- `sample_index.json`는 `schema_version=2` (category_name 기반). v1 감지 시 자동 재생성.

### 4-5. RAW 등록 / 파이프라인 실행 흐름
- 둘 다 Celery 비동기. API는 즉시 202 응답 + 상태는 목록/Drawer로 확인.
- 재시도 없음(`max_retries=0`). 에러 시 부분 생성 디렉토리는 `shutil.rmtree`로 정리.
- 파이프라인 큐: `"pipeline"` (prefetch=1, soft 24h / hard 25h). 등록 큐: `"default"`.

---

## 5. 핵심 파일 참조

| 영역 | 경로 |
|------|------|
| 설계서 (현행) | `objective_n_plan_5th.md` |
| 파이프라인 로직 | `backend/lib/pipeline/` |
| Manipulator 구현 | `backend/lib/manipulators/` |
| 파이프라인 API | `backend/app/api/v1/pipelines/router.py` |
| 파이프라인 서비스 | `backend/app/services/pipeline_service.py` |
| Celery 태스크 | `backend/app/tasks/pipeline_tasks.py`, `register_tasks.py` |
| 에디터 페이지 | `frontend/src/pages/PipelineEditorPage.tsx` |
| 에디터 스토어 | `frontend/src/stores/pipelineEditorStore.ts` |
| Graph↔Config 변환 | `frontend/src/utils/pipelineConverter.ts` |
| 실행 상세 Drawer | `frontend/src/components/pipeline/ExecutionDetailDrawer.tsx` |
| 노드 스타일 (공유) | `frontend/src/components/pipeline/nodeStyles.ts` |

---

## 6. 아카이브된 이전 핸드오프

- 001: 데이터셋 등록 오류/UX 개선 (이슈 1~6 + A~E)
- 002: 데이터셋 목록/상세 개선 + 클래스 정보 검증 + 소프트 삭제
- 003: `lib/` 분리 + 포맷 변환 manipulator 구현
- 004: Celery 비동기 파이프라인 실행 + DAG config 개편 + 포트 변경
- 005: merge_datasets + 파이프라인 검증기
- 006: React Flow GUI 에디터 + 누락 이미지 스킵 + processing.log
- 007: RAW 등록 Celery 전환 + ANNOTATION_FILTER/IMAGE_FILTER 분리
- 008: Manipulator 7종 + YOLO 샘플 뷰어 bbox 정규화 + NodePalette 스타일 통합
- 009: remap/rotate/mask 구현 + 이미지 변환 파이프라인 연결
- 010: 통일포맷 마이그레이션 (7 stage 완료)
- 011: 실행 상세 Drawer + 버전 정책 `{major}.{minor}` + 출력 그룹 task_types 자동 설정
- 012: Merge 외 노드 입력 엣지 1개 강제 (v5.2)

원문: `docs_history/handoffs/` 하위.
