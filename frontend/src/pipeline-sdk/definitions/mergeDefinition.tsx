/**
 * MergeDefinition — 다중 입력을 받아 단일 출력을 생성하는 병합 노드.
 *
 * operator='merge_datasets' 고정. 2개 이상 입력 필수.
 */
import { memo, useMemo } from 'react'
import { useEdges } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Typography, Tag, Divider } from 'antd'
import { useNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import type { NodeDefinition } from '../types'
import type { MergeNodeData } from '@/types/pipeline'

const { Text } = Typography

const MERGE_COLOR = '#9254de'
const MERGE_EMOJI = '🔗'

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

function MergePropertiesComponent() {
  return (
    <>
      <Tag color="purple">Merge</Tag>
      <Divider style={{ margin: '8px 0' }} />
      <Text type="secondary" style={{ fontSize: 12 }}>
        2개 이상의 데이터셋을 병합합니다. 연결된 입력이 자동으로 inputs에 매핑됩니다.
      </Text>
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
    createDefaultData: () => ({
      type: 'merge',
      operator: 'merge_datasets',
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
          operator: 'merge_datasets',
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
      if (taskConfig.operator !== 'merge_datasets') continue
      const nodeId = taskKey.startsWith('task_') ? taskKey.slice(5) : taskKey
      const data: MergeNodeData = {
        type: 'merge',
        operator: 'merge_datasets',
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

/** 들어오는 엣지로부터 PipelineConfig TaskConfig.inputs 토큰 배열을 구성. */
function buildInputsFromIncoming(ctx: {
  incomingEdges: { source: string }[]
  getNodeData: (id: string) => { type?: string; datasetId?: string | null } | undefined
}): string[] {
  const inputs: string[] = []
  for (const edge of ctx.incomingEdges) {
    const source = ctx.getNodeData(edge.source)
    if (!source) continue
    if (source.type === 'dataLoad' && source.datasetId) {
      inputs.push(`source:${source.datasetId}`)
    } else if (source.type === 'operator' || source.type === 'merge' || source.type === 'placeholder') {
      inputs.push(`task_${edge.source}`)
    }
  }
  return inputs
}

export { buildInputsFromIncoming }
