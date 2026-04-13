# 파이프라인 노드 SDK화 — 설계안

> 작성: 2026-04-13
> 브랜치: `feature/pipeline-dag-node-sdk`
> 목적: 6차 설계서 §7-1 액션 아이템 1번 (노드 추가 SDK화) + 1-a (가이드 문서) 구현 준비
> 범위: 분석(1) + 설계 초안(2). 실제 구현(3)은 미착수.

---

## 1. 현황 분석 — 새 노드 추가 시 수정 파일

### 1-A. 새 Manipulator(Operator) 하나 추가

**백엔드**
1. `backend/lib/manipulators/<name>.py` — `UnitManipulator` 상속 구현 (`transform_annotation`, 필요 시 `build_image_manipulation`)
2. `backend/lib/manipulators/__init__.py` — `MANIPULATOR_REGISTRY` 딕셔너리에 수동 등록
3. `backend/migrations/versions/NNN_seed_<name>.py` — DB seed 마이그레이션 작성 (`params_schema`, `compatible_task_types`, `description` 등)
4. (선택) `REQUIRED_PARAMS`, `accepts_multi_input` 클래스 속성 추가

**프론트엔드**
- 원칙적으로 수정 없음 — API가 manipulator 메타를 반환 → `NodePalette` / `OperatorNode` / `DynamicParamForm`가 자동 반응
- 단, 고유 이모지를 부여하려면 `nodeStyles.ts#MANIPULATOR_EMOJI`
- 새 카테고리면 `nodeStyles.ts#CATEGORY_STYLE`
- `params_schema`에 새 UI 타입이 필요하면 `DynamicParamForm` 확장

→ **문제: 클래스 구현 + DB seed 두 곳에 중복 선언**. 동기화 드리프트 위험 (백로그 "DB seed 정합성 재확인" 실재).

### 1-B. 새 특수 노드 타입 추가 (비-operator 노드, 예: Split / TrainOutput)

**수정 파일 9개 이상**:
1. `types/pipeline.ts` — `<X>NodeData` 인터페이스 추가 + `PipelineNodeData` union 확장
2. `components/pipeline/nodes/<X>Node.tsx` — React Flow 컴포넌트 신규 (헤더/Handle/검증 Tag/store 구독 패턴 반복 작성)
3. `components/pipeline/nodeStyles.ts` — `SPECIAL_NODE_STYLE` 항목 추가
4. `pages/PipelineEditorPage.tsx` — `nodeTypes` 매핑 추가 + `handleAddNode`의 `data.type` 분기 확장
5. `components/pipeline/NodePalette.tsx` — 팔레트 버튼 하드코딩 + `createNodeData` 팩토리
6. `utils/pipelineConverter.ts` — `graphToPipelineConfig` / `pipelineConfigToGraph` / `validateGraphStructure` 양방향 분기 추가
7. `stores/pipelineEditorStore.ts` — `updateNodeParams` 등 type-guard 분기 확장
8. `components/pipeline/PropertiesPanel.tsx` — 선택 노드 type별 분기
9. `stores/…#applyValidationToNodes` — issue.field → 노드 매핑 규칙 추가

### 1-C. 결합 문제의 본질
- **노드 타입 분기(`if data.type === ...`)가 9개 파일에 산재** — "노드가 자기 자신에 대한 지식을 갖지 않고" 주변 코드가 대신 알고 있다.
- React Flow 노드 상용구(헤더 / Handle / border / 검증 Tag / store 직접 구독)가 노드마다 재작성된다.
- Manipulator는 DB seed + Python 클래스 **두 진실의 원천** → sync 마이그레이션이 수동 노동.
- config ↔ graph 변환기가 노드 타입 지식을 하드코딩으로 갖고 있어, 노드 추가 시 변환기가 선형 팽창한다.

---

## 2. SDK 설계안

핵심 원칙: **"노드 정의 = 한 객체"**. 한 파일에 선언하면 팔레트·캔버스·검증·변환·속성 패널이 자동 연결된다. 파일 구조는 전면 재편(사용자 승인).

### 2-1. 백엔드 — Manipulator 자기등록 (Self-Register)

`params_schema`를 DB seed가 아니라 **클래스 속성**으로 이동. registry → DB sync를 앱 부팅이 수행.

