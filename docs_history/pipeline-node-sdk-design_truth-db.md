# 파이프라인 노드 SDK화 — 설계안 (DB-as-truth 보정판)

> 작성: 2026-04-13
> 브랜치: `feature/pipeline-dag-node-sdk`
> 이전 버전: `pipeline-node-sdk-design_truth-code.md` (코드를 진실 원천으로 삼았던 초기 제안 — 사용자 피드백으로 철회)
> 목적: 6차 설계서 §7-1 액션 아이템 1번 (노드 추가 SDK화) + 1-a (가이드 문서) 구현 준비
> 범위: 분석(1) + 설계(2) + 결정·리스크(3). 실제 구현(3단계)은 미착수.

## 설계 전제 (사용자 확정)

- **manipulator 메타의 진실 원천은 DB**. admin이 `psql` / 관리 GUI로 상태 파악 가능해야 함. 코드는 실행 로직만 담당.
- 아직 운영 이전 단계. **기존 파이프라인 이력 / DB는 언제든 초기화 가능** — 하위 호환 장치는 최소화.
- 코드↔DB 정합성 도구(sync_to_db, alias 등)는 도입하지 않음.
- 다만 "앞으로도 이런 변경작업이 없다는 보장은 없다" → **Placeholder 노드 + DAG schema_version** 도입으로 미래 변경 완충.

---

## 1. 현황 분석 — 새 노드 추가 시 수정 파일

### 1-A. 새 Manipulator 추가

**백엔드**
1. `backend/lib/manipulators/<name>.py` — `UnitManipulator` 상속 구현 (`transform_annotation`, 필요 시 `build_image_manipulation`)
2. `backend/lib/manipulators/__init__.py` — `MANIPULATOR_REGISTRY` 딕셔너리에 수동 등록
3. `backend/migrations/versions/NNN_seed_<name>.py` — DB seed 마이그레이션 (`params_schema`, `compatible_task_types`, `description` 등)

**프론트엔드**
- 원칙적으로 수정 없음 (API가 메타 반환 → `NodePalette` / `OperatorNode` / `DynamicParamForm` 자동 반응)
- 고유 이모지: `nodeStyles.ts#MANIPULATOR_EMOJI`
- 새 카테고리: `nodeStyles.ts#CATEGORY_STYLE`
- 새 params UI 타입: `DynamicParamForm` 확장

**책임 분리 원칙**: 코드(1)는 "실행", DB(3)는 "메타". 둘은 **동일 `name`으로 느슨히 연결**된 두 진실이며 중복 아님. 각자의 역할이 다르다.

### 1-B. 새 특수 노드 타입 추가 (비-operator, 예: Split / TrainOutput)

**수정 파일 9개 이상**:
1. `types/pipeline.ts` — `<X>NodeData` + `PipelineNodeData` union 확장
2. `components/pipeline/nodes/<X>Node.tsx` — 컴포넌트 신규 (헤더/Handle/검증 Tag/store 구독 반복 작성)
3. `components/pipeline/nodeStyles.ts` — `SPECIAL_NODE_STYLE` 항목 추가
4. `pages/PipelineEditorPage.tsx` — `nodeTypes` 매핑 + `handleAddNode` 분기
5. `components/pipeline/NodePalette.tsx` — 팔레트 버튼 하드코딩 + `createNodeData` 팩토리
6. `utils/pipelineConverter.ts` — `graphToPipelineConfig` / `pipelineConfigToGraph` / `validateGraphStructure` 양방향 분기
7. `stores/pipelineEditorStore.ts` — `updateNodeParams` type-guard 분기 확장
8. `components/pipeline/PropertiesPanel.tsx` — 선택 노드 type별 분기
9. `stores/…#applyValidationToNodes` — issue.field → 노드 매핑 규칙 추가

