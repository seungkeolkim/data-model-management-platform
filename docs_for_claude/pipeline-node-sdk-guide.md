# 파이프라인 노드 SDK 가이드

이 문서는 파이프라인 에디터에 **새 노드를 추가하는 방법**을 설명합니다.
설계 배경·원칙은 `pipeline-node-sdk-design_truth-db.md`를 참조하세요.

---

## 0. 용어 정리

- **NodeKind** — 에디터가 인식하는 노드 종류. 현재 5종: `dataLoad`, `operator`, `merge`, `save`, `placeholder`.
- **Manipulator** — DB `manipulators` 테이블에 등록된 단위 변환 함수. 전부 `operator` NodeKind 하나로 렌더링됨 (manipulator 이름·category·params_schema만 다를 뿐 동일 NodeComponent 사용).
- **NodeDefinition** — 한 NodeKind의 팔레트 / NodeComponent / PropertiesComponent / validate / config 변환 로직을 한 곳에 묶는 SDK의 중심 타입.

두 가지 추가 경로가 있습니다.

| 원하는 것 | 경로 | 난이도 |
|---|---|---|
| **새 단위 변환 추가** (예: `blur_image`) | A. Manipulator 추가 | Python 클래스 1개 + seed 1줄 |
| **새 특수 노드 추가** (예: `split` 노드) | B. NodeKind 추가 | TS 정의 파일 1개 + registry 키 3군데 |

---

## A. 새 Manipulator 추가 (대부분 여기로)

**원칙: `lib/manipulators/` 아래 모듈만 추가하면 됩니다.** 레지스트리는 `pkgutil.iter_modules`로 자동 발견하므로 `__init__.py`나 중앙 목록을 수정할 필요가 없습니다.

### A-1. UnitManipulator 서브클래스 작성

`backend/lib/manipulators/blur_image.py` (예시):

```python
from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.models import Annotation, ImagePlan

class BlurImage(UnitManipulator):
    """이미지에 Gaussian blur를 적용. 어노테이션은 그대로 통과."""

    @property
    def name(self) -> str:
        # DB manipulators.name과 반드시 일치
        return "blur_image"

    def transform_annotation(self, annotation: Annotation, params: dict) -> Annotation:
        return annotation  # 어노테이션 변형 없음

    def build_image_manipulation(self, params: dict) -> ImagePlan:
        radius = params.get("radius", 3)
        # PipelineExecutor가 해석하는 plan 형태로 반환
        return ImagePlan(ops=[{"type": "gaussian_blur", "radius": radius}])
```

**주의사항:**
- `name` 프로퍼티는 **인스턴스 생성 없이 호출 가능한 값**이어야 자동 발견 시 수집됨
- 같은 `name`을 가진 manipulator가 2개 이상이면 부팅 시 즉시 예외 (seed 정합성 보호)
- 추상 중간 클래스는 `inspect.isabstract`로 자동 제외되므로 안전

### A-2. Seed 마이그레이션 작성

`backend/migrations/versions/xxxx_seed_blur_image.py`:

```python
def upgrade():
    op.execute("""
        INSERT INTO manipulators (name, display_name, category, emoji,
                                  description, params_schema, compatible_task_types,
                                  status, created_at, updated_at)
        VALUES ('blur_image', '이미지 블러', 'AUGMENT', '🌫️',
                '가우시안 블러를 적용합니다 (어노테이션 불변)',
                '{"type":"object","properties":{"radius":{"type":"number","default":3}}}',
                '["DETECTION","SEGMENTATION"]', 'ACTIVE', NOW(), NOW())
    """)
```

**필드 의미:**
- `name` — `UnitManipulator.name`과 정확히 일치
- `category` — 팔레트 그룹핑에 사용 (`CATEGORY_STYLE` 매핑 키). 새 category를 쓰려면 `frontend/src/pipeline-sdk/styles.ts`의 `CATEGORY_STYLE`에 스타일 추가
- `params_schema` — JSON Schema. 프론트 `DynamicParamForm`이 이걸로 속성 패널을 자동 생성
- `compatible_task_types` — 팔레트가 현재 taskType에 맞춰 필터링

### A-3. 검증

```bash
make migrate
docker exec mlplatform-backend python -c "from lib.manipulators import MANIPULATOR_REGISTRY; print('blur_image' in MANIPULATOR_REGISTRY)"
```

프론트는 재시작하면 팔레트에 자동 노출됩니다. **프론트 코드 수정 불필요.**

---

## B. 새 특수 NodeKind 추가

팔레트에 고정된 특수 노드(dataLoad/merge/save 같은)를 하나 더 만들고 싶을 때. 예: `split` 노드.

### B-1. `NodeDataByKind`에 타입 추가

`frontend/src/pipeline-sdk/types.ts`:

```ts
export interface SplitNodeData extends BaseNodeData {
  type: 'split'
  ratio: number  // 예: 0.8
}

export interface NodeDataByKind {
  dataLoad: DataLoadNodeData
  operator: OperatorNodeData
  merge: MergeNodeData
  save: SaveNodeData
  placeholder: PlaceholderNodeData
  split: SplitNodeData   // ← 추가
}
```

### B-2. Definition 파일 작성

`frontend/src/pipeline-sdk/definitions/splitDefinition.tsx`:

```tsx
import type { NodeDefinition } from '../types'

export const splitDefinition: NodeDefinition<'split'> = {
  kind: 'split',
  paletteItems: (ctx) => [{
    key: 'split',
    section: 'basic',
    label: 'Split',
    emoji: '✂️',
    color: '#8e44ad',
    createData: () => ({ type: 'split', ratio: 0.8, label: 'Split' }),
  }],
  NodeComponent: ({ nodeId }) => { /* NodeShell로 감싼 뷰 */ },
  PropertiesComponent: ({ nodeId, data }) => { /* ratio 입력 UI */ },
  validate: (data, ctx) => {
    if (data.ratio <= 0 || data.ratio >= 1) {
      return [{ severity: 'error', message: 'ratio는 0<r<1' }]
    }
    return []
  },
  toConfigContribution: (data, ctx) => ({
    tasks: { [ctx.nodeId]: { operator: 'split', params: { ratio: data.ratio }, inputs: ctx.inputRefs } },
    outputRef: `task:${ctx.nodeId}`,
  }),
  matchFromConfig: (config, matchCtx) => { /* unclaimed task 중 operator==='split' 클레임 */ },
  matchIssueField: (field) => field === 'split_ratio' ? 'ratio' : null,
}
```

### B-3. bootstrap + registry 갱신

`frontend/src/pipeline-sdk/bootstrap.ts`:

```ts
import { splitDefinition } from './definitions/splitDefinition'
registerNodeDefinition(splitDefinition)
```

`frontend/src/pipeline-sdk/registry.ts`의 `assertRegistryCompleteness` expected 배열:

```ts
const expected: NodeKind[] = ['dataLoad', 'operator', 'merge', 'save', 'placeholder', 'split']
```

> **이 3곳 중 한 군데라도 누락되면 런타임 assert로 즉시 터집니다.** 의도된 감시 포인트이므로 "회피"하지 말고 반드시 채워넣으세요.

### B-4. matchFromConfig 작성 규칙 (중요)

JSON 복원 시 `configToGraph`가 정의별 `matchFromConfig`를 `MATCH_ORDER` 순으로 호출하며, 각 정의는 **자신이 소유할 task_key / source_dataset_id를 claim**해야 합니다.

- `ownedTaskKeys: Set<string>` — 이 노드가 흡수한 `config.tasks` 키
- `ownedSourceDatasetIds: Set<string>` — 이 노드가 흡수한 `source:<id>` 참조

이후 정의는 `matchCtx.claimedTaskKeys` / `claimedSourceDatasetIds`를 보고 중복 클레임을 피합니다. 마지막 `placeholder`가 leftover를 쓸어담아 절대 유실이 없게 보장합니다.

---

## C. 자주 묻는 것

**Q. NodeComponent에서 React Flow의 `data` prop이 업데이트가 안 됩니다.**
A. `useNodeData(nodeId)` 훅을 쓰세요. React Flow는 초기 `data`만 넘겨주므로 store 직접 구독이 필요합니다.

**Q. params_schema를 바꿨는데 팔레트 UI가 그대로입니다.**
A. manipulator는 React Query로 60초 캐시됩니다. 새로고침하거나 query invalidate.

**Q. placeholder 노드가 자꾸 생깁니다.**
A. JSON에 DB에 없는 operator가 있다는 뜻. Seed 마이그레이션을 돌렸는지 확인하세요. placeholder는 "유실 방지"가 목적이며 실행 시 validate가 차단합니다.

**Q. 기존 operator에 필드를 추가했는데 옛날 JSON을 불러오면 경고가 뜹니다.**
A. `PipelineConfig.schema_version` 올리고 `matchFromConfig`에서 버전별 분기를 넣으세요. 현재 `CURRENT_SCHEMA_VERSION = 1` (`engine/graphToConfig.ts`).

---

## D. 체크리스트

Manipulator 추가:
- [ ] `lib/manipulators/<name>.py`에 UnitManipulator 서브클래스
- [ ] Alembic seed 마이그레이션
- [ ] `make migrate` + 레지스트리 확인

새 NodeKind 추가:
- [ ] `types.ts` `NodeDataByKind`에 항목
- [ ] `definitions/<kind>Definition.tsx` 작성
- [ ] `bootstrap.ts`에 `registerNodeDefinition`
- [ ] `registry.ts` expected 배열에 추가
- [ ] `matchFromConfig`에서 정확한 claim 범위 설정
