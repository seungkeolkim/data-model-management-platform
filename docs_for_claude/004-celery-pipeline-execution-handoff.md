# Celery 비동기 파이프라인 실행 — 핸드오프

> 브랜치: `feature/data_transform_manipulator`
> 작업 기간: 2026-04-03
> 이전 핸드오프: `003-pipeline-manipulator-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. PipelineConfig DAG 기반 구조 개편

기존 선형 파이프라인 → Airflow 스타일 DAG으로 개편.

```yaml
pipeline:
  name: "coco8_conv_coco"
  output:
    dataset_type: SOURCE
    annotation_format: COCO
    split: TRAIN            # 단수 (리스트 아님)
  tasks:
    convert_to_coco:
      operator: format_convert_to_coco
      inputs: ["source:5c9e1a85-..."]  # "source:<dataset_id>" 또는 태스크명
      params: {}
```

**핵심 파일:** `lib/pipeline/config.py`
- `PipelineConfig`, `TaskConfig`, `OutputConfig` (Pydantic)
- `topological_order()` — Kahn's algorithm
- `get_terminal_task_name()` — sink 노드 자동 탐색
- `model_validator`로 순환 참조, 잘못된 참조 검증
- `load_pipeline_config_from_yaml()` — YAML 파싱

**테스트:** `tests/test_pipeline_config.py` (28개 테스트)

### 2. 파일명·클래스명·함수명 일괄 리네이밍

003 핸드오프 문서의 파일명이 변경되었음에 주의:

| 이전 | 이후 |
|------|------|
| `executor.py` | `dag_executor.py` |
| `image_executor.py` | `image_materializer.py` |
| `manipulator.py` | `manipulator_base.py` |
| `models.py` | `pipeline_data_models.py` |
| `class_mapping.py` | `coco_yolo_class_mapping.py` |
| `PipelineExecutor` | `PipelineDagExecutor` |
| `ImageExecutor` | `ImageMaterializer` |
| `.execute()` | `.materialize()` |
| `get_images_path()` | `get_images_dir()` |

### 3. Celery 비동기 파이프라인 실행

**전체 흐름:**
```
POST /api/v1/pipelines/execute  →  202 { execution_id, celery_task_id }
  └→ DB: DatasetGroup(찾기/생성) + Dataset(PENDING) + PipelineExecution(PENDING)
  └→ Celery: run_pipeline.delay(execution_id, config_dict)

[Worker]
  → PipelineExecution(RUNNING) → Dataset(PROCESSING)
  → PipelineDagExecutor.run(config, target_version)
  → 성공: Dataset(READY) + PipelineExecution(DONE) + DatasetLineage 생성 + metadata 채움
  → 실패: Dataset(ERROR) + PipelineExecution(FAILED) + error_message

GET /api/v1/pipelines/{id}/status  →  { status, current_stage, processed_count, ... }
```

**수정/생성 파일:**

| 파일 | 변경 |
|------|------|
| `app/core/database.py` | sync_engine + SyncSessionLocal 추가 (Celery용) |
| `app/core/config.py` | broker URL `sqla+postgresql://` 수정, 포트 기본값 변경 |
| `app/services/pipeline_service.py` | **신규** — submit_pipeline, get_execution_status, list_executions |
| `app/tasks/pipeline_tasks.py` | **구현** — _DbAwareDagExecutor + run_pipeline 태스크 |
| `app/api/v1/pipelines/router.py` | **구현** — POST /execute(202), GET /{id}/status, GET / |
| `app/schemas/pipeline.py` | PipelineListResponse 추가 |
| `lib/pipeline/dag_executor.py` | `run()`에 `target_version` 파라미터 추가 |
| `docker-compose.yml` | celery-worker 서비스 활성화 |

**Celery 설정:**
- Broker: PostgreSQL (`sqla+postgresql://`) — Redis 미사용
- Result backend: PostgreSQL (`db+postgresql://`)
- Worker: backend과 동일 이미지, `backend_venv` 볼륨 공유
- Worker 재시작: `docker restart mlplatform-celery` (hot reload 없음)