```python
class RemapClassName(UnitManipulator):
    name = "remap_class_name"
    category = "REMAP"
    description = "class명 변경"
    compatible_task_types = ["DETECTION", "SEGMENTATION"]
    compatible_annotation_fmts = ["COCO", "YOLO"]
    scope = ["PER_SOURCE"]
    required_params = ["mapping"]
    accepts_multi_input = False
    params_schema = {
        "mapping": {"type": "key_value", "label": "class 이름 매핑", "required": True}
    }

    def transform_annotation(self, ...): ...
    # build_image_manipulation은 필요한 경우에만 오버라이드
```

**자동 등록 메커니즘**
- `lib/manipulators/__init__.py`가 하위 모듈을 패키지 walk로 import → 메타클래스/데코레이터가 `MANIPULATOR_REGISTRY`에 자동 수록
- `sync_manipulators_to_db()` — 앱/Celery 부팅 시 registry 전체를 `manipulators` 테이블에 UPSERT
- 기존 seed 마이그레이션은 "빈 테이블 + 초기 스냅샷"으로 축소. **코드가 진실의 원천**
- 삭제된 manipulator는 hard delete 금지 — `status=DEPRECATED` soft deactivate (lineage 참조 무결성 보호)

→ **새 manipulator 추가 = 파일 1개 + 재시작**.

### 2-2. 프론트엔드 — NodeDefinition 중심 아키텍처

노드의 모든 관심사를 한 객체로 통합:

```typescript
export interface NodeDefinition<TData extends BaseNodeData = BaseNodeData> {
  kind: string                                      // React Flow 노드 타입 키
  palette: {
    section: 'basic' | 'manipulator'
    label: string
    description?: string
    color: string
    emoji: string
    disabledRule?: (ctx) => { disabled: boolean; reason?: string }
  }
  handles: { inputs: { min: number; max: number | 'infinity' }; outputs: number }
  createDefaultData(ctx: CreateContext): TData
  NodeComponent: React.ComponentType<NodeProps>
  PropertiesComponent?: React.ComponentType<{ nodeId: string; data: TData }>
  validate?(data: TData, ctx: GraphContext): ClientValidationError[]
  toConfigContribution(data: TData, ctx: ConvertContext): ConfigContribution
  matchFromConfig?(config: PipelineConfig): RestoredNode<TData>[]
  matchIssueField?(issueField: string, data: TData): boolean
}
```

**단일 Registry + 런타임 확장**
```typescript
export const NODE_REGISTRY = new Map<string, NodeDefinition>()
registerNodeDefinition(dataLoadDef)
registerNodeDefinition(mergeDef)
registerNodeDefinition(saveDef)
// Operator 계열은 manipulator API 응답 수신 후 팩토리로 동적 생성:
registerOperatorDefinitionsFromApi(manipulators)
```

**SDK가 제공하는 상용구 헬퍼**
- `<NodeShell header color issues handles>` — 헤더 / border / 검증 Tag / Handle 공통
- `useNodeData<T>(nodeId)` — store 직접 구독 + 타입 좁힘
- `buildNodeTypesFromRegistry()` — React Flow `nodeTypes` 자동 생성
- `declareOperatorFromManipulator(meta)` — API 메타 → NodeDefinition 팩토리

**분기가 있던 모든 지점이 registry 순회로 전환된다**
- `PipelineEditorPage` — `nodeTypes = buildNodeTypesFromRegistry()`
- `NodePalette` — registry 순회 + operator 자동 확장
- `graphToPipelineConfig` — 각 노드의 `toConfigContribution()` 수집
- `pipelineConfigToGraph` — 각 definition의 `matchFromConfig()` 파이프 실행
- `applyValidationToNodes` — issue마다 registry 순회하며 `matchIssueField()` 적용
- `PropertiesPanel` — 선택 노드의 `PropertiesComponent`만 렌더

### 2-3. 제안 파일 구조

```
frontend/src/pipeline-sdk/
├── types.ts                  # NodeDefinition, BaseNodeData, Context 타입
├── registry.ts               # NODE_REGISTRY, register 함수
├── bootstrap.ts              # 모든 definitions 등록 + operator 동적 등록 훅
├── hooks/useNodeData.ts
├── components/
│   ├── NodeShell.tsx         # 헤더 / Handle / border / Tag 공통 UI
│   └── DynamicParamForm.tsx  # (기존 이동, 타입 확장 지점 일원화)
├── engine/
│   ├── graphToConfig.ts      # registry 순회만
│   ├── configToGraph.ts
│   ├── clientValidation.ts   # 구조 검증 + 노드별 validate 수집
│   └── issueMapping.ts
├── definitions/
│   ├── dataLoadDefinition.tsx
│   ├── operatorDefinition.tsx   # manipulator → definition 팩토리
│   ├── mergeDefinition.tsx
│   └── saveDefinition.tsx
└── README.md                 # "새 노드 만드는 법" 가이드 (7-1a 항목 충족)
```

