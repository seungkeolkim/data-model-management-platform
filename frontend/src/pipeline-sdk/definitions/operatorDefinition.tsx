/**
 * OperatorDefinition — 범용 단일입력/단일출력 manipulator 노드.
 *
 * 모든 manipulator(format_convert, filter, sample, remap, augment)가 단 하나의
 * kind='operator' definition을 공유한다. 팔레트 항목은 `paletteFromManipulators`가
 * API 응답을 받아 동적으로 확장한다.
 *
 * 다형성은 OperatorNodeData.operator 필드로 표현한다.
 */
import { memo } from 'react'
import type { NodeProps } from '@xyflow/react'
import { Typography, Select, Tag, Divider, Modal } from 'antd'
import { useNodeData, useSetNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import { getCategoryStyle, getManipulatorEmoji } from '../styles'
import { buildInputsFromIncoming } from './mergeDefinition'
import DynamicParamForm from '@/components/pipeline/DynamicParamForm'
import type { NodeDefinition, PaletteItem, CreateContext } from '../types'
import type { OperatorNodeData } from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'

const { Text } = Typography

/** 포맷 변환 노드는 통일포맷 자동 처리로 대체되어 비활성 */
const FORMAT_CONVERT_CATEGORY = 'FORMAT_CONVERT'
/** 백엔드 코드 미구현 manipulator (DB seed만 존재) */
const UNIMPLEMENTED_OPERATORS = ['det_change_compression', 'det_shuffle_image_ids']

/** description("버튼 텍스트 (도움말)") 패턴에서 앞부분만 추출 */
function extractShortLabel(desc: string): string {
  const match = desc.match(/^(.+?)\s*\((.+)\)\s*$/)
  return match ? match[1] : desc
}

/** params_schema의 default 필드를 수집하여 초기 params 구성 */
function buildDefaultParams(schema: Record<string, unknown> | null): Record<string, unknown> {
  if (!schema) return {}
  const defaults: Record<string, unknown> = {}
  for (const [key, field] of Object.entries(schema)) {
    const fieldDef = field as { default?: unknown }
    if (fieldDef.default !== undefined) {
      defaults[key] = fieldDef.default
    }
  }
  return defaults
}

function createOperatorDataFromManipulator(m: Manipulator): OperatorNodeData {
  const paramsSchema = m.params_schema as Record<string, unknown> | null
  return {
    type: 'operator',
    operator: m.name,
    category: m.category,
    label: extractShortLabel(m.description ?? m.name),
    params: buildDefaultParams(paramsSchema),
    paramsSchema,
  }
}

const OperatorNodeComponent = memo(function OperatorNodeInner({ id }: NodeProps) {
  const nodeData = useNodeData<'operator'>(id)
  const setNodeData = useSetNodeData()
  if (!nodeData) return null

  const style = getCategoryStyle(nodeData.category)
  const emoji = getManipulatorEmoji(nodeData.operator, nodeData.category)

  // params 요약 — select는 인라인 드롭다운, key_value는 "old → new" 렌더링.
  const paramsSchema = (nodeData.paramsSchema ?? {}) as Record<string, { label?: string; type?: string; options?: string[] }>
  const paramEntries = Object.entries(nodeData.params ?? {}).filter(
    ([, val]) => val !== '' && val !== null && val !== undefined,
  )
  const selectEntries = Object.entries(paramsSchema).filter(([, schema]) => schema.type === 'select')
  const keyValueEntries = paramEntries.filter(
    ([key, val]) => typeof val === 'object' && val !== null && !Array.isArray(val) && paramsSchema[key]?.type !== 'select',
  )
  const nonKeyValueEntries = paramEntries.filter(
    ([key, val]) =>
      !(typeof val === 'object' && val !== null && !Array.isArray(val)) &&
      paramsSchema[key]?.type !== 'select',
  )

  const handleSelectChange = (paramKey: string, value: string) => {
    setNodeData(id, { ...nodeData, params: { ...nodeData.params, [paramKey]: value } })
  }

  return (
    <NodeShell
      color={style.color}
      emoji={emoji}
      headerLabel={nodeData.label}
      inputs={{ count: 1 }}
      outputs="single"
      issues={nodeData.validationIssues ?? []}
    >
      <Text type="secondary" style={{ fontSize: 11 }}>
        {nodeData.operator}
      </Text>
      {selectEntries.map(([paramKey, schema]) => (
        <div key={paramKey} className="nodrag" style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
          <Text style={{ fontSize: 10, color: '#8c8c8c', whiteSpace: 'nowrap' }}>
            {schema.label ?? paramKey}:
          </Text>
          <Select
            size="small"
            value={(nodeData.params?.[paramKey] as string) ?? schema.options?.[0]}
            options={(schema.options ?? []).map((opt) => ({ value: opt, label: opt }))}
            onChange={(val) => handleSelectChange(paramKey, val)}
            style={{ flex: 1, fontSize: 11 }}
          />
        </div>
      ))}
      {nonKeyValueEntries.length > 0 && (
        <div style={{ marginTop: 4 }}>
          {nonKeyValueEntries.map(([paramKey, val]) => {
            const label = paramsSchema[paramKey]?.label ?? paramKey
            let displayValue: string
            if (typeof val === 'string' && val.includes('\n')) {
              const items = val.split('\n').map((s) => s.trim()).filter(Boolean)
              const preview = items.slice(0, 4).join(', ')
              displayValue = items.length > 4 ? `${preview} 외 ${items.length - 4}개` : preview
            } else if (Array.isArray(val)) {
              displayValue = `[${val.length}]`
            } else {
              displayValue = String(val).slice(0, 30)
            }
            return (
              <div key={paramKey} style={{ fontSize: 10, color: '#8c8c8c', lineHeight: '16px' }}>
                {label}: {displayValue}
              </div>
            )
          })}
        </div>
      )}
      {keyValueEntries.map(([paramKey, val]) => {
        const entries = Object.entries(val as Record<string, string>)
        if (entries.length === 0) return null
        return (
          <div key={paramKey} style={{ marginTop: 4 }}>
            {entries.map(([k, v]) => (
              <div key={k} style={{ fontSize: 10, color: '#8c8c8c', lineHeight: '16px' }}>
                {k} → {v}
              </div>
            ))}
          </div>
        )
      })}
    </NodeShell>
  )
})

function OperatorPropertiesComponent({
  nodeId,
  data,
}: {
  nodeId: string
  data: OperatorNodeData
}) {
  const setNodeData = useSetNodeData()
  return (
    <>
      <Tag color="blue">{data.category}</Tag>
      <Text strong style={{ fontSize: 13, display: 'block', marginTop: 4 }}>
        {data.label}
      </Text>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 2 }}>
        {data.operator}
      </Text>
      <Divider style={{ margin: '8px 0' }} />
      <DynamicParamForm
        paramsSchema={data.paramsSchema as Record<string, never> | null}
        params={data.params as Record<string, unknown>}
        onChange={(newParams) => setNodeData(nodeId, { ...data, params: newParams })}
      />
    </>
  )
}

