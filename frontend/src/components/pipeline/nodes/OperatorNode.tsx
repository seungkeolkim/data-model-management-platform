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
import { Typography, Tag } from 'antd'
import {
  SwapOutlined,
  FilterOutlined,
  ScissorOutlined,
  RetweetOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import type { OperatorNodeData } from '@/types/pipeline'

const { Text } = Typography

/** 카테고리별 색상 및 아이콘 */
const CATEGORY_STYLE: Record<string, { color: string; icon: React.ReactNode }> = {
  FORMAT_CONVERT: { color: '#1677ff', icon: <SwapOutlined /> },
  FILTER: { color: '#eb2f96', icon: <FilterOutlined /> },
  SAMPLE: { color: '#722ed1', icon: <ScissorOutlined /> },
  REMAP: { color: '#fa8c16', icon: <RetweetOutlined /> },
  AUGMENT: { color: '#13c2c2', icon: <ThunderboltOutlined /> },
  UDM: { color: '#595959', icon: <ToolOutlined /> },
}

const DEFAULT_STYLE = { color: '#8c8c8c', icon: <ToolOutlined /> }

function OperatorNodeComponent({ id }: NodeProps) {
  // store 직접 구독 — params 변경이 노드에 실시간 반영됨
  const nodeData = usePipelineEditorStore(
    (s) => (s.nodeDataMap[id] as OperatorNodeData) ?? null,
  )

  if (!nodeData) return null
  const style = CATEGORY_STYLE[nodeData.category] ?? DEFAULT_STYLE

  const hasErrors = (nodeData.validationIssues ?? []).some((i) => i.severity === 'error')
  const hasWarnings = (nodeData.validationIssues ?? []).some((i) => i.severity === 'warning')
  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : style.color

  // params 요약: textarea 값은 줄바꿈→쉼표로 축약, 그 외는 key: value 형태
  const paramEntries = Object.entries(nodeData.params ?? {}).filter(
    ([, val]) => val !== '' && val !== null && val !== undefined,
  )
  const paramsSummary =
    paramEntries.length === 0
      ? null
      : paramEntries
          .slice(0, 2)
          .map(([, val]) => {
            if (typeof val === 'string' && val.includes('\n')) {
              // textarea 값: 줄바꿈을 쉼표로 합쳐서 표시
              const items = val.split('\n').map((s) => s.trim()).filter(Boolean)
              const preview = items.slice(0, 4).join(', ')
              return items.length > 4 ? `${preview} 외 ${items.length - 4}개` : preview
            }
            if (Array.isArray(val)) return `[${val.length}]`
            return String(val).slice(0, 30)
          })
          .join(', ') + (paramEntries.length > 2 ? ' ...' : '')

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
        {style.icon}
        {nodeData.label}
      </div>

      {/* 본문 */}
      <div style={{ padding: '8px 12px' }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {nodeData.operator}
        </Text>
        {paramsSummary && (
          <div style={{ marginTop: 4 }}>
            <Text style={{ fontSize: 10, color: '#8c8c8c' }}>{paramsSummary}</Text>
          </div>
        )}

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