기존 `components/pipeline/nodes/`, `utils/pipelineConverter.ts`, `nodeStyles.ts`는 전부 흡수/폐기. `PipelineEditorPage`의 타입별 분기 로직도 제거.

### 2-4. 결과 — 새 노드 추가 비용

| 대상 | 현재 | SDK 적용 후 |
|------|------|-------------|
| 새 Manipulator | 백엔드 4곳 + 마이그레이션 | 백엔드 파일 1개 |
| 새 특수 노드 | 프론트 9+곳 | 프론트 `definitions/<name>.tsx` 1개 |

### 2-5. 마이그레이션 순서 (구현 단계에서 참고)

1. SDK 타입 + `NodeShell` 상용구 + registry 스켈레톤
2. 백엔드 manipulator 자기등록 + `sync_manipulators_to_db()` (기존 seed와 공존 가능)
3. OperatorNode 정의부터 SDK 포팅 → 동등성 확인
4. DataLoad / Merge / Save 순차 포팅
5. `pipelineConverter.ts` → `engine/`로 재구성 (단위 테스트 우선)
6. `PipelineEditorPage` 핸들러를 SDK 경로로 전환
7. 기존 seed 마이그레이션을 no-op으로 비활성화
8. `docs_for_claude/pipeline-node-sdk-guide.md` 작성 (7-1a TODO 충족)

### 2-6. 결정 필요 지점 / 리스크

상세 설명은 본 문서 §3 참조.

1. Manipulator 진실 원천 이동 (DB → 코드)
2. Operator 노드의 런타임 등록 (빌드 타임 vs 런타임 혼재)
3. 역변환(matchFromConfig) 복잡성
4. TypeScript 제네릭/공변성 타협
5. 기존 실행 이력 config JSON과의 하위 호환
6. Celery 워커 부팅 타이밍과 DB sync 충돌

---

## 3. 결정 필요 지점 / 리스크 상세

### 3-1. Manipulator 진실 원천 이동 (DB → 코드)

**현재**: `manipulators` 테이블이 진실의 원천. 코드의 `UnitManipulator` 클래스와 DB row가 **이름으로만 느슨하게 연결**되어 있고, `params_schema` / `description` / `compatible_task_types`는 DB에만 존재.

**제안**: 코드가 진실의 원천. 부팅 시 DB UPSERT. 프론트는 여전히 DB를 조회하지만 실제 쓰기 주체는 코드.

**리스크**:
- **이름 변경 = 새 manipulator 취급**. `filter_final_classes` → `filter_remain_selected_class_names_only_in_annotation` 같은 과거 리네이밍이 벌어지면, lineage의 `transform_config` 스냅샷에 남은 옛 이름이 "unknown operator"가 된다.
  - 완화: `aliases: list[str]` 클래스 속성 → registry에서 alias도 인덱싱 → 실행 시 resolve
- **DEPRECATED 상태 운영 규칙 필요**. 코드에서 삭제되면 UPSERT가 DEPRECATED로 표시만 할지, `deleted_at` 설정할지 결정 필요. lineage의 과거 실행 config를 가리키는 참조가 끊어지면 안 됨.
- **수동 DB 조작이 무효화**된다. 운영자가 DB 직접 UPDATE로 `description`을 고쳐도 다음 부팅 시 덮어쓰여진다 → 운영 관례 변경 공지 필요.
- **params_schema의 "마이그레이션 파괴적 변경"**. 기존 실행 이력 config에 존재하던 param이 스키마에서 사라지면 불러오기 / 재실행이 깨질 수 있다. Backward-compatible 확장만 허용하는 규칙 도입 권장.

**결정 필요**:
- (a) 이름 변경 정책: alias 지원 여부
- (b) 삭제 정책: DEPRECATED-only vs soft delete
- (c) schema 버전 필드 도입 여부 (`params_schema_version`)

