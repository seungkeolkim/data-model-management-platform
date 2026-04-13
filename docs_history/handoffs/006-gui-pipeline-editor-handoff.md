# GUI 파이프라인 에디터 + 파이프라인 실행 안정화 — 핸드오프

> 브랜치: `feature/data-manipulate-pipeline-gui-detection`
> 작업 기간: 2026-04-06
> 이전 핸드오프: `005-merge-and-validation-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. ComfyUI 스타일 노드 기반 파이프라인 에디터

React Flow 기반 전체화면 노드 에디터. 사용자가 시각적으로 DAG 파이프라인을 구성하고 검증/실행할 수 있다.

**핵심 기술 결정:**
- `@xyflow/react` v12.6+ 사용
- Zustand store(`nodeDataMap`)가 노드 도메인 데이터의 단일 진실 소스
- React Flow는 시각 상태(위치, 연결)만 관리
- 노드 컴포넌트는 `usePipelineEditorStore((s) => s.nodeDataMap[id])`로 직접 구독 (React Flow의 `node.data` prop은 store 변경 시 갱신 안 됨)
- 노드 내부 폼 요소에 `className="nopan nodrag"` 적용 (React Flow 공식 방법, `onMouseDown stopPropagation`은 Ant Design Select 차단하므로 금지)

**4종 커스텀 노드:**

| 노드 | 입력 | 출력 | 역할 |
|------|------|------|------|
| DataLoadNode | 없음 | 1 | 3단계 캐스케이드 선택 (그룹→Split→버전) |
| OperatorNode | 1 | 1 | 범용 operator (카테고리별 색상/아이콘) |
| MergeNode | N(동적) | 1 | merge_datasets, 연결된 엣지 수에 따라 핸들 자동 증가 |
| SaveNode | 1 | 없음 | 출력 설정 (name, dataset_type, split, format) 인라인 폼 |

**Graph → PipelineConfig 변환:**
- `utils/pipelineConverter.ts` — `graphToPipelineConfig()` + `validateGraphStructure()`
- DataLoadNode → `source:<datasetId>` (task가 아님)
- OperatorNode/MergeNode → `task_<nodeId>`
- SaveNode → `config.name` + `config.output`
- 클라이언트 사전 검증: 사이클 감지, SaveNode 유무, 연결 완전성

**페이지 구조:**
- `/pipelines` — 실행 이력 페이지 (AppLayout 내부, 사이드바 있음)
  - 태스크 타입 선택 모달 (DETECTION만 활성, 나머지 "준비 중")
- `/pipelines/editor?taskType=DETECTION` — 전체화면 에디터 (AppLayout 밖)

### 2. DataLoadNode 3단계 캐스케이드 선택

DataLoadNode 안에서 데이터셋을 3단계로 선택:
1. **데이터셋 그룹** — DETECTION 태스크 타입 + READY 데이터셋 있는 그룹만 표시
2. **Split** — 선택된 그룹의 READY 데이터셋에서 존재하는 split 추출
3. **버전** — 선택된 그룹+split의 READY 데이터셋 버전 목록

**규칙:** 상위 항목 변경 시 하위 항목 자동 초기화. 순수 드롭다운 (showSearch 없음).

**속성 패널 연동:** 3단계 선택 완료 시 우측 PropertiesPanel에 데이터 타입, 어노테이션 포맷, 이미지 수, 클래스 수, 클래스 매핑 테이블(scrollable) 표시.

### 3. 누락 이미지 스킵 처리 (Phase B 안정화)

annotation에는 존재하지만 실제 파일이 없는 이미지를 파이프라인 중단 대신 경고와 함께 건너뛴다.

**변경 파일:**
- `lib/pipeline/image_materializer.py` — `MaterializeResult` dataclass 추가, `materialize()` 반환 타입 변경, `_materialize_single_image()`이 `src_path.exists()` 선확인 후 스킵
- `lib/pipeline/dag_executor.py` — Phase B 후 스킵된 이미지를 `output_meta.image_records`에서 제거, annotation도 필터링된 상태로 작성
- `PipelineResult` — `skipped_image_count`, `skipped_image_files` 필드 추가
- `app/tasks/pipeline_tasks.py` — Celery 태스크 결과에 `skipped_image_count` 포함

**검증 결과:** coco128(128장, 2장 누락) → 126장 정상 출력 확인.

### 4. ExecutionStatusModal 무한 루프 수정

**원인:** `setExecutionStatus(statusData)`를 렌더링 본문에서 직접 호출 → store 업데이트 → 리렌더 반복.
**수정:** `useEffect`로 감싸고, dependency를 `statusData` 객체 참조가 아닌 실질 값(`status`, `processed_count`)으로 한정.

### 5. processing.log — 파이프라인 실행 로그 파일

파이프라인 실행 전 과정을 출력 디렉토리에 `processing.log`로 영구 보관.

**구조:**
```
========================================================================
  파이프라인 실행 로그 — {config.name}
  실행 시각: 2026-04-06 07:32:56 UTC
