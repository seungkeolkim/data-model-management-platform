/**
 * PlaceholderDefinition — registry에 없는 operator를 열람용으로 복원하는 노드.
 *
 * 용도:
 *   - 과거 PipelineConfig JSON을 재실행은 못 하더라도 시각적으로 확인할 수 있도록
 *   - DAG schema v0/v1/v2... 마이그레이션이 아직 없을 때 안전 착륙 지점
 *
 * 동작:
 *   - matchFromConfig: 다른 definition이 점유하지 못한 task를 모두 점유
 *   - validate: 이 노드가 1개라도 있으면 실행 차단 (unknown operator)
 *   - toConfigContribution: 원본 operator/params/inputs 그대로 재기입
 */
import { memo } from 'react'
import type { NodeProps } from '@xyflow/react'
import { Typography, Tag, Divider } from 'antd'
import { useNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import type { NodeDefinition } from '../types'
import type { PlaceholderNodeData } from '../types'

const { Text } = Typography

const PLACEHOLDER_COLOR = '#ff4d4f'
const PLACEHOLDER_EMOJI = '⚠️'

const PlaceholderNodeComponent = memo(function PlaceholderNodeInner({ id }: NodeProps) {
  const nodeData = useNodeData<'placeholder'>(id)
  if (!nodeData) return null

  return (
    <NodeShell
      color={PLACEHOLDER_COLOR}
      emoji={PLACEHOLDER_EMOJI}
      headerLabel="Unknown Operator"
      inputs={{ count: Math.max(1, nodeData.originalInputs.length) }}
      outputs="single"
      issues={nodeData.validationIssues ?? []}
      minWidth={220}
    >
      <Text type="danger" style={{ fontSize: 11, display: 'block' }}>
        {nodeData.originalOperator}
      </Text>
      <Text type="secondary" style={{ fontSize: 10, display: 'block', marginTop: 2 }}>
        {nodeData.reason}
      </Text>
      {Object.keys(nodeData.originalParams).length > 0 && (
        <div style={{ marginTop: 4, fontSize: 10, color: '#8c8c8c', maxHeight: 80, overflowY: 'auto' }}>
          <pre style={{ margin: 0, fontSize: 10 }}>
            {JSON.stringify(nodeData.originalParams, null, 2)}
          </pre>
        </div>
      )}
    </NodeShell>
  )
})

function PlaceholderPropertiesComponent({ data }: { nodeId: string; data: PlaceholderNodeData }) {
  return (
    <>
      <Tag color="error">Unknown</Tag>
      <Divider style={{ margin: '8px 0' }} />
      <Text type="danger" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
        registry에 없는 operator: {data.originalOperator}
      </Text>
      <Text type="secondary" style={{ fontSize: 11 }}>
        {data.reason} 이 노드를 포함한 파이프라인은 실행할 수 없습니다. 노드를 삭제하거나
        유효한 operator로 교체한 뒤 실행하세요.
      </Text>
      <Divider style={{ margin: '8px 0' }} />
      <Text strong style={{ fontSize: 11 }}>원본 params</Text>
      <pre style={{ fontSize: 10, background: '#fafafa', padding: 6, borderRadius: 4, marginTop: 4 }}>
        {JSON.stringify(data.originalParams, null, 2)}
      </pre>
    </>
  )
}

export const placeholderDefinition: NodeDefinition<'placeholder'> = {
  kind: 'placeholder',
  // 팔레트에서는 만들 수 없음 — 오직 matchFromConfig 복원 경로로만 생성.
  NodeComponent: PlaceholderNodeComponent,
  PropertiesComponent: PlaceholderPropertiesComponent,

  validate(_data, ctx) {
    return [
      {
        nodeId: ctx.nodeId,
        message: '등록되지 않은 operator가 포함되어 있습니다. 이 파이프라인은 실행할 수 없습니다.',
      },
    ]
  },

  // 원본 operator/params/inputs를 그대로 재기입. 어차피 서버 검증에서 튕긴다.
  toConfigContribution(data, ctx) {
    const taskKey = `task_${ctx.nodeId}`
    return {
      tasks: {
        [taskKey]: {
          operator: data.originalOperator,
          inputs: data.originalInputs,
          params: data.originalParams,
        },
      },
      outputRef: taskKey,
    }
  },

  // 다른 definition이 점유하지 못한 task 전부를 Placeholder로 복원.
  matchFromConfig(ctx) {
    const { config, manipulatorMap, claimedTaskKeys } = ctx
    const restored = []
    for (const [taskKey, taskConfig] of Object.entries(config.tasks)) {
      if (claimedTaskKeys.has(taskKey)) continue
      // manipulator registry에 없고 det_merge_datasets도 아닌 경우
      const isKnown =
        taskConfig.operator === 'det_merge_datasets' || !!manipulatorMap[taskConfig.operator]
      if (isKnown) continue
      const nodeId = taskKey.startsWith('task_') ? taskKey.slice(5) : taskKey
      const data: PlaceholderNodeData = {
        type: 'placeholder',
        originalOperator: taskConfig.operator,
        originalParams: { ...taskConfig.params },
        originalInputs: [...taskConfig.inputs],
        reason: 'MANIPULATOR_REGISTRY에 등록되지 않은 operator입니다.',
      }
      restored.push({ nodeId, data, ownedTaskKeys: [taskKey] })
    }
    return restored
  },

  matchIssueField(issue, _data, nodeId) {
    return issue.field.startsWith(`tasks.task_${nodeId}`)
  },
}
