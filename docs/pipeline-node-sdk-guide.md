# 파이프라인 노드 SDK 가이드

이 문서는 파이프라인 에디터·실행 엔진에 **새 Manipulator** 또는 **새 NodeKind** 를
추가할 때 실제로 손대야 하는 지점과 계약을 정리한 실무 가이드입니다. 코드와
문서가 어긋날 경우 코드가 정답입니다 — 이 문서도 코드에 맞춰 갱신합니다.

---

## 0. 구조 한눈에 보기

```
backend/lib/pipeline/
  manipulator_base.py        — UnitManipulator ABC
  pipeline_data_models.py    — DatasetMeta / ImageRecord / ImageManipulationSpec / ImagePlan / DatasetPlan / HeadSchema
  config.py                  — PipelineConfig / TaskConfig / OutputConfig
  dag_executor.py            — PipelineDagExecutor: topological 실행 + Phase B 실체화
  image_materializer.py      — ImageMaterializer: spec.operation 디스패치 (rotate_image, mask_region)
  pipeline_visualizer.py     — pipeline.png (graphviz)
  pipeline_validator.py      — 서버측 PipelineConfig 검증
  io/                        — coco_io / yolo_io / manifest_io / classification head_schema IO

backend/lib/manipulators/
  __init__.py                — MANIPULATOR_REGISTRY (pkgutil.iter_modules 자동 발견)
  det_*.py                   — detection 도메인 14종
  cls_*.py                   — classification 도메인 N종
  (detseg_*.py)              — detection+segmentation 통합 시 예약 prefix

backend/migrations/versions/
  001_initial_schema.py      — 테이블 생성 (manipulators 포함)
  002_seed_manipulators.py   — detection 14종 초기 시드
  009_add_head_schema.py     — Dataset.head_schema 추가
  010_seed_cls_manips.py     — classification 초기 시드
  011/012/013/014_*.py       — 스코프 축소, 이름 접두어 정리
  (새 manipulator 를 추가할 때마다 여기 파일 1개를 추가한다)

frontend/src/pipeline-sdk/
  types.ts                   — NodeKind, NodeDataByKind, NodeDefinition 계약
  registry.ts                — registerNodeDefinition / assertRegistryCompleteness (하드코딩 expected 리스트)
  bootstrap.ts               — 모든 definition 등록 + 무결성 assert
  palette.ts                 — buildPaletteItems (registry 순회)
  styles.ts                  — CATEGORY_STYLE / MANIPULATOR_EMOJI
  definitions/
    dataLoadDefinition.tsx     — kind='dataLoad'     (source:<id> 토큰만 기여)
    operatorDefinition.tsx     — kind='operator'     (manipulator API → 팔레트 동적 확장)
    mergeDefinition.tsx        — kind='merge'        (operator='det_merge_datasets' 고정)
    saveDefinition.tsx         — kind='save'         (PipelineConfig.name/output 기여)
    placeholderDefinition.tsx  — kind='placeholder'  (미등록 operator 복원용)
  engine/
    graphToConfig.ts         — CURRENT_SCHEMA_VERSION=1, 각 definition.toConfigContribution 수집·병합
    configToGraph.ts         — MATCH_ORDER 순회, matchFromConfig 로 ownership claim
    clientValidation.ts      — 그래프 레벨 사전 검증
    issueMapping.ts          — 서버 issue.field ↔ nodeId 매핑
  hooks/useNodeData.ts       — Zustand store 구독 (React Flow data prop 업데이트 누락 회피)
  components/NodeShell.tsx   — 모든 노드가 공유하는 컨테이너 (handle / issue badge 표준화)
```

---

## 1. 용어 — 자주 헷갈리는 네임스페이스

