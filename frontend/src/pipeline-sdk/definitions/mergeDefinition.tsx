/**
 * MergeDefinition — 다중 입력을 받아 단일 출력을 생성하는 병합 노드.
 *
 * 에디터의 taskType 에 따라 operator 가 자동 결정된다:
 *   DETECTION      → det_merge_datasets
 *   CLASSIFICATION → cls_merge_datasets
 * 두 operator 모두 accepts_multi_input=True 로 설정돼 DAG executor 가
 * list[DatasetMeta] 를 직접 전달한다. 2개 이상 입력 필수.
 *
 * cls_merge_datasets 는 `objective_n_plan_7th.md §2-11` 정책에 따라 3개 옵션을
 * params 로 받는다:
 *   - on_head_mismatch      : error | fill_empty
 *   - on_class_set_mismatch : error | multi_label_union
 *   - on_label_conflict     : drop_image | merge_if_compatible
 * PropertiesComponent 에서 DynamicParamForm 으로 렌더링하며, on_class_set_mismatch
 * 를 multi_label_union 로 변경할 때는 "학습에 영향" 경고 모달을 띄워 사용자에게
 * 최종 결정을 맡긴다 (§2-11-4 요구사항).
 */
import { memo, useMemo } from 'react'
import { useEdges } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Typography, Tag, Divider, Modal } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useNodeData, useSetNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import DynamicParamForm from '@/components/pipeline/DynamicParamForm'
import { manipulatorsApi } from '@/api/pipeline'
import type { NodeDefinition } from '../types'
import type { MergeNodeData } from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'

const { Text, Paragraph } = Typography

const MERGE_COLOR = '#9254de'
const MERGE_EMOJI = '🔗'

/** Merge 기본 노드가 점유하는 operator 집합 (palette/matchFromConfig 등에서 공용). */
export const MERGE_OPERATORS: ReadonlySet<string> = new Set([
  'det_merge_datasets',
  'cls_merge_datasets',
])

/** taskType → merge operator 매핑. 알 수 없는 값은 detection 기본값으로 폴백. */
function resolveMergeOperator(taskType: string): 'det_merge_datasets' | 'cls_merge_datasets' {
  if (taskType === 'CLASSIFICATION') return 'cls_merge_datasets'
  return 'det_merge_datasets'
}

const MergeNodeComponent = memo(function MergeNodeInner({ id }: NodeProps) {
  const nodeData = useNodeData<'merge'>(id)
  const allEdges = useEdges()

  const connectedInputCount = useMemo(
    () => allEdges.filter((e) => e.target === id).length,
    [allEdges, id],
  )
  // 최소 2개, 연결된 수 + 1개 여분 핸들
  const handleCount = Math.max(2, connectedInputCount + 1)

  if (!nodeData) return null

  return (
    <NodeShell
      color={MERGE_COLOR}
      emoji={MERGE_EMOJI}
      headerLabel="Merge"
      inputs={{ count: handleCount }}
      outputs="single"
      issues={nodeData.validationIssues ?? []}
      minWidth={180}
    >
      <Text type="secondary" style={{ fontSize: 11 }}>
        {connectedInputCount}개 입력 연결됨
      </Text>
    </NodeShell>
  )
})

/** cls_merge_datasets params 중 하나의 key. manipulator API 응답의 키와 1:1. */
const CLASS_SET_MISMATCH_KEY = 'on_class_set_mismatch'
const MULTI_LABEL_UNION_VALUE = 'multi_label_union'