========================================================================

[출력 설정]
[DAG 태스크]
[실행 결과 요약]
[스킵된 이미지 목록]

========================================================================
  상세 실행 로그
========================================================================
(lib 네임스페이스 전체 로그 — manipulator, materializer 등 포함)
```

**구현:** `_ProcessingLogBufferHandler`(logging.Handler 서브클래스)로 `lib` 네임스페이스 로그를 메모리 버퍼링, 실행 완료 후 파일 작성. try/finally로 핸들러 정리 보장.

### 6. COCO 포맷 merge 시 공식 비순차 category_id 보존

**문제:** merge_datasets가 카테고리 ID를 0부터 순차 재매핑하여 COCO 공식 ID 체계(1~90, 비순차) 파괴.

**수정:**
- `merge_datasets.py` — `_build_unified_categories()`를 포맷별 분기:
  - COCO: `_build_unified_categories_preserve_ids()` — 첫 등장 소스의 원본 ID 보존, ID 충돌 시에만 91번부터 할당
  - YOLO: `_build_unified_categories_sequential()` — 기존대로 0-based 순차
- `dag_executor.py` — `_merge_metas()`에도 동일 로직 적용

### 7. YOLO data.yaml 위치 수정 — annotations/ → 데이터셋 루트

**문제:** `data.yaml`이 `annotations/` 안에 있으면 `ls | wc`로 라벨 파일 수를 셀 때 +1 오차, 파싱 혼선 가능.

**수정:**
- `write_yolo_dir()` — 순수 라벨 `.txt`만 생성 (classes.txt, data.yaml 생성 제거)
- `dag_executor.py` — `data.yaml`을 데이터셋 루트에 생성
- `storage.py` — `copy_annotation_meta_file()` 대상을 데이터셋 루트로 변경
- `dataset_service.py` — 메타 파일 경로 해석도 데이터셋 루트 기준

**결과 디렉토리 구조:**
```
source/coco136/train/v1.0.0/
├── data.yaml          ← 데이터셋 루트
├── processing.log
├── images/
│   └── *.jpg
└── annotations/
    └── *.txt          ← 순수 라벨 파일만 (또는 instances.json)