### 1-C. 결합 문제의 본질
- 노드 타입 분기가 9개 파일에 산재 — "노드가 자기 자신에 대한 지식을 갖지 않음"
- React Flow 상용구(헤더/Handle/border/검증 Tag/store 구독)가 노드마다 재작성
- config ↔ graph 변환기가 노드 타입 지식을 하드코딩 → 노드 증가 시 선형 팽창

---

## 2. SDK 설계안

### 2-1. 백엔드 — 스코프 축소 (자동 발견만)

**manipulator 메타는 DB에 유지**. Python 클래스는 실행 로직 + `name`만. `sync_manipulators_to_db()` 도입하지 않음.

**유일한 개선점**: `MANIPULATOR_REGISTRY` 자동 발견.
- 현재: `__init__.py`에서 모든 클래스를 수동 import + dict 등록
- 개선: 패키지 walk (`pkgutil.iter_modules`) + 데코레이터 또는 `__init_subclass__` 훅으로 자동 수집
- 새 파일 놓으면 자동 등록. `__init__.py` 수정 불요.

**결과**: 백엔드 수정 지점 3곳 → **2곳** (클래스 + seed migration). 두 파일은 **역할이 다르므로 남는 것이 정상** — 실행 로직과 메타 데이터는 별개의 관심사.

### 2-2. 프론트엔드 — NodeDefinition 중심 아키텍처

노드의 모든 관심사를 한 객체로 통합:

```typescript
export interface NodeDefinition<K extends keyof NodeDataByKind> {
  kind: K                                           // React Flow 노드 타입 키
  palette: {
    section: 'basic' | 'manipulator'
    label: string
    description?: string
    color: string
    emoji: string
    disabledRule?: (ctx) => { disabled: boolean; reason?: string }
  }
  handles: { inputs: { min: number; max: number | 'infinity' }; outputs: number }
  createDefaultData(ctx: CreateContext): NodeDataByKind[K]
  NodeComponent: React.ComponentType<NodeProps>
  PropertiesComponent?: React.ComponentType<{ nodeId: string; data: NodeDataByKind[K] }>
  validate?(data: NodeDataByKind[K], ctx: GraphContext): ClientValidationError[]
  toConfigContribution(data: NodeDataByKind[K], ctx: ConvertContext): ConfigContribution
  matchFromConfig?(config: PipelineConfig): RestoredContribution<NodeDataByKind[K]>[]
  matchIssueField?(issueField: string, data: NodeDataByKind[K]): boolean
}
```

**타입 안전 테이블 (3-4 결정)**:
```typescript
interface NodeDataByKind {
  dataLoad: DataLoadNodeData
  operator: OperatorNodeData
  merge: MergeNodeData
  save: SaveNodeData
  placeholder: PlaceholderNodeData   // 3-5 placeholder 추가
}
```

**Registry + 런타임 확장 (3-2 결정)**:
- 특수 노드는 빌드 타임 등록: `registerNodeDefinition(dataLoadDef)` 등
- Operator 계열은 `kind='operator'` **하나로 통합**. manipulator API 응답이 와도 새 kind 만들지 않음. `OperatorNodeData.operator` 필드로 다형성 표현.
- React Flow `nodeTypes`는 빌드 타임 5개 (dataLoad/operator/merge/save/placeholder) **고정**

**역변환 계약 (3-3 결정)**:
```typescript
interface RestoredContribution<TData> {
  nodeId: string
  data: TData
  ownedTaskKeys: string[]            // 이 노드가 복원 시 점유한 tasks[key]
  ownedSourceDatasetIds?: string[]   // DataLoad 전용 (source:<id> 문자열)
}
```

엣지 생성기는 모든 contribution의 ownership 맵을 뒤집어 `taskKey → nodeId` / `datasetId → nodeId` 인덱스를 만들고, 각 task의 `inputs`를 해석하여 엣지 복원. 헬퍼 세 개 제공: `configMatchers.singleton` / `perTask` / `sourceString`.

