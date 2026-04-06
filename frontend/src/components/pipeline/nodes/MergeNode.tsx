/**
 * MergeNode — merge_datasets 다중 입력 노드
 *
 * 2개 이상의 입력을 받아 하나로 병합한다.
 * 입력 핸들은 연결된 엣지 수에 따라 동적으로 생성된다 (최소 2개).
 */

import { memo, useMemo } from 'react'
import { Handle, Position, useEdges } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Typography, Tag } from 'antd'
import { MergeCellsOutlined } from '@ant-design/icons'
import type { MergeNodeData } from '@/types/pipeline'

const { Text } = Typography

const MERGE_COLOR = '#9254de'

function MergeNodeComponent({ id, data }: NodeProps) {
  const nodeData = data as unknown as MergeNodeData
  const allEdges = useEdges()

  // 이 노드에 연결된 입력 엣지 수 계산 → 핸들 수 결정
  const connectedInputCount = useMemo(
    () => allEdges.filter((e) => e.target === id).length,
    [allEdges, id],
  )
  // 최소 2개 핸들, 연결된 수 + 1개 여분 (새 연결용)
  const handleCount = Math.max(2, connectedInputCount + 1)

  const hasErrors = (nodeData.validationIssues ?? []).some((i) => i.severity === 'error')
  const hasWarnings = (nodeData.validationIssues ?? []).some((i) => i.severity === 'warning')
  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : MERGE_COLOR

  return (
    <div
      style={{
        background: '#fff',
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        minWidth: 180,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      {/* 다중 입력 핸들 — 세로로 균등 배치 */}
      {Array.from({ length: handleCount }).map((_, idx) => (
        <Handle
          key={`input-${idx}`}
          type="target"
          position={Position.Left}
          id={`input-${idx}`}
          style={{
            width: 10,
            height: 10,
            background: MERGE_COLOR,
            border: '2px solid #fff',
            top: `${((idx + 1) / (handleCount + 1)) * 100}%`,
          }}
        />
      ))}

      {/* 헤더 */}
      <div
        style={{
          background: MERGE_COLOR,
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
        <MergeCellsOutlined />
        Merge
      </div>

      {/* 본문 */}
      <div style={{ padding: '8px 12px' }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {connectedInputCount}개 입력 연결됨
        </Text>

        {/* 검증 이슈 */}
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
          background: MERGE_COLOR,
          border: '2px solid #fff',
        }}
      />
    </div>
  )
}

export default memo(MergeNodeComponent)