**DB 세션 이중 구조:**
- FastAPI: `AsyncSession` (asyncpg) — `get_db()`
- Celery: `SyncSessionLocal` (psycopg2) — 직접 생성/관리

### 4. 포트 변경

| 서비스 | 이전 | 이후 | 환경변수 |
|--------|------|------|----------|
| nginx | 80 | **18080** | `NGINX_PORT` |
| backend | 8000 | **18000** | `APP_PORT` |
| postgres (호스트) | 5432 | **15432** | `POSTGRES_EXTERNAL_PORT` |
| frontend | 5173 | **15173** | `FRONTEND_PORT` |

주의: `POSTGRES_PORT`(5432)는 Docker 컨테이너 **내부** 통신 포트로 변경 불가. 호스트 매핑은 `POSTGRES_EXTERNAL_PORT`.

### 5. 기타
- 사이드바 로고 클릭 → 메인 페이지 이동 (`AppLayout.tsx`)
- CLI 파이프라인 실행기: `run_pipeline_yaml.py` + `pipelines/coco8_conv_coco.yaml`

---

## 검증 완료 사항

- 124 unit tests 전부 통과
- API end-to-end: POST → Celery 실행 → DONE 확인
- 버전 자동 증가: v1.0.0 → v1.0.1 → v1.0.2
- DatasetGroup 자동 생성/재사용
- DatasetLineage 엣지 자동 생성
- Dataset metadata(class_info) 자동 채움
- 전 서비스 새 포트에서 정상 동작

---

## 남은 작업

### Phase 2 잔여 (데이터셋 파이프라인)

| 항목 | 우선순위 | 난이도 | 비고 |
|------|----------|--------|------|
| **추가 manipulator 구현** | 높음 | 중 | remap_class_name, filter_image_by_class, filter_annotation_by_class, sample_n_images, merge_datasets |
| **GUI 파이프라인 위자드** | 높음 | 높음 | 블록 다이어그램 → YAML 생성 → execute API 호출 |
| **파이프라인 실행 이력 UI** | 중간 | 낮음 | GET /pipelines 목록 + 상태 polling |
| **진행률 업데이트** | 낮음 | 중 | dag_executor에 progress callback 추가 필요 (lib/ 수정) |
| **nginx 포트 80 문제 조사** | 낮음 | - | Docker proxy 간섭, 18080에서는 정상 동작 |

### Phase 2-a (EDA 자동화)
- `app/tasks/eda_tasks.py` skeleton만 존재
- 파이프라인 완료 후 EDA 태스크 자동 체이닝 가능

### Phase 2-b (샘플 뷰어 + 리니지 시각화)
- DatasetLineage 데이터는 이미 생성됨
- React Flow DAG 시각화 예정

### 테스트 자동화 (메모리에 TODO 저장됨)
- Integration test: DB 연동 파이프라인 end-to-end
- Regression test: known dataset 변환 결과 고정 assert
- E2E test: API → Celery → DB 상태 변경 (docker-compose 기반)

---

## 주의사항

1. **현재 파이프라인은 Detection 타입 데이터 한정.** attribute/zero-shot 등은 미설계.
2. **Celery worker는 hot reload 안 됨.** 코드 변경 시 `docker restart mlplatform-celery` 필수.
3. **`lib/` → `app/` import 금지** 원칙 유지.
4. **dag_executor.py의 `target_version` 파라미터:** 서비스 레이어에서 버전을 사전 생성하여 전달. CLI에서는 기본값 `"v1.0.0"` 사용.

---

## 커밋 히스토리 (이번 세션)

```
dd89767 fix: 사이드바 로고 클릭 시 메인 페이지(/)로 이동
614451a chore: 전체 포트를 비충돌 대역으로 변경 (15xxx~18xxx)
d19b4bd fix: nginx 포트를 80 → 8080으로 변경 (포트 충돌 회피)
8dd052b feat: Celery 비동기 파이프라인 실행 + API 엔드포인트 구현
09d6a70 refactor: 파이프라인 모듈 파일명·클래스명·함수명 일괄 리네이밍
3ecf400 refactor: PipelineConfig를 DAG 기반 구조로 개편
```