```

---

## 신규 생성 파일

### 프론트엔드

| 파일 | 역할 |
|------|------|
| `types/pipeline.ts` | 파이프라인 에디터 TypeScript 타입 전체 |
| `api/pipeline.ts` | 파이프라인/manipulator/datasets API 함수 |
| `stores/pipelineEditorStore.ts` | Zustand 에디터 상태 (nodeDataMap 중심) |
| `utils/pipelineConverter.ts` | graph↔PipelineConfig 변환 + 클라이언트 사전 검증 |
| `pages/PipelineEditorPage.tsx` | 전체화면 에디터 (React Flow 캔버스) |
| `pages/PipelineHistoryPage.tsx` | 실행 이력 + 태스크 타입 선택 모달 |
| `components/pipeline/nodes/DataLoadNode.tsx` | 3단계 캐스케이드 선택 노드 |
| `components/pipeline/nodes/OperatorNode.tsx` | 범용 operator 노드 |
| `components/pipeline/nodes/MergeNode.tsx` | 다중 입력 merge 노드 |
| `components/pipeline/nodes/SaveNode.tsx` | 출력 설정 싱크 노드 |
| `components/pipeline/NodePalette.tsx` | 좌측 노드 팔레트 (API 동적 로드) |
| `components/pipeline/EditorToolbar.tsx` | 상단 툴바 |
| `components/pipeline/PropertiesPanel.tsx` | 우측 속성 패널 |
| `components/pipeline/DynamicParamForm.tsx` | params_schema 기반 동적 폼 (7 타입) |
| `components/pipeline/ExecutionStatusModal.tsx` | 실행 상태 polling 모달 |
| `components/pipeline/PipelineJsonPreview.tsx` | JSON 프리뷰 디버그 패널 |

### 백엔드

| 파일 | 변경 내용 |
|------|-----------|
| `lib/pipeline/image_materializer.py` | `MaterializeResult` 추가, 누락 이미지 스킵 |
| `lib/pipeline/dag_executor.py` | processing.log, COCO ID 보존, data.yaml 루트 배치 |
| `lib/manipulators/merge_datasets.py` | COCO 포맷 원본 ID 보존 |
| `lib/pipeline/io/yolo_io.py` | write_yolo_dir에서 classes.txt/data.yaml 제거 |
| `app/core/storage.py` | copy_annotation_meta_file → 데이터셋 루트 |
| `app/services/dataset_service.py` | 메타 파일 경로 해석 루트 기준 |
| `app/tasks/pipeline_tasks.py` | skipped_image_count 결과 포함 |

### 수정된 기존 파일

| 파일 | 변경 |
|------|------|
| `frontend/src/App.tsx` | 라우트 추가: `/pipelines/editor`, `/pipelines` |
| `frontend/src/components/common/AppLayout.tsx` | 사이드바 "데이터 변형" 메뉴 |
| `frontend/package.json` | `@xyflow/react` 의존성 |

---

## 검증 완료된 파이프라인 시나리오

| 시나리오 | 결과 |
|----------|------|
| coco128(YOLO) → format_convert_to_coco → Save | 126장 (2장 스킵), COCO 출력 |
| coco128(YOLO) + coco4 → 각각 COCO 변환 → merge → Save | 130장 (2장 스킵), COCO 출력 |
| coco_val → format_convert_to_yolo → Save | YOLO 출력, data.yaml 루트 배치 확인 |

---

## 다음 세션에서 할 것 (우선순위 순)

### 즉시 필요

1. **DB 초기화 + 데이터 재등록** — data.yaml 위치 변경으로 기존 데이터 호환 안 됨
2. **실행 완료 모달에 skipped 정보 표시** — 현재 GUI에서 skipped 수를 확인할 수 없음
3. **MergeNode params_schema 기반 폼** — 현재 merge는 params 없이 동작하지만 향후 확장 대비

### 백엔드 확장

4. **추가 Manipulator 구현** — remap_class_name, filter_keep/remove_by_class, sample_n_images
5. **DB seed 정비** — manipulators 테이블에 신규 manipulator seed + params_schema

### GUI 고도화

6. **엣지 연결 규칙 검증** — 현재 아무 노드나 연결 가능, 타입 호환성 체크 필요
7. **노드 삭제 기능** — 현재 캔버스에서 노드 삭제 미구현
8. **검증 결과 노드별 하이라이트** — validate API 결과를 개별 노드에 매핑

---

## 핵심 패턴 — 다음 세션 참고

### React Flow + Zustand 상태 동기화 패턴

```tsx
// 노드 컴포넌트에서 반드시 store 직접 구독 (node.data prop 사용 금지)
const nodeData = usePipelineEditorStore(
  (s) => (s.nodeDataMap[id] as DataLoadNodeData) ?? null,
)
```

### 노드 내부 폼 이벤트 방지 패턴

```tsx
// 폼 영역에 className만 적용 (onMouseDown stopPropagation 금지)
<div className="nopan nodrag" style={{ padding: '8px 12px' }}>
  <Select ... />
  <Input ... />
</div>
```

### useEffect 내 store 동기화 (무한 루프 방지)

```tsx
// 객체 참조가 아닌 실질 값만 dependency에 포함
const statusValue = statusData?.status
const processedCount = statusData?.processed_count
useEffect(() => {
  if (statusData) setExecutionStatus(statusData)
}, [statusValue, processedCount, setExecutionStatus])
```