| 용어 | 값 공간 | 어디에 쓰이는가 |
|---|---|---|
| **NodeKind** | 5종 고정: `dataLoad` / `operator` / `merge` / `save` / `placeholder` | 프론트 SDK 가 인식하는 노드 종류. `NodeDataByKind` 의 키와 일치. |
| **operator** | manipulator 의 DB `name` (예: `det_rotate_image`, `cls_rename_head`) | `TaskConfig.operator`, DAG registry 키, pipeline.png 라벨. |
| **operation** | ImageMaterializer 가 디스패치하는 문자열 (예: `rotate_image`, `mask_region`) | `ImageManipulationSpec.operation`. **operator 와 별개 네임스페이스 — prefix 규약 적용 대상 아님.** |
| **category** | manipulator 의 분류 태그 (DB `category`, 팔레트 섹션) | `ANNOTATION_FILTER` / `IMAGE_FILTER` / `FORMAT_CONVERT` / `SAMPLE` / `REMAP` / `AUGMENT` / `MERGE` / `SCHEMA` |
| **scope** | `PER_SOURCE` / `POST_MERGE` (JSONB 리스트) | 입력 시그니처 — PER_SOURCE 는 단건 DatasetMeta, POST_MERGE 는 list[DatasetMeta]. |
| **task_kind** | `DETECTION` / `CLASSIFICATION` | `DatasetMeta.head_schema` 유무로 결정. executor·IO 분기 기준. |
| **compatible_task_types** | `["DETECTION"]` / `["CLASSIFICATION"]` / 복수 | 팔레트 필터링. 에디터 taskType 쿼리 파라미터에 맞춰 걸러짐. |

**중요**: `operator` 와 `operation` 은 같은 단어지만 다른 변수입니다. 네이밍 rename
시 이 둘을 구분해서 바꿔야 합니다 (과거 실제 사고 사례 있음).

---

## 2. 이름 규약

pipeline.png 라벨 가독성과 IDE 파일 트리 정렬을 맞추기 위해 도메인 prefix 를 둡니다.

| 도메인 | prefix | 예시 |
|---|---|---|
| Detection | `det_` | `det_rotate_image`, `det_merge_datasets` |
| Classification | `cls_` | `cls_rename_head`, `cls_merge_datasets` |
| Detection + Segmentation 통합(예정) | `detseg_` | — |

**규약**:
- prefix 는 붙이되 **prefix 이후 본체는 축약하지 않는다**. `det_rot` (X), `det_rotate_image` (O).
- 파일명 · 클래스 · `name` property · DB `manipulators.name` 네 곳이 모두 일치해야 합니다.
- 같은 동작이 두 도메인에 모두 필요하면 각 도메인별로 별도 manipulator 를 만듭니다 (예: `det_merge_datasets` 와 `cls_merge_datasets` 는 별개 클래스).

---

## 3. A경로 — 새 Manipulator 추가

대부분의 작업은 여기입니다. **파일 2개** 로 끝납니다.

### 3-1. UnitManipulator 구현

`backend/lib/manipulators/det_<name>.py` (또는 `cls_<name>.py`).

```python
"""
det_blur_image — Gaussian blur (AUGMENT).

annotation 은 불변. 이미지만 변형한다.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import (
    DatasetMeta, ImageManipulationSpec, ImageRecord,
)

logger = logging.getLogger(__name__)


class BlurImage(UnitManipulator):
    """
    DB seed name: "det_blur_image".
    scope=["PER_SOURCE","POST_MERGE"], compatible_task_types=["DETECTION"].
    """

    @property
    def name(self) -> str:
        return "det_blur_image"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        # PER_SOURCE 단건 입력만 허용 (POST_MERGE 이면 list 가 들어옴).
        if isinstance(input_meta, list):
            raise TypeError("det_blur_image 는 단건 DatasetMeta 만 입력 가능합니다.")

        radius = float(params.get("radius", 3.0))
        if radius <= 0:
            raise ValueError(f"radius 는 양수여야 합니다: {radius}")

        result_meta = copy.deepcopy(input_meta)
        for record in result_meta.image_records:
            # 이미지 변환 명세를 record.extra 에 누적.
            # Phase B 의 _build_image_plans 가 이 dict 를 ImagePlan.specs 로 추출한다.
            specs = record.extra.get("image_manipulation_specs", [])
            specs.append({
                "operation": "gaussian_blur",   # ← ImageMaterializer 디스패치 키 (prefix 없음!)
                "params": {"radius": radius},
            })
            record.extra["image_manipulation_specs"] = specs

        logger.info("det_blur_image 완료: images=%d, radius=%.1f",
                    len(result_meta.image_records), radius)
        return result_meta

    def build_image_manipulation(
        self,
        image_record: ImageRecord,
        params: dict[str, Any],
    ) -> list[ImageManipulationSpec]:
        radius = float(params.get("radius", 3.0))
        return [ImageManipulationSpec(
            operation="gaussian_blur",   # ← 위 dict 의 operation 과 반드시 동일
            params={"radius": radius},
        )]
```