function MergePropertiesComponent({
  nodeId,
  data,
}: {
  nodeId: string
  data: MergeNodeData
}) {
  const setNodeData = useSetNodeData()
  const isClassification = data.operator === 'cls_merge_datasets'

  // cls_merge_datasets 인 경우에만 params_schema 가 필요. detection merge 는 params 가 없다.
  const { data: manipulatorsResponse } = useQuery({
    queryKey: ['manipulators-for-merge'],
    queryFn: () => manipulatorsApi.list().then((r) => r.data),
    staleTime: 60_000,
    enabled: isClassification,
  })

  const clsMergeManipulator: Manipulator | undefined = useMemo(() => {
    if (!isClassification) return undefined
    return manipulatorsResponse?.items.find((m) => m.name === 'cls_merge_datasets')
  }, [manipulatorsResponse, isClassification])

  const paramsSchema = (clsMergeManipulator?.params_schema ?? null) as
    | Record<string, { type?: string; options?: string[]; default?: unknown }>
    | null

  /**
   * DynamicParamForm 의 onChange 인터셉터.
   *
   * on_class_set_mismatch 을 multi_label_union 으로 바꾸려 하면 "학습 영향" 경고
   * 모달로 확인을 받는다. 취소를 누르면 기존 값을 유지한다 (상태를 갱신하지 않음).
   * 그 외 필드 변경과 복원 방향(error 로 되돌리기) 은 바로 적용.
   */
  const handleParamsChange = (newParams: Record<string, unknown>) => {
    const previousValue = (data.params ?? {})[CLASS_SET_MISMATCH_KEY]
    const nextValue = newParams[CLASS_SET_MISMATCH_KEY]
    const promotingToMultiLabel =
      previousValue !== MULTI_LABEL_UNION_VALUE &&
      nextValue === MULTI_LABEL_UNION_VALUE

    if (!promotingToMultiLabel) {
      setNodeData(nodeId, { ...data, params: newParams })
      return
    }

    Modal.confirm({
      title: 'Class 집합 불일치를 multi_label_union 으로 승격하시겠습니까?',
      okText: '승격 적용',
      cancelText: '취소',
      okButtonProps: { danger: true },
      width: 520,
      content: (
        <div style={{ fontSize: 13, lineHeight: 1.6 }}>
          <Paragraph style={{ marginBottom: 6 }}>
            이 옵션을 켜면 입력들이 class 집합에서 서로 다르더라도 병합이 진행되며,
            해당 head 는 <b>multi_label=True 로 강제 승격</b> 됩니다.
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            결과 데이터셋에서 원래 single-label 이던 head 도 multi-label 출력으로
            취급되므로 <b>학습 출력 head 구성·loss 에 영향</b>을 줄 수 있습니다.
          </Paragraph>
          <Paragraph style={{ marginBottom: 0, color: '#8c8c8c' }}>
            의미상 동일한 class 이름이 다르게 표기돼 있는 경우에는
            cls_rename_class 로 먼저 정리한 뒤 merge 하는 편이 안전합니다.
          </Paragraph>
        </div>
      ),
      onOk: () => {
        setNodeData(nodeId, { ...data, params: newParams })
      },
    })
  }

  return (
    <>
      <Tag color="purple">Merge</Tag>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
        {data.operator}
      </Text>
      <Divider style={{ margin: '8px 0' }} />
      <Text type="secondary" style={{ fontSize: 12 }}>
        2개 이상의 데이터셋을 병합합니다. 연결된 입력이 자동으로 inputs에 매핑됩니다.
      </Text>
      {isClassification ? (
        paramsSchema ? (
          <DynamicParamForm
            paramsSchema={paramsSchema as Record<string, never>}
            params={data.params as Record<string, unknown>}
            onChange={handleParamsChange}
          />
        ) : (
          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 8 }}>
            병합 옵션 스키마를 불러오는 중입니다…
          </Text>
        )
      ) : null}
    </>
  )
}

export const mergeDefinition: NodeDefinition<'merge'> = {
  kind: 'merge',
  palette: {
    section: 'basic',
    label: 'Merge (병합)',
    color: MERGE_COLOR,
    emoji: MERGE_EMOJI,
    order: 20,
    createDefaultData: (ctx) => ({
      type: 'merge',
      // taskType 에 맞는 merge operator 를 고른다.
      operator: resolveMergeOperator(ctx.taskType),
      params: {},
      inputCount: 2,
    }),
  },
  NodeComponent: MergeNodeComponent,
  PropertiesComponent: MergePropertiesComponent,

  validate(data, ctx) {
    const errors = []
    const incoming = ctx.edges.filter((e) => e.target === ctx.nodeId)
    if (incoming.length === 0) {
      errors.push({ nodeId: ctx.nodeId, message: '"Merge" 노드에 입력 연결이 없습니다.' })
    } else if (incoming.length < 2) {
      errors.push({ nodeId: ctx.nodeId, message: 'Merge 노드는 2개 이상의 입력이 필요합니다.' })
    }
    return errors
  },

  toConfigContribution(data, ctx) {
    const inputs = buildInputsFromIncoming(ctx)
    const taskKey = `task_${ctx.nodeId}`
    return {
      tasks: {
        [taskKey]: {
          // 노드 생성 시 taskType 으로 결정된 operator 를 그대로 사용.
          operator: data.operator,
          inputs,
          params: (data.params as Record<string, unknown>) ?? {},
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
      // detection / classification 양쪽 merge operator 모두 Merge 기본 노드로 복원.
      if (!MERGE_OPERATORS.has(taskConfig.operator)) continue
      const nodeId = taskKey.startsWith('task_') ? taskKey.slice(5) : taskKey
      const data: MergeNodeData = {
        type: 'merge',
        operator: taskConfig.operator as MergeNodeData['operator'],
        params: { ...taskConfig.params },
        inputCount: taskConfig.inputs.length,
      }
      restored.push({
        nodeId,
        data,
        ownedTaskKeys: [taskKey],
      })
    }
    return restored
  },

  matchIssueField(issue, _data, nodeId) {
    return issue.field.startsWith(`tasks.task_${nodeId}`)
  },
}

/**
 * 들어오는 엣지로부터 PipelineConfig TaskConfig.inputs 토큰 배열을 구성.
 * DataLoad 노드 → `source:<split_id>`, operator/merge/placeholder → `task_<nodeId>`.
 */
function buildInputsFromIncoming(ctx: {
  incomingEdges: { source: string }[]
  getNodeData: (id: string) =>
    | { type?: string; splitId?: string | null }
    | undefined
}): string[] {
  const inputs: string[] = []
  for (const edge of ctx.incomingEdges) {
    const source = ctx.getNodeData(edge.source)
    if (!source) continue
    if (source.type === 'dataLoad' && source.splitId) {
      inputs.push(`source:${source.splitId}`)
    } else if (source.type === 'operator' || source.type === 'merge' || source.type === 'placeholder') {
      inputs.push(`task_${edge.source}`)
    }
  }
  return inputs
}

export { buildInputsFromIncoming }
