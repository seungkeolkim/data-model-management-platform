# 엣지 입력 수 제한 (Merge 외 노드 단일 입력 강제) — 핸드오프

> 브랜치: `feature/improve-dag-validation` → main (merge 완료)
> 작업 기간: 2026-04-13
> 이전 핸드오프: `011-execution-detail-version-policy-handoff.md`

---

## 이번 세션에서 완료한 것

### 1. 엣지 입력 수 제한 (Merge 외 노드 단일 입력 강제)

GUI 파이프라인 에디터에서 Merge 노드를 제외한 모든 노드(DataLoadNode 출력 대상, OperatorNode, SaveNode)에 **두 번째 입력 엣지 연결 시도를 차단**.

**변경 파일:**

| 파일 | 변경 |
|------|------|
| `frontend/src/pages/PipelineEditorPage.tsx` | `onConnect` 핸들러에서 대상 노드 타입 확인 후 Merge가 아니면 기존 입력 엣지 존재 여부 체크 → 있으면 `Modal.warning`으로 안내하고 엣지 생성 차단 |

**구현 요지:**

```typescript
const onConnect: OnConnect = useCallback(
  (connection) => {
    const targetNodeId = connection.target
    if (!targetNodeId) return

    const targetData = nodeDataMap[targetNodeId]
    const isMergeNode = targetData?.type === 'merge'

    if (!isMergeNode) {
      const existingInputEdge = edges.find((edge) => edge.target === targetNodeId)
      if (existingInputEdge) {
        Modal.warning({
          title: '연결 불가',
          content: 'Merge 노드를 제외한 노드는 입력을 하나만 받을 수 있습니다. 여러 입력을 합치려면 Merge 노드를 사용하세요.',
        })
        return
      }
    }

    setEdges((eds) => addEdge({ ...connection, animated: true }, eds))
  },
  [setEdges, edges, nodeDataMap],
)
```

- Merge 노드는 기존대로 다중 입력 허용 (N개 동적 핸들)
- 이외 노드는 첫 번째 엣지는 정상 연결, 두 번째부터 차단

---

## 검토했지만 착수하지 않은 것

### DAG 정합성 검증 전반 — 현 시점에서 추가 구현 불필요로 결론

011 핸드오프에서 "다음 세션 작업"으로 제시했던 DAG 정합성 검증 항목들을 재검토한 결과:

1. **DB → LP → PP → Execution 같은 단계 도입**
   - DB 쿼리 엔진의 발상이지만, 현재 PipelineConfig JSON이 이미 실행 직전 형태의 계획(PP에 해당)
   - 옵티마이저가 없으므로 LP/PP 분리 불필요
   - Query/LP/PP 레이어 추가 구현 안 함

2. **타입 체크 (중간 노드 output 타입 전파)**
   - 통일포맷 전환 이후 annotation_format 구분이 사라졌고, dataset_type은 SaveNode에서만 사용
   - 중간 노드 타입 전파 실익이 적다고 판단 → 불필요

3. **엣지 연결 규칙 검증**
   - 타입 호환성 체크 대신 **입력 수 제한**으로 단순화 → 위 항목으로 완료

4. **사용자 custom 포맷 파서 플러그인 SDK**
   - 외부 개발자용 플러그인 아키텍처 논의 진행했으나 **구현하지 않기로 결정**
   - 현 시점에 VisDrone 등 커스텀 포맷은 사내 코드로 직접 `lib/pipeline/io/`에 추가하는 방식 유지
   - 향후 정말 필요해지면 그때 설계

### 현재 검증 체계 (유지)

**정적 검증 (`lib/pipeline/pipeline_validator.py`)**: INVALID_DATASET_TYPE, RAW_NOT_ALLOWED_AS_OUTPUT, INVALID_SPLIT, INVALID_ANNOTATION_FORMAT, UNKNOWN_OPERATOR, MERGE_MIN_INPUTS, MULTI_INPUT_WITHOUT_MERGE

**DB 검증 (`app/services/pipeline_service.py`)**: SOURCE_DATASET_NOT_FOUND, SOURCE_DATASET_GROUP_DELETED, SOURCE_DATASET_NOT_READY, SOURCE_DATASET_NO_ANNOTATIONS

---

## 커밋 이력

| 커밋 | 내용 |
|------|------|
| `87c8552` | feat: Merge 외 노드에 다중 입력 엣지 연결 차단 + 경고 모달 |

`feature/improve-dag-validation` 브랜치에서 작업 후 main으로 fast-forward merge + push 완료.

---

## 다음 세션 작업 후보

### 액션 아이템 TODO (신규, 우선순위 순)

1. **노드 추가 기능 — SDK화**
   - 1-1. 모든 노드(DataLoadNode / OperatorNode / MergeNode / SaveNode, 그리고 Manipulator)의 구현 인터페이스 일원화 → 신규 노드 추가를 쉽게
   - 1-2. SDK화 이후 "노드 추가 방법" 가이드 md 문서 생성 (`docs_for_claude/` 하위 또는 별도 developer docs)

2. **Classification 데이터 입력** — 현재 Detection only 스코프. Classification 전용 데이터셋 등록/관리 플로우 설계 및 구현

3. **원천 소스 버전업 시 파이프라인 자동 수행** — 5차 설계서 §7-2의 Automation 시나리오. 원천 SOURCE가 `1.0 → 2.0`으로 올라가면 downstream 파이프라인이 사전 등록된 config로 자동 재실행 + 출력 minor 증가 (`1.0 → 1.1`)

4. **버전 정책 점검** — 현행 `{major}.{minor}` 정책이 실제 운영에서 문제 없는지 재검토 (수동/자동 구분, 충돌 발생 시 동작 등)

5. **(1 & 2 완료 후, 약간 먼 미래) Detection, Attribute Classification 모델 학습** — Docker 컨테이너 기반, config 동적 주입 방식. Step 2(학습 자동화) 진입점

### 기존 Phase 2 잔여 / 장기 TODO

- **검증 결과 노드별 하이라이트** — validate API의 `issue_field`를 개별 노드에 매핑
- **미구현 manipulator** — `change_compression`(AUGMENT), `shuffle_image_ids`(SAMPLE)
- **기존 데이터셋 뷰어 전수 검증** — 모든 READY 데이터셋에서 샘플뷰어/EDA 정상 동작 확인
- **네이밍 점검** — `_write_data_yaml` 등 general한 함수명 리네이밍
- **YOLO yaml path 주입** — Step 2 학습 자동화 시점

---

## 핵심 파일 변경 맵 (이번 세션)

### 수정된 파일

| 파일 | 주요 변경 |
|------|-----------|
| `frontend/src/pages/PipelineEditorPage.tsx` | `onConnect` — 입력 수 제한 검증 로직 추가 |
| `objective_n_plan_5th.md` | v5.2로 버전업, 엣지 입력 수 제한 규칙 추가, 장기 TODO의 DAG 정합성 항목 재정리 |

### 신규 파일

| 파일 | 역할 |
|------|------|
| `docs_for_claude/012-edge-input-limit-handoff.md` | 이 핸드오프 문서 |