**반드시 지켜야 할 계약**:

1. **`name` property 는 인스턴스 생성 직후 호출 가능해야 한다.**
   registry 는 `instance = obj(); instance.name` 으로 키를 얻습니다. `__init__` 에
   필수 인자가 있거나 `name` 이 동적으로 계산되면 자동 발견에서 **조용히 스킵**됩니다.

2. **`transform_annotation` 시그니처는 고정입니다.**
   `(input_meta, params, context=None) -> DatasetMeta`. DAG executor 는 현재
   `.transform_annotation(meta, params)` 로 호출하므로 `context` 는 기본값을
   유지하세요. POST_MERGE 전용(multi-input) 이면 클래스 속성 `accepts_multi_input = True`
   를 선언해야 executor 가 `list[DatasetMeta]` 를 직접 넘깁니다 (안 그러면
   `_merge_metas()` 로 미리 합쳐져서 단건으로 들어옵니다).

3. **이미지 파일 I/O 는 절대 금지.** annotation·meta 만 만지세요. 실제 바이너리
   변형은 ImageMaterializer 의 역할입니다. 이를 위반하면 Phase A/B 분리 이득이
   사라집니다 (재시도·증분·분산 실행 전부 깨짐).

4. **이미지 변형이 필요하면 두 곳을 동기화합니다:**
   - `transform_annotation` 에서 `record.extra["image_manipulation_specs"]` 에
     `{"operation": "...", "params": {...}}` dict 를 append.
   - `build_image_manipulation` 에서 동일한 `ImageManipulationSpec` 를 반환.
   - **`operation` 문자열은 ImageMaterializer 의 `_apply_image_operation` 에서
     `if spec.operation == "..."` 로 매칭하는 키입니다. 반드시 거기 분기를 추가해야
     실제 픽셀이 변형됩니다.** 미지원 operation 은 경고만 찍고 조용히 스킵됩니다 —
     이게 가장 흔한 버그 패턴입니다.

5. **annotation 변형은 deep copy 후 수행.** 입력 `DatasetMeta` 는 다른 태스크가
   공유할 수 있으므로 in-place 수정하면 디버깅이 지옥입니다.

6. **PER_SOURCE manipulator 는 `isinstance(input_meta, list)` 가드로 오용을 즉시
   차단.** (현재 executor 는 scope 기반 엄격 분기가 아니라 `accepts_multi_input`
   플래그로만 분기하므로, manipulator 자신이 런타임 타입 체크를 해줘야 안전합니다.)

#### Classification 도메인일 때 추가 주의

`cls_*` manipulator 는 다음 필드를 다룹니다 (detection 경로와 상호 배타적):

- `DatasetMeta.head_schema: list[HeadSchema]` — head 별 class 공간 SSOT. 순서가
  학습 output index 이므로 임의 정렬·dedup 금지. 명시적 reorder manipulator
  (`cls_reorder_classes`) 로만 순서를 바꿉니다.
- `DatasetMeta.categories` 는 classification 에선 **빈 리스트** 로 둡니다.
- `ImageRecord.labels: dict[head_name, list[class_name]]` — single-label head 도
  리스트로 통일.
- `ImageRecord.sha: str` — SHA-1 hex. 파일명 규약은 `images/{sha}.{ext}`.
  annotation-only 변형(label rename 등) 은 sha 를 유지해야 하며, 바이너리 변형
  augment 를 나중에 도입하면 sha 재계산 + file_name 갱신을 manipulator 안에서
  처리해야 합니다.
- `ImageRecord.annotations` 는 classification 에선 **비어 있습니다**.

Detection·Classification 양쪽에 쓰일 수 있는 공용 연산은 현재 설계상
없습니다 — 각 도메인마다 별도 manipulator 를 만듭니다.

### 3-2. Seed 마이그레이션

`backend/migrations/versions/<n>_seed_<name>.py`. 기존 시드 마이그레이션
(`002_seed_manipulators.py`, `010_seed_cls_manips.py`) 의 `_build_manipulator_seed_record`
헬퍼를 참고합니다.