### 3-2. Operator 노드의 런타임 등록 (빌드 타임 vs 런타임 혼재)

**문제의 구조**:
- **특수 노드** (DataLoad, Merge, Save)는 프론트엔드 빌드 타임에 정의를 작성하는 게 자연스럽다 — 도메인 지식과 UI가 타이트하게 결합되어 있기 때문.
- **Operator 노드**는 manipulator API 응답으로 비로소 존재를 안다 → 빌드 타임 등록 불가.

**제안**: registry는 양쪽을 모두 수용. 부팅 시 2단계 등록.
```
1. bootstrap() — 특수 노드 definition 3종 등록
2. manipulators API 로드 후 registerOperatorDefinitionsFromApi() — operator definition N개 동적 등록
```

**리스크**:
- 첫 렌더링 시점에는 operator definition이 아직 없음 → `NODE_REGISTRY.get("some_operator")`가 null. JSON 불러오기 / 팔레트가 **API 대기 상태를 명시적으로 처리**해야 한다.
- React Flow `nodeTypes`는 최초 렌더 후 변경이 까다롭다 (노드 타입이 달라지면 리렌더 이슈). 해결: 모든 operator는 kind=`'operator'` 하나로 통일하고, **definition은 `kind`가 아니라 `operator_name`으로 구분**하는 설계 필요.
- 서버사이드 렌더링 / 테스트 환경에서 registry 초기화 순서가 불안정해질 수 있다. Registry를 React Context로 감싸 lazy 초기화로 다루는 편이 안전.

**결정 필요**:
- operator definition을 kind 단위로 쪼갤지, `kind='operator'` 하나로 묶고 내부에서 operator_name으로 분기할지 (후자 권장)

### 3-3. 역변환(matchFromConfig) 복잡성

**문제**: config → graph 역변환에는 각 노드 종류가 config에서 자기 자신을 **식별하는 서로 다른 규칙**이 있다.
- **Save**: config 전체에 1개 (`config.name`, `config.output` → 싱글톤 생성)
- **Operator**: `config.tasks[<key>]` 단위로 1:1
- **Merge**: `config.tasks[<key>]` 중 `operator === 'merge_datasets'`만
- **DataLoad**: `config.tasks[*].inputs`에서 `"source:<dataset_id>"` 추출, **dataset_id별 유니크** — task가 아니라 input 문자열 스캔

`NodeDefinition#matchFromConfig`를 노드 작성자가 자유롭게 구현하게 하면 자유도는 높지만 실수 여지가 크다 (ID 중복, 엣지 복원 누락 등).

**제안**: SDK가 세 가지 빌트인 패턴을 헬퍼로 제공.
```typescript
configMatchers.singleton({ from: (config) => ({ name: config.name, ... }) })
configMatchers.perTask({ predicate: (task) => task.operator !== 'merge_datasets' })
configMatchers.sourceString({ prefix: 'source:' })
```

노드 작성자는 헬퍼 중 하나를 고르고 변환 함수만 쓰면 된다.

**리스크**:
- 엣지 복원은 노드 생성과 분리되어 있다 (현재 `pipelineConfigToGraph`가 한 번에 처리). SDK로 쪼개면 엣지 생성기가 "누가 어느 task/source를 맡았는지" 알아야 하므로 **노드 생성 결과에 `taskKey → nodeId`, `datasetId → nodeId` 매핑 반환을 강제**하는 계약이 필요하다.
- 세 패턴으로 커버 안 되는 미래 노드가 나오면 SDK 확장이 필요 — 일반화 vs YAGNI 트레이드오프. 일단 3종 헬퍼로 출발.
- 자동 레이아웃(`_applyAutoLayout`)은 노드 종류와 무관하게 graph 위에서 동작하므로 SDK 밖에 둬야 함 (변경 없음).

**결정 필요**:
- "matchFromConfig 결과 계약"의 형태 — 생성된 node + 자기가 담당한 config 키 반환

### 3-4. TypeScript 제네릭 / 공변성 타협

**문제**: `NodeDefinition<TData>`를 제네릭으로 만들면 각 definition 내부는 안전하지만, `Map<string, NodeDefinition<???>>`에 담을 때 `TData` 파라미터가 공변/반공변 양쪽에 나타나 union이 안 된다.

**예시**:
```typescript
// 타입 에러 — toConfigContribution은 TData를 input으로 받으므로 반공변
const map = new Map<string, NodeDefinition<DataLoadData> | NodeDefinition<SaveData>>()
```