export const operatorDefinition: NodeDefinition<'operator'> = {
  kind: 'operator',
  // operator는 palette 정적 항목이 없음 — manipulator API로부터 동적 생성.
  paletteFromManipulators(manipulators: Manipulator[], _ctx: CreateContext): PaletteItem<'operator'>[] {
    const items: PaletteItem<'operator'>[] = []
    for (const m of manipulators) {
      // det_merge_datasets는 MergeNode 별도 특수 노드로 처리 — 여기서 제외.
      if (m.name === 'det_merge_datasets') continue
      const style = getCategoryStyle(m.category)
      const isFormatConvert = m.category === FORMAT_CONVERT_CATEGORY
      const isUnimplemented = UNIMPLEMENTED_OPERATORS.includes(m.name)
      const disabled = isFormatConvert
        ? {
            reason:
              '통일포맷 도입으로 포맷 변환이 파이프라인 저장 시 자동으로 수행됩니다. Save 노드의 출력 포맷 설정으로 충분합니다.',
            modalTitle: '포맷 변환은 자동으로 처리됩니다',
          }
        : isUnimplemented
          ? {
              reason: `"${extractShortLabel(m.description ?? m.name)}"은(는) 현재 미구현 상태입니다.`,
              modalTitle: '미구현 기능',
            }
          : null
      items.push({
        key: m.name,
        section: 'manipulator',
        label: extractShortLabel(m.description ?? m.name),
        description: m.description ?? undefined,
        color: style.color,
        emoji: getManipulatorEmoji(m.name, m.category),
        kind: 'operator',
        disabled,
        createData: () => createOperatorDataFromManipulator(m),
      })
    }
    return items
  },
  NodeComponent: OperatorNodeComponent,
  PropertiesComponent: OperatorPropertiesComponent,

  validate(data, ctx) {
    const errors = []
    const incoming = ctx.edges.filter((e) => e.target === ctx.nodeId)
    if (incoming.length === 0) {
      errors.push({ nodeId: ctx.nodeId, message: `"${data.label}" 노드에 입력 연결이 없습니다.` })
    }
    return errors
  },

  toConfigContribution(data, ctx) {
    const inputs = buildInputsFromIncoming(ctx)
    const taskKey = `task_${ctx.nodeId}`
    return {
      tasks: {
        [taskKey]: {
          operator: data.operator,
          inputs,
          params: (data.params as Record<string, unknown>) ?? {},
        },
      },
      outputRef: taskKey,
    }
  },

  matchFromConfig(ctx) {
    const { config, manipulatorMap, claimedTaskKeys } = ctx
    const restored = []
    for (const [taskKey, taskConfig] of Object.entries(config.tasks)) {
      if (claimedTaskKeys.has(taskKey)) continue
      if (taskConfig.operator === 'det_merge_datasets') continue
      const manipulatorMeta = manipulatorMap[taskConfig.operator]
      if (!manipulatorMeta) continue // placeholderDefinition이 나중에 점유

      const nodeId = taskKey.startsWith('task_') ? taskKey.slice(5) : taskKey
      const description = manipulatorMeta.description ?? taskConfig.operator
      const labelMatch = description.match(/^(.+?)\s*\((.+)\)\s*$/)
      const label = labelMatch ? labelMatch[1] : description
      const data: OperatorNodeData = {
        type: 'operator',
        operator: taskConfig.operator,
        category: manipulatorMeta.category ?? 'UNKNOWN',
        label,
        params: { ...taskConfig.params },
        paramsSchema: (manipulatorMeta.params_schema as Record<string, unknown>) ?? null,
      }
      restored.push({ nodeId, data, ownedTaskKeys: [taskKey] })
    }
    return restored
  },

  matchIssueField(issue, _data, nodeId) {
    return issue.field.startsWith(`tasks.task_${nodeId}`)
  },
}

/** 비활성 팔레트 항목 클릭 시 공통 모달 */
export function showDisabledModal(item: { label: string; disabled: { reason: string; modalTitle?: string } }): void {
  const { disabled, label } = item
  Modal.info({
    title: disabled.modalTitle ?? label,
    content: <div>{disabled.reason}</div>,
    okText: '확인',
  })
}