**SDK 상용구 헬퍼**
- `<NodeShell header color issues handles>` — 헤더/border/검증 Tag/Handle 공통
- `useNodeData<K>(nodeId)` — store 직접 구독 + 타입 좁힘
- `buildNodeTypesFromRegistry()` — React Flow `nodeTypes` 자동 생성
- `declareOperatorFromManipulator(meta)` — API 메타 → OperatorNodeData 생성 팩토리 (단일 kind='operator' 정의 재사용)

**분기가 있던 모든 지점이 registry 순회로 전환**
- `PipelineEditorPage` — `nodeTypes = buildNodeTypesFromRegistry()`
- `NodePalette` — registry 순회 + operator API 응답 자동 확장
- `graphToPipelineConfig` — 각 노드의 `toConfigContribution()` 수집
- `pipelineConfigToGraph` — 각 definition의 `matchFromConfig()` 파이프 실행
- `applyValidationToNodes` — issue마다 registry 순회 + `matchIssueField()`
- `PropertiesPanel` — 선택 노드의 `PropertiesComponent`만 렌더

### 2-3. DAG schema 버저닝 + Placeholder 노드 (3-5 결정)

**schema_version 필드**
- `PipelineConfig.schema_version: int = 1` 추가
- Config 생성 시 현재 SDK가 기입
- 로드 시 버전 체크 → 상위 버전이면 "이 config는 더 최신 버전에서 만들어졌습니다" 경고
- 하위 버전 migrator는 **지금 작성하지 않음** (YAGNI). 필드만 심어 둠
- 버전 필드 없는 config는 "v0" 취급, best-effort 복원

**Placeholder 노드** (`kind='placeholder'`)
- `matchFromConfig` 시 registry(= DB)에 없는 operator 발견 → Placeholder 노드로 복원
- 빨간 테두리, 본문: `⚠️ Unknown operator: <name>` + 원본 params JSON
- 클라이언트 검증이 placeholder 존재 시 실행 차단 ("unknown operator 포함")
- 의의: 과거 config JSON을 **열람용으로는 계속 볼 수 있음**, 재실행은 차단

### 2-4. 제안 파일 구조

```
frontend/src/pipeline-sdk/
├── types.ts                  # NodeDefinition, NodeDataByKind, Context 타입
├── registry.ts               # NODE_REGISTRY, register 함수
├── bootstrap.ts              # 특수 노드 definition 등록 + operator 동적 확장 훅
├── hooks/useNodeData.ts
├── components/
│   ├── NodeShell.tsx         # 헤더/Handle/border/Tag 공통 UI
│   └── DynamicParamForm.tsx  # (기존 이동)
├── engine/
│   ├── graphToConfig.ts      # registry 순회
│   ├── configToGraph.ts      # matchFromConfig 파이프 + ownership 기반 엣지 복원
│   ├── clientValidation.ts   # 구조 검증 + 노드별 validate 수집
│   └── issueMapping.ts
├── definitions/
│   ├── dataLoadDefinition.tsx
│   ├── operatorDefinition.tsx   # manipulator → OperatorNodeData 팩토리
│   ├── mergeDefinition.tsx
│   ├── saveDefinition.tsx
│   └── placeholderDefinition.tsx
└── README.md                 # "새 노드 만드는 법" 가이드 (7-1a 항목 충족)
```

기존 `components/pipeline/nodes/`, `utils/pipelineConverter.ts`, `nodeStyles.ts`는 전부 흡수/폐기. `PipelineEditorPage`의 타입별 분기 로직도 제거.

**백엔드는 현재 파일 구조 유지**. `lib/manipulators/__init__.py`만 자동 발견 로직으로 교체.

### 2-5. 결과 — 새 노드 추가 비용

| 대상 | 현재 | SDK 적용 후 |
|------|------|-------------|
| 새 Manipulator | 백엔드 3곳 + 마이그레이션 | 백엔드 2곳 (클래스 1 + seed 1) |
| 새 특수 노드 | 프론트 9+곳 | 프론트 **2곳** (`definitions/<name>.tsx` + `NodeDataByKind` 1줄) |