```python
"""seed det_blur_image

Revision ID: 015_seed_det_blur_image
Revises: 014_det_prefix_rename
Create Date: 2026-04-16
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Sequence, Union

from alembic import op

revision: str = "015_seed_det_blur_image"
down_revision: Union[str, None] = "014_det_prefix_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO manipulators (
            id, name, category, scope,
            compatible_task_types, compatible_annotation_fmts,
            output_annotation_fmt, params_schema,
            description, status, version, created_at
        ) VALUES (
            '{uuid.uuid4()}',
            'det_blur_image',
            'AUGMENT',
            '{json.dumps(["PER_SOURCE", "POST_MERGE"])}'::jsonb,
            '{json.dumps(["DETECTION"])}'::jsonb,
            '{json.dumps(["COCO", "YOLO"])}'::jsonb,
            NULL,
            '{json.dumps({
                "radius": {
                    "type": "number",
                    "label": "blur 반경 (px)",
                    "default": 3.0,
                    "required": True,
                },
            })}'::jsonb,
            'Gaussian blur 적용 (annotation 불변)',
            'ACTIVE',
            '1.0.0',
            '{datetime.utcnow().isoformat()}'
        );
    """)


def downgrade() -> None:
    op.execute("DELETE FROM manipulators WHERE name = 'det_blur_image';")
```

**필드 계약**:

| 컬럼 | 값 |
|---|---|
| `name` | Python `UnitManipulator.name` 과 정확히 일치 (prefix 포함) |
| `category` | 팔레트 섹션/색상/이모지. 현재 허용: `ANNOTATION_FILTER` / `IMAGE_FILTER` / `FORMAT_CONVERT` / `SAMPLE` / `REMAP` / `AUGMENT` / `MERGE` / `SCHEMA` (cls 전용). 새 카테고리를 추가하면 `frontend/src/pipeline-sdk/styles.ts` 의 `CATEGORY_STYLE` 에도 스타일을 추가. |
| `scope` | JSONB 리스트. `["PER_SOURCE"]`, `["POST_MERGE"]`, 또는 `["PER_SOURCE","POST_MERGE"]` 중 하나. merge 계열만 POST_MERGE. |
| `compatible_task_types` | JSONB 리스트. `["DETECTION"]`, `["CLASSIFICATION"]`, 혹은 둘 다. 에디터 taskType 과 교집합이 없으면 팔레트에서 숨겨짐. |
| `compatible_annotation_fmts` | JSONB 리스트. detection 은 `["COCO","YOLO"]` 등. classification 은 `null` 허용 (manifest 는 내부 규약이므로 무의미). |
| `output_annotation_fmt` | format_convert 계열에서만 `"COCO"`/`"YOLO"` 로 설정. 통일포맷 도입 후 사용처가 좁아졌지만 기존 필드 유지. 일반 manipulator 는 `NULL`. |
| `params_schema` | JSONB. 프론트 `DynamicParamForm` 이 UI 를 자동 생성. `type` 은 `number`·`text`·`textarea`·`select`·`key_value` 등. `default` 가 있으면 팔레트 생성 시 초기값으로 주입. |
| `status` | `ACTIVE` / `EXPERIMENTAL` / `DEPRECATED`. 프론트가 ACTIVE 만 노출하도록 확장 가능. |

### 3-3. 검증

```bash
make migrate
docker exec mlplatform-backend python -c \
  "from lib.manipulators import MANIPULATOR_REGISTRY; print('det_blur_image' in MANIPULATOR_REGISTRY)"
```

**Celery 워커는 `--reload` 없음 → 파일만 바뀌면 안 되고 컨테이너 재시작 필수:**

```bash
docker compose restart celery-worker backend
```

프론트는 별도 빌드 없이 manipulator API 를 React Query 로 폴링하므로, 브라우저
새로고침 후 팔레트에 자동 노출됩니다. 단 60 초 staleTime 이 있으니 즉시 반영이
필요하면 해당 query key 를 invalidate 하세요.

### 3-4. 새 `operation` 을 추가한 경우 — ImageMaterializer 분기

