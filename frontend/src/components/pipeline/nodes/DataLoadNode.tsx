/**
 * DataLoadNode — 소스 데이터셋 선택 노드
 *
 * DB에서 READY 상태 데이터셋 목록을 조회하여 드롭다운으로 표시한다.
 * 출력 핸들만 존재하며, 선택된 dataset_id가 하위 노드의 inputs에
 * "source:<dataset_id>" 형태로 변환된다.
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Select, Typography, Tag } from 'antd'
import { DatabaseOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { datasetsForPipelineApi } from '@/api/pipeline'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import type { DataLoadNodeData } from '@/types/pipeline'

const { Text } = Typography

function DataLoadNodeComponent({ id, data }: NodeProps) {
  const nodeData = data as unknown as DataLoadNodeData
  const setNodeData = usePipelineEditorStore((s) => s.setNodeData)

  const { data: datasets, isLoading } = useQuery({
    queryKey: ['datasets-ready-for-pipeline'],
    queryFn: () => datasetsForPipelineApi.listReady().then((r) => r.data),
    staleTime: 30_000,
  })

  const hasErrors = (nodeData.validationIssues ?? []).some((i) => i.severity === 'error')
  const hasWarnings = (nodeData.validationIssues ?? []).some((i) => i.severity === 'warning')

  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : '#52c41a'

  return (
    <div
      style={{
        background: '#fff',
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        minWidth: 240,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      {/* 헤더 */}
      <div
        style={{
          background: '#52c41a',
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
        <DatabaseOutlined />
        Data Load
      </div>

      {/* 본문 */}
      <div style={{ padding: '8px 12px' }}>
        <Select
          size="small"
          placeholder="데이터셋 선택"
          value={nodeData.datasetId || undefined}
          loading={isLoading}
          style={{ width: '100%' }}
          showSearch
          optionFilterProp="label"
          onChange={(value, option) => {
            const selected = Array.isArray(option) ? option[0] : option
            setNodeData(id, {
              ...nodeData,
              datasetId: value,
              datasetLabel: (selected?.label as string) ?? '',
            })
          }}
          options={(datasets ?? []).map((ds) => ({
            value: ds.id,
            label: `${ds.storage_uri} (${ds.split})`,
          }))}
          // 노드 내부 클릭이 드래그로 잡히지 않도록
          onMouseDown={(e) => e.stopPropagation()}
        />
        {nodeData.datasetId && (
          <Text type="secondary" style={{ fontSize: 10, display: 'block', marginTop: 4 }}>
            ID: {nodeData.datasetId.slice(0, 8)}...
          </Text>
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
          background: '#52c41a',
          border: '2px solid #fff',
        }}
      />
    </div>
  )
}

export default memo(DataLoadNodeComponent)