### 2-6. "2곳 제약"의 런타임/컴파일 보장 (3-4)

새 노드 추가 시 수정 포인트가 **반드시 2곳으로 유지**되도록 SDK 자체에 강제 장치:

- `NODE_REGISTRY`의 키 집합은 `keyof NodeDataByKind`와 타입 레벨에서 정확히 일치해야 함 (TypeScript conditional types)
- 부팅 시 런타임 assert로 "registry에 등록된 kind 집합 == `NodeDataByKind`의 키 집합" 검사
- 이 assert가 실패하면 SDK 버그로 취급 (나머지 파일 수정으로 해결 시도하지 않음)

### 2-7. 마이그레이션 순서 (구현 단계)

1. `pipeline-sdk/` 스켈레톤 — 타입 테이블 + registry + `NodeShell`
2. 백엔드 `MANIPULATOR_REGISTRY` 자동 발견 교체 (기능 등가)
3. OperatorNode definition부터 SDK 포팅 → 동등성 확인
4. DataLoad / Merge / Save 순차 포팅
5. Placeholder node 정의 + `matchFromConfig` 파이프 통합
6. `PipelineConfig.schema_version` 필드 도입
7. `pipelineConverter.ts` → `engine/` 재구성 (단위 테스트 우선)
8. `PipelineEditorPage` 핸들러 SDK 경로로 전환 + 기존 노드 컴포넌트 파일 삭제
9. `docs_for_claude/pipeline-node-sdk-guide.md` 작성 (7-1a TODO 충족)

---

## 3. 결정 사항 기록

### 3-1. Manipulator 진실 원천 = **DB** ✅
- 이유: admin이 코드 없이도 `psql` / 관리 GUI로 상황 파악 가능해야 함
- 구체화: 클래스는 실행 로직 + `name`만, 메타는 seed migration. 둘은 역할 분리로 공존
- `sync_manipulators_to_db()` 및 alias 메커니즘 도입하지 않음 (DB 초기화 가능 전제)

### 3-2. Operator 노드 kind 통합 = **`kind='operator'` 고정** ✅
- React Flow `nodeTypes`는 5개 고정 (dataLoad/operator/merge/save/placeholder)
- operator의 다형성은 `OperatorNodeData.operator` 필드로 표현
- 미래 sub-type은 이 구조 안에서 확장

### 3-3. matchFromConfig 반환 계약 = **ownership 메타 강제** ✅
- `{ nodeId, data, ownedTaskKeys, ownedSourceDatasetIds? }`
- 엣지 복원은 ownership 맵 기반
- 복잡도 증가 수용

### 3-4. TypeScript 타입 전략 = **`NodeDataByKind` 테이블** ✅
- 새 노드 수정점 = definition 파일 + 타입 테이블 1줄 = 2곳
- 추가 수정 지점이 발생하면 SDK 버그로 취급

### 3-5. 하위 호환 = **Placeholder + schema_version 둘 다** ✅
- 과거 데이터 정합성은 맞추지 않음 (초기화 허용)
- 미래 대응용 방어 장치만 도입
- schema migrator는 YAGNI — 필드만 심음

### 3-6. DB sync 타이밍 문제 = **소거됨** ✅
- DB가 진실이므로 앱/워커는 DB를 읽기만 함
- UPSERT 경쟁 / 프로세스 간 버전 스큐 / 마이그레이션 타이밍 복잡도 **모두 존재하지 않음**
- DB 쓰기 주체는 Alembic 마이그레이션 단일 — 기존 워크플로 그대로

---

## 4. 다음 단계

§2-7 마이그레이션 순서에 따라 구현 착수. 각 단계는 독립 커밋 단위이며, 기존 동작 동등성을 확인하며 점진 포팅.