**제안**: 내부 저장은 `NodeDefinition<any>`로 통일, 접근 시 타입 좁힘 헬퍼로 복원.
```typescript
const def = NODE_REGISTRY.get(kind) as NodeDefinition<SaveData>
// 또는 getNodeDefinition<SaveData>(kind)
```

**리스크**:
- `any`는 타입 안전성을 소실. definition 작성자가 잘못된 `TData`를 선언해도 컴파일러가 못 잡는다.
- 대안: `unknown` + discriminated union + 런타임 가드 — 보일러플레이트 증가
- 대안: `kind → TData` 매핑 테이블(`NodeDataByKind`)을 타입 레벨로 유지 — 확장 시 두 곳 수정 필요 (단 registry 밖의 한 곳)

**결정 필요**:
- `any` 기반 실용 타협 vs `NodeDataByKind` 타입 테이블 유지 (후자 권장 — 확장성은 타입만 건드리면 됨)

### 3-5. 기존 실행 이력 config JSON과의 하위 호환

**문제**: `PipelineExecution.config` JSONB에는 과거 실행의 config 스냅샷이 남아있다. 드로어에서 "Config 불러오기"로 DAG 복원이 현 구현의 핵심 기능이다.

**리스크**:
- SDK 리팩토링 중 **PipelineConfig 스키마를 바꾸면 과거 실행의 불러오기가 깨진다**. config 스키마(v1: 현재)는 건드리지 말 것.
- 과거 스냅샷에 들어있는 operator 이름 / params가 현재 registry에 없으면 어떻게 보여줄 것인가? "이 operator는 DEPRECATED입니다" placeholder 노드를 만들어야 함 (지금은 그냥 `Modal.warning`).
- `config_schema_version` 필드를 PipelineConfig에 도입할지 결정 필요. 도입하면 향후 변경 포용, 안 하면 단순성 유지.

**결정 필요**:
- 과거 config 호환 정책: "best effort 복원 + unknown operator placeholder 노드"
- schema version 필드 도입 여부 (YAGNI vs 미래 대비)

### 3-6. Celery 워커 부팅 타이밍과 DB sync 충돌

**문제**: FastAPI 백엔드 + Celery 워커 2개 프로세스가 동시에 부팅되며 둘 다 `sync_manipulators_to_db()`를 호출하면 UPSERT 경쟁이 발생한다.

**리스크**:
- PostgreSQL은 `INSERT ... ON CONFLICT ... DO UPDATE`로 원자적 처리 가능하지만, **두 프로세스가 동일 row를 동시에 쓰면 락/데드락 가능성**이 있다.
- Celery 워커는 코드 변경 시 재시작되지만 FastAPI는 재시작 빈도가 다르다 → 버전 스큐 상황에서 한쪽은 신규 manipulator를 알고 다른 쪽은 모를 수 있다.
- Alembic 마이그레이션은 `alembic upgrade head`가 단일 지점에서 실행 → 마이그레이션 시점에 sync도 함께 돌리는 편이 단순. 그러면 "부팅 시 sync"가 아니라 "마이그레이션 시 sync"가 된다.

**제안**:
- sync는 **마이그레이션 시점에만 실행** (Alembic post-upgrade hook 또는 별도 `make sync-manipulators` 커맨드)
- 앱 부팅 시에는 registry 로드만, DB 쓰기 없음
- Celery는 자신의 registry로 operator 실행 → DB는 프론트 메타 조회용으로만 사용

**리스크**:
- 마이그레이션 없이 manipulator만 추가한 경우 `make sync-manipulators` 수동 실행이 필요해짐 → 문서화 필수
- 개발 편의성은 자동화된 "부팅 시 sync"가 나음 — 개발/운영 분기 가능

**결정 필요**:
- sync 실행 시점: 부팅 vs 마이그레이션 vs 수동 커맨드
- 개발 환경과 운영 환경에서 다른 정책을 쓸지

---

## 4. 다음 단계 (구현 착수 시)

이 문서의 결정 필요 지점 6종에 대해 사용자와 **선택을 확정**한 뒤, §2-5 마이그레이션 순서에 따라 구현을 시작한다. 각 단계는 독립 커밋 단위이며, 기존 동작 동등성을 확인하며 점진 포팅한다.
