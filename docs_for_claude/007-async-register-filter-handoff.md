# 비동기 데이터셋 등록 + filter_final_classes + UI 개선 — 핸드오프

> 브랜치: `feature/data-manipulate-pipeline-gui-detection`
> 작업 기간: 2026-04-07
> 이전 핸드오프: `006-gui-pipeline-editor-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. 데이터셋 등록 Celery 비동기 전환

RAW 데이터셋 등록 시 파일 복사를 Celery 비동기 태스크로 분리. 기존에는 API가 파일 복사 완료까지 동기 대기하여 타임아웃 위험이 있었다.

**변경된 등록 흐름:**

```
[사용자] → 등록 API 호출
    → Dataset(status=PROCESSING) 즉시 DB 생성
    → Celery 태스크 dispatch
    → API 즉시 202 응답
    ↓
[Celery Worker] — register_dataset 태스크
    → 파일 복사 (이미지 폴더 + 어노테이션 + 메타 파일)
    → 클래스 정보 자동 추출 (best-effort)
    → 성공: Dataset READY + image_count/class_info 업데이트
    → 실패: Dataset ERROR + 부분 생성 디렉토리 정리
```

**핵심 파일:**

| 파일 | 변경 내용 |
|------|-----------|
| `backend/app/tasks/register_tasks.py` | **신규** — `register_dataset` Celery 태스크, 동기 DB 세션 사용 |
| `backend/app/services/dataset_service.py` | 동기 파일 복사 제거, Celery dispatch로 변경 |
| `backend/app/api/v1/dataset_groups/router.py` | 202 응답, Celery task_id 포함 |
| `backend/app/tasks/celery_app.py` | `register_tasks` include 추가 |

**프론트엔드 변경:**
- 기존: fire-and-forget + 타임아웃 설정(`VITE_REGISTER_TIMEOUT_MINUTES`)
- 변경: 정상 await (백엔드가 즉시 응답하므로), 안내 모달로 변경
- `VITE_REGISTER_TIMEOUT_MINUTES` 환경변수 제거

### 2. ExecutionStatusModal → ExecutionSubmittedModal 전환

파이프라인 실행 후 polling 모달을 제거하고, "실행 제출 완료" 확인 모달로 변경.

**변경 전:** `ExecutionStatusModal` — 2초 간격 polling으로 실행 상태를 실시간 추적
**변경 후:** `ExecutionSubmittedModal` — 확인 모달만 표시, "데이터셋 목록으로 이동" 또는 "계속 편집" 선택

**제거된 store 필드:** `executionStatus`, `setExecutionStatus` (pipelineEditorStore)
**유지된 store 필드:** `executionId`, `setExecutionId` (모달 open/close 제어에 사용)

**파일:** `frontend/src/components/pipeline/ExecutionStatusModal.tsx` — 내용 전면 교체 (파일명은 유지)

### 3. filter_final_classes manipulator 구현

지정 class 이름의 annotation만 유지하고 나머지를 제거하는 manipulator. 이미지 자체는 삭제하지 않는다.

**파일:** `backend/lib/manipulators/filter_final_classes.py` (신규)

**동작:**
1. `keep_class_names` 파싱 → 유지할 class 이름 set 구성
2. categories에서 이름 매칭하여 유지할 `category_id` set 구성
3. 모든 `image_record.annotations`에서 해당 `category_id`만 유지
4. categories도 유지 대상만 남김
5. annotation이 0개가 된 이미지도 `image_records`에 유지 (빈 이미지)

**params:**
- `keep_class_names`: textarea 타입, 줄바꿈 구분된 class 이름 목록

**MANIPULATOR_REGISTRY에 등록:** 4종째 (format_convert_to_coco, format_convert_to_yolo, merge_datasets, **filter_final_classes**)

### 4. 필터 카테고리 분리 — FILTER / IMAGE_FILTER

기존 FILTER 카테고리를 의미에 따라 두 카테고리로 분리.

| 카테고리 | GUI 표시 | 동작 | 해당 manipulator |
|----------|----------|------|------------------|
| **FILTER** | "Annotation 필터" | annotation만 제거, 이미지 파일 유지 | `filter_final_classes` |
| **IMAGE_FILTER** (신규) | "Image 필터" | 이미지 자체를 유지/제거 | `filter_keep_by_class`, `filter_remove_by_class`, `filter_invalid_class_name` |

**변경 파일:**
- `backend/migrations/versions/002_seed_manipulators.py` — seed 데이터에 IMAGE_FILTER 카테고리 적용
- `frontend/src/components/pipeline/NodePalette.tsx` — `CATEGORY_META`에 IMAGE_FILTER 추가 (빨간색 아이콘)

### 5. NodePalette / OperatorNode UI 개선

**NodePalette:**
- description의 괄호 부분(`(도움말)`)을 Tooltip으로 분리 — 버튼은 짧은 이름만, hover 시 상세 도움말 표시
- 노드 라벨도 괄호 제거한 짧은 이름 사용 (`extractShortLabel()`)

**OperatorNode:**
- store 직접 구독으로 변경 → params 변경이 노드에 실시간 반영
- textarea params는 줄바꿈→쉼표 축약 표시 (예: "person, car, truck")

### 6. 기타 변경

- `format_convert_to_coco` params_schema에서 불필요한 `category_names` 제거
- `format_convert_to_yolo` description을 "COCO → YOLO 포맷 변환"으로 짧게 변경

---

## 신규 생성 파일

| 파일 | 역할 |
|------|------|
| `backend/app/tasks/register_tasks.py` | 데이터셋 등록 Celery 태스크 (동기 DB, 파일 복사 + 클래스 추출) |
| `backend/lib/manipulators/filter_final_classes.py` | FilterFinalClasses — annotation 레벨 class 필터 |

---

## 수정된 기존 파일

### 백엔드

| 파일 | 변경 |
|------|------|
| `app/services/dataset_service.py` | 동기 파일 복사 → Celery dispatch |
| `app/api/v1/dataset_groups/router.py` | 202 즉시 응답 |
| `app/tasks/celery_app.py` | `register_tasks` include |
| `lib/manipulators/__init__.py` | MANIPULATOR_REGISTRY에 `filter_final_classes` 추가 (4종) |
| `migrations/versions/002_seed_manipulators.py` | FILTER/IMAGE_FILTER 카테고리 분리 |
| `lib/manipulators/format_convert.py` | params_schema에서 `category_names` 제거, description 축약 |

### 프론트엔드

| 파일 | 변경 |
|------|------|
| `components/pipeline/ExecutionStatusModal.tsx` | polling → ExecutionSubmittedModal 확인 모달 |
| `components/pipeline/NodePalette.tsx` | IMAGE_FILTER 카테고리, 괄호→Tooltip 분리 |
| `components/pipeline/nodes/OperatorNode.tsx` | store 직접 구독, textarea 축약 표시 |
| `stores/pipelineEditorStore.ts` | `executionStatus`/`setExecutionStatus` 제거 |
| 데이터셋 등록 관련 컴포넌트 | fire-and-forget 제거, 타임아웃 환경변수 제거 |

---

## 다음 세션에서 할 것 (우선순위 순)

### 즉시 필요

1. **MergeNode params_schema 기반 폼** — 현재 merge는 params 없이 동작하지만 향후 확장 대비 (보류 가능)

### 백엔드 확장

2. **추가 Manipulator 구현** (lib/manipulators/ 하위)
   - `remap_class_name` — category name 변경
   - `filter_keep_by_class` / `filter_remove_by_class` — 이미지 레벨 class 필터
   - `filter_invalid_class_name` — regex/blacklist 기반 이미지 제거
   - `sample_n_images` — N장 랜덤 샘플 추출

### GUI 고도화

3. **엣지 연결 규칙 검증** — 현재 아무 노드나 연결 가능, 타입 호환성 체크 필요
4. **검증 결과 노드별 하이라이트** — validate API 결과를 개별 노드에 매핑

---

## 핵심 패턴 — 다음 세션 참고

### Celery 동기 DB 세션 패턴

Celery 태스크는 async loop 없이 동기 환경에서 실행된다. `SyncSessionLocal()`을 사용하며, try/finally로 반드시 세션을 닫는다.

```python
@celery_app.task(bind=True, name="...", queue="default", max_retries=0)
def register_dataset(self, dataset_id: str, ...):
    db = SyncSessionLocal()
    try:
        return _execute_register(db=db, dataset_id=dataset_id, ...)
    finally:
        db.close()
```

### filter_final_classes — annotation 레벨만 처리

이미지는 건드리지 않고 annotation만 필터링한다. annotation이 전부 제거된 이미지도 `image_records`에 유지한다 (빈 이미지로 남김). IMAGE_FILTER와의 핵심 차이점.

### NodePalette Tooltip 패턴

description이 "버튼 텍스트 (도움말)" 패턴이면 괄호 안 내용을 Tooltip으로 분리:

```tsx
const parenMatch = desc.match(/^(.+?)\s*\((.+)\)\s*$/)
const buttonLabel = parenMatch ? parenMatch[1] : desc
const tooltipText = parenMatch ? parenMatch[2] : null
```