이미지 바이너리 변형이 포함된 manipulator 라면 `build_image_manipulation` 이
반환하는 `ImageManipulationSpec.operation` 문자열이 실제로 처리되도록
`backend/lib/pipeline/image_materializer.py` 의 `_apply_image_operation` 에 분기를
추가합니다.

```python
def _apply_image_operation(self, img, spec):
    if spec.operation == "rotate_image":
        return self._apply_rotate(img, spec.params)
    if spec.operation == "mask_region":
        return self._apply_mask_region(img, spec.params)
    if spec.operation == "gaussian_blur":          # ← 추가
        return self._apply_gaussian_blur(img, spec.params)

    logger.warning("미지원 이미지 변환 operation: %s (건너뜀)", spec.operation)
    return img
```

빠뜨리면 이미지는 단순 복사되고 로그에 `미지원 이미지 변환 operation` 경고만
남습니다. annotation 은 이미 변형된 상태이므로 메타데이터와 실제 픽셀이
**불일치** 하는 상태가 되니 특히 위험합니다.

### 3-5. 체크리스트 (Manipulator 추가)

- [ ] `backend/lib/manipulators/<prefix>_<name>.py` — UnitManipulator 서브클래스 작성
- [ ] `name` property 가 인스턴스 생성 직후 호출 가능한지 확인
- [ ] PER_SOURCE 전용이면 `isinstance(input_meta, list)` 가드
- [ ] POST_MERGE 전용이면 `accepts_multi_input = True` 선언
- [ ] 이미지 변형 포함이면 `operation` 문자열 양쪽(dict + ImageManipulationSpec) 동기화
- [ ] 이미지 변형 포함이면 `image_materializer._apply_image_operation` 에 분기 추가
- [ ] `backend/migrations/versions/<n>_seed_<name>.py` 작성, `down_revision` 체인 확인
- [ ] `make migrate` 및 `MANIPULATOR_REGISTRY` 에 키 등록 확인
- [ ] `docker compose restart backend celery-worker` — 워커 프로세스 교체
- [ ] 프론트 팔레트에 등장하고 DynamicParamForm 이 의도대로 렌더되는지 확인
- [ ] (선택) 고유 이모지가 필요하면 `frontend/src/pipeline-sdk/styles.ts` 의
      `MANIPULATOR_EMOJI` 에 추가

---

## 4. B경로 — 새 NodeKind 추가

팔레트에 상주하는 특수 노드(`split` 같은) 를 도입하는 경우입니다. Manipulator 와
달리 프론트 SDK 의 contract (types → definition → registry) 를 건드리므로
변경 지점이 늘어납니다.

현재 NodeKind 는 5 종 고정: `dataLoad`, `operator`, `merge`, `save`, `placeholder`.

### 4-1. `NodeDataByKind` 에 타입 추가

`frontend/src/pipeline-sdk/types.ts`:

```ts
export interface SplitNodeData extends BaseNodeData {
  type: 'split'
  ratio: number    // 0 < r < 1
  seed?: number
}

export interface NodeDataByKind {
  dataLoad: DataLoadNodeData
  operator: OperatorNodeData
  merge: MergeNodeData
  save: SaveNodeData
  placeholder: PlaceholderNodeData
  split: SplitNodeData              // ← 추가
}
```

> `NodeDataByKind` 의 키 집합은 **단일 진실 공급원**입니다. `NodeKind` 타입이
> 여기서 파생됩니다. 아래 registry assertion 이 이 키 집합과 런타임 비교합니다.

### 4-2. Definition 파일 작성

`frontend/src/pipeline-sdk/definitions/splitDefinition.tsx`:

```tsx
import type { NodeDefinition } from '../types'

export const splitDefinition: NodeDefinition<'split'> = {
  kind: 'split',

  palette: {
    section: 'basic',
    label: 'Split',
    color: '#8e44ad',
    emoji: '✂️',
    order: 25,
    createDefaultData: (_ctx) => ({
      type: 'split',
      ratio: 0.8,
    }),
  },

  NodeComponent: SplitNodeComponent,
  PropertiesComponent: SplitPropertiesComponent,

  validate(data, ctx) {
    const errors = []
    if (!(data.ratio > 0 && data.ratio < 1)) {
      errors.push({ nodeId: ctx.nodeId, message: 'Split 비율은 0 과 1 사이여야 합니다.' })
    }
    const incoming = ctx.edges.filter((e) => e.target === ctx.nodeId)
    if (incoming.length === 0) {
      errors.push({ nodeId: ctx.nodeId, message: 'Split 노드에 입력 연결이 없습니다.' })
    }
    return errors
  },

  toConfigContribution(data, ctx) {
    const inputs = buildInputsFromIncoming(ctx)   // mergeDefinition 에서 export
    const taskKey = `task_${ctx.nodeId}`
    return {
      tasks: {
        [taskKey]: {
          operator: 'split',
          inputs,
          params: { ratio: data.ratio, ...(data.seed ? { seed: data.seed } : {}) },
        },
      },
      outputRef: taskKey,
    }
  },

  matchFromConfig(ctx) {
    const { config, claimedTaskKeys } = ctx
    const restored = []
    for (const [taskKey, taskConfig] of Object.entries(config.tasks)) {
      if (claimedTaskKeys.has(taskKey)) continue
      if (taskConfig.operator !== 'split') continue
      const nodeId = taskKey.startsWith('task_') ? taskKey.slice(5) : taskKey
      restored.push({
        nodeId,
        data: {
          type: 'split' as const,
          ratio: Number(taskConfig.params.ratio ?? 0.8),
          seed: taskConfig.params.seed as number | undefined,
        },
        ownedTaskKeys: [taskKey],
      })
    }
    return restored
  },

  matchIssueField(issue, _data, nodeId) {
    return issue.field.startsWith(`tasks.task_${nodeId}`)
  },
}
```

### 4-3. bootstrap + registry 갱신

`frontend/src/pipeline-sdk/bootstrap.ts`:

```ts
import { splitDefinition } from './definitions/splitDefinition'
registerNodeDefinition(splitDefinition)
```

`frontend/src/pipeline-sdk/registry.ts` 의 `assertRegistryCompleteness` 내부
하드코딩된 expected 배열:

```ts
const expected: NodeKind[] = ['dataLoad', 'operator', 'merge', 'save', 'placeholder', 'split']
```

`frontend/src/pipeline-sdk/engine/configToGraph.ts` 의 `MATCH_ORDER` 배열에도
추가 (placeholder 보다 앞, save 보다 앞에 배치 — placeholder 는 마지막에
leftover 를 쓸어담아야 합니다):

```ts
const MATCH_ORDER: NodeKind[] = ['dataLoad', 'operator', 'merge', 'split', 'placeholder', 'save']
```

> **이 네 곳 중 한 군데라도 누락되면 부팅 시 `assertRegistryCompleteness` 가
> 즉시 throw 합니다.** 이는 의도된 감시 포인트이므로 완화하지 말고 전부 채우세요.

### 4-4. `matchFromConfig` 작성 규칙 (가장 실수하기 쉬운 지점)

Config → Graph 역변환은 `MATCH_ORDER` 순서대로 각 definition 의 `matchFromConfig`
를 호출하며, 각 definition 은 **자신이 소유할 task_key / source_dataset_id 를 claim**
해야 합니다.

- `ownedTaskKeys: string[]` — 이 노드가 흡수한 `config.tasks` 의 키
- `ownedSourceDatasetIds?: string[]` — 이 노드가 흡수한 `source:<id>` 참조

이후 definition 은 `matchCtx.claimedTaskKeys` / `claimedSourceDatasetIds` 를 보고
중복 claim 을 피합니다. **마지막에 `placeholder` 가 아직 claim 되지 않은 task 를
전부 흡수** 하므로 task 유실 없이 복원 가능합니다.

현재 claim 분배:

| Definition | 무엇을 claim 하는가 |
|---|---|
| `dataLoad` | `config.tasks[*].inputs` 중 `source:<id>` 토큰 + `passthrough_source_dataset_id` |
| `operator` | MANIPULATOR_REGISTRY 에 등록된 operator 로 시작하는 task (단, `det_merge_datasets` 제외) |
| `merge` | `operator === 'det_merge_datasets'` 인 task |
| `save` | task claim 없음, `config.name` / `config.output` 으로부터 싱글톤 생성 |
| `placeholder` | 앞 단계에서 claim 되지 않은 나머지 task 전부 |

