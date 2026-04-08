/**
 * OperatorNode — 범용 단일입력/단일출력 manipulator 노드
 *
 * format_convert, filter, sample, remap, augment 등
 * 모든 단일 I/O manipulator를 하나의 노드 컴포넌트로 처리한다.
 * params는 PropertiesPanel의 DynamicParamForm에서 편집한다.
 * 노드 본문에는 operator 이름과 params 요약만 표시한다.
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Typography, Tag, Select } from 'antd'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import type { OperatorNodeData } from '@/types/pipeline'
import { getCategoryStyle, getManipulatorEmoji } from '../nodeStyles'

const { Text } = Typography

function OperatorNodeComponent({ id }: NodeProps) {
  // store 직접 구독 — params 변경이 노드에 실시간 반영됨
  const nodeData = usePipelineEditorStore(
    (s) => (s.nodeDataMap[id] as OperatorNodeData) ?? null,
  )
  const setNodeData = usePipelineEditorStore((s) => s.setNodeData)

  if (!nodeData) return null
  const style = getCategoryStyle(nodeData.category)

  const hasErrors = (nodeData.validationIssues ?? []).some((i) => i.severity === 'error')
  const hasWarnings = (nodeData.validationIssues ?? []).some((i) => i.severity === 'warning')
  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : style.color

  // params 요약 — select는 인라인 드롭다운, key_value는 줄바꿈 렌더링, 나머지는 label: value 텍스트
  const paramsSchema = (nodeData.paramsSchema ?? {}) as Record<string, { label?: string; type?: string; options?: string[] }>
  const paramEntries = Object.entries(nodeData.params ?? {}).filter(
    ([, val]) => val !== '' && val !== null && val !== undefined,
  )

  // select 타입 — 노드 본문에서 인라인 드롭다운으로 편집
  const selectEntries = Object.entries(paramsSchema).filter(([, schema]) => schema.type === 'select')

  // key_value 매핑 항목 추출 (예: mapping: { person: "human", car: "vehicle" })
  const keyValueEntries = paramEntries.filter(
    ([key, val]) => typeof val === 'object' && val !== null && !Array.isArray(val) && paramsSchema[key]?.type !== 'select',
  )
  // 그 외 일반 params — label: value 한 줄씩 표시 (select, key_value 제외)
  const nonKeyValueEntries = paramEntries.filter(
    ([key, val]) =>
      !(typeof val === 'object' && val !== null && !Array.isArray(val)) &&
      paramsSchema[key]?.type !== 'select',
  )

  /** select 파라미터 변경 핸들러 */
  const handleSelectChange = (paramKey: string, value: string) => {
    setNodeData(id, { ...nodeData, params: { ...nodeData.params, [paramKey]: value } })
  }

  return (
    <div
      style={{
        background: '#fff',
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        minWidth: 200,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      {/* 입력 핸들 */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 10,
          height: 10,
          background: style.color,
          border: '2px solid #fff',
        }}
      />

      {/* 헤더 */}
      <div
        style={{
          background: style.color,
          color: '#fff',
          padding: '6px 12px',
          borderRadius: '6px 6px 0 0',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        <span>{getManipulatorEmoji(nodeData.operator, nodeData.category)}</span>
        {nodeData.label}
      </div>

      {/* 본문 */}
      <div style={{ padding: '8px 12px' }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {nodeData.operator}
        </Text>
        {/* select 타입: 인라인 드롭다운 */}
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

        {/* 일반 params: label: value 한 줄씩 */}
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

        {/* key_value 매핑: 한 줄에 하나씩 "old → new" 표시 */}
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

        {/* 검증 이슈 표시 */}
        {(nodeData.validationIssues ?? []).length > 0 && (
          <div style={{ marginTop: 4 }}>
            {nodeData.validationIssues!.map((issue, idx) => (
              <Tag
                key={idx}
                color={issue.severity === 'error' ? 'error' : 'warning'}
                style={{ fontSize: 10, marginTop: 2 }}
              >
                {issue.message}
              </Tag>
            ))}
          </div>
        )}
      </div>

      {/* 출력 핸들 */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 10,
          height: 10,
          background: style.color,
          border: '2px solid #fff',
        }}
      />
    </div>
  )
}

export default memo(OperatorNodeComponent)