> 향후 detseg_merge_datasets / cls_merge_datasets 가 도입되면 merge definition 의
> claim 조건을 `operator` prefix 기반으로 확장하거나, 도메인별 merge definition
> 을 분리하게 됩니다. 이 결정은 앞으로 실제 필요 시점에 내리며, 현재는 detection
> 의 `det_merge_datasets` 하나만 특수 취급합니다.

### 4-5. `buildInputsFromIncoming` 재사용

`frontend/src/pipeline-sdk/definitions/mergeDefinition.tsx` 에서 export 하는
헬퍼로, React Flow edge 배열을 `TaskConfig.inputs` 토큰 배열로 변환합니다.

```
dataLoad source → `source:<datasetId>`
operator/merge/placeholder/split → `task_<nodeId>`
```

새 NodeKind 가 "다른 노드에 의해 입력으로 참조될 수 있다" 면 이 헬퍼의 분기를
확장해야 합니다. 안 그러면 그래프 직렬화에서 조용히 누락됩니다.

### 4-6. 체크리스트 (새 NodeKind)

- [ ] `types.ts` 의 `NodeDataByKind` 에 새 키·타입 추가
- [ ] `definitions/<kind>Definition.tsx` 작성 (NodeComponent / PropertiesComponent / validate / toConfigContribution / matchFromConfig / matchIssueField)
- [ ] `bootstrap.ts` 에서 `registerNodeDefinition(...)` 호출
- [ ] `registry.ts` 의 `expected` 배열에 kind 추가
- [ ] `engine/configToGraph.ts` 의 `MATCH_ORDER` 에 kind 추가 (placeholder 앞)
- [ ] `matchFromConfig` 의 claim 범위가 정확한지 (다른 definition 과 겹치지 않는지) 수동 검증
- [ ] 하위 노드가 이 노드의 출력을 참조할 수 있다면 `buildInputsFromIncoming` 의 허용 `source.type` 분기에 추가
- [ ] 백엔드에 대응되는 operator/실행 로직이 필요하면 — `TaskConfig.operator` 로
      전달되는 문자열을 DAG executor 가 어떻게 해석할지 설계 (manipulator
      경로로 내릴지, executor 에 특수 분기를 둘지)

---

## 5. 자주 걸리는 함정

**Q. manipulator 파일을 추가했는데 registry 에 안 나타난다.**
A. 90% 는 `name` property 가 인스턴스 생성 직후 호출되지 않는 경우입니다.
`__init__` 에 필수 인자를 넣었거나, `name` 이 다른 속성에 의존하면 `_discover_manipulator_classes`
의 `try: instance = obj(); instance.name / except: continue` 에서 조용히
스킵됩니다. 키를 모듈 상수로 빼고 `@property` 안에서 그걸 그대로 반환하게 하세요.

**Q. 이미지 변형 manipulator 를 돌렸는데 annotation 은 바뀌었는데 픽셀은 그대로다.**
A. `ImageManipulationSpec.operation` 문자열이 `image_materializer._apply_image_operation`
의 `if spec.operation == "..."` 분기 어디에도 매칭되지 않으면 경고만 찍히고
스킵됩니다. `transform_annotation` 내부 dict 의 `"operation"` 값과
`build_image_manipulation` 의 `ImageManipulationSpec.operation` 이 **동일한 문자열**
이어야 하고, 그 문자열이 materializer 에도 등록돼 있어야 합니다. operator
네임스페이스(prefix 적용 대상) 와 operation 네임스페이스(prefix 적용 대상 아님)
를 섞지 않도록 주의.

**Q. seed 마이그레이션은 돌렸는데 파이프라인 실행 시 "등록되지 않은 manipulator" 오류가 난다.**
A. Celery 워커는 자동 reload 가 없습니다. `docker compose restart celery-worker`
로 프로세스를 교체하세요. backend 컨테이너는 uvicorn `--reload` 덕에 반영되지만
실제 실행은 워커에서 돌아갑니다.

**Q. placeholder 노드가 자꾸 생긴다.**
A. JSON 에 DB 에 없는 operator 이름이 있다는 뜻입니다. seed 마이그레이션 누락,
prefix rename 누락, 또는 operator 네임스페이스 오타(prefix 규약 위반) 를 의심하세요.
placeholder 는 유실 방지가 목적이며 `validate` 가 실행을 차단합니다.

**Q. 그래프 → JSON 변환에서 "Save 노드가 없습니다" 가 뜬다.**
A. Save 노드가 `rootParts.name` 과 `rootParts.output` 을 기여하지 못한 경우입니다.
`toConfigContribution` 이 `{root: {name, output, ...}}` 를 반환하는지 확인하세요.
복수 개 save 노드가 있으면 나중 것이 덮어씁니다 — 의도된 동작이지만 UX 상
`validate` 로 "Save 1개만 허용" 을 사전에 막는 쪽이 낫습니다.

**Q. 기존 operator 에 params 필드를 추가했는데 옛날 JSON 을 불러오면 검증에서 튕긴다.**
A. `PipelineConfig.schema_version` 을 올리고 `matchFromConfig` 에서 버전별 분기를
넣거나, 더 안전하게는 `params_schema` 에 `default` 를 부여해 누락 필드가 자동
채워지도록 합니다. 현재 `CURRENT_SCHEMA_VERSION = 1` (`engine/graphToConfig.ts`).

**Q. Classification manipulator 인데 팔레트에 안 보인다.**
A. 에디터 URL 의 `taskType` 쿼리 파라미터가 `DETECTION` 인지 확인. 또한 seed
의 `compatible_task_types` 에 `"CLASSIFICATION"` 이 들어있어야 하고,
dataLoad 노드는 그룹의 `task_types` 에 `CLASSIFICATION` 이 포함된 경우에만
노출됩니다.

**Q. operator 이름을 rename 했는데 기존 실행 이력이 깨진다.**
A. `pipeline_executions.config` 는 JSONB 스냅샷이라 이름이 박제돼 있습니다.
rename 마이그레이션에서 `REPLACE(config::text, '"old_name"', '"new_name"')::jsonb`
로 함께 갱신하세요 (014 마이그레이션이 detection 14종에 대해 이미 해 놓은 패턴).

---

## 6. 파일 수정 지점 요약표

Manipulator 추가:

| 파일 | 필수 여부 | 내용 |
|---|---|---|
| `backend/lib/manipulators/<prefix>_<name>.py` | 필수 | UnitManipulator 서브클래스 |
| `backend/migrations/versions/<n>_seed_<name>.py` | 필수 | DB 시드 |
| `backend/lib/pipeline/image_materializer.py` | 이미지 변형 시 | `_apply_image_operation` 분기 추가 |
| `frontend/src/pipeline-sdk/styles.ts` | 선택 | 고유 이모지 |

새 NodeKind 추가 (위 항목에 더해):

| 파일 | 내용 |
|---|---|
| `frontend/src/pipeline-sdk/types.ts` | `NodeDataByKind` 에 키·인터페이스 |
| `frontend/src/pipeline-sdk/definitions/<kind>Definition.tsx` | NodeDefinition 구현 |
| `frontend/src/pipeline-sdk/bootstrap.ts` | `registerNodeDefinition` |
| `frontend/src/pipeline-sdk/registry.ts` | `expected` 배열 |
| `frontend/src/pipeline-sdk/engine/configToGraph.ts` | `MATCH_ORDER` 배열 |
| `frontend/src/pipeline-sdk/definitions/mergeDefinition.tsx` | `buildInputsFromIncoming` 분기 (출력이 참조되는 경우) |
| backend 실행 로직 | operator 문자열 처리 경로 설계 (manipulator 일반 경로 or executor 특수 분기) |

---

## 7. 유지보수 메모

- 이 가이드는 코드와 어긋나면 코드를 따릅니다. 구조가 바뀌면 이 문서도 같이
  갱신하세요. 특히 `NodeKind` 증감, `MATCH_ORDER`, operation 디스패치 분기,
  category 목록, prefix 규약이 변하면 반드시 이 문서에 반영합니다.
- 관련 설계 배경은 `docs/pipeline-node-sdk-design_truth-db.md` 에 있습니다.
  (있다면) 그 문서가 "왜 이 구조인가" 를, 이 문서가 "어떻게 추가하는가" 를
  다룹니다.
