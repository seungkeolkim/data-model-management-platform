/**
 * PropertiesPanel — 우측 속성 패널.
 *
 * 선택된 노드의 definition.PropertiesComponent를 렌더링한다.
 * 노드 타입별 분기는 이 파일에서 사라졌고, 각 definition이 자기 패널을 제공.
 */
import { Typography, Divider, Tag, Empty } from 'antd'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import { getNodeDefinition } from '@/pipeline-sdk'
import type { NodeKind } from '@/pipeline-sdk'
import SchemaPreviewSection from './SchemaPreviewSection'

const { Text, Title } = Typography

export default function PropertiesPanel() {
  const selectedNodeId = usePipelineEditorStore((s) => s.selectedNodeId)
  const nodeDataMap = usePipelineEditorStore((s) => s.nodeDataMap)

  const nodeData = selectedNodeId ? nodeDataMap[selectedNodeId] : null

  if (!nodeData || !selectedNodeId) {
    return (
      <div
        style={{
          width: 280,
          background: '#fafafa',
          borderLeft: '1px solid #f0f0f0',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Empty description="노드를 선택하세요" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    )
  }

  const definition = getNodeDefinition(nodeData.type as NodeKind)
  const PropertiesComponent = definition?.PropertiesComponent

  return (
    <div
      style={{
        width: 280,
        background: '#fafafa',
        borderLeft: '1px solid #f0f0f0',
        height: '100%',
        overflowY: 'auto',
        padding: '12px',
      }}
    >
      <Title level={5} style={{ margin: 0, marginBottom: 8 }}>
        속성
      </Title>

      {PropertiesComponent ? (
        <PropertiesComponent nodeId={selectedNodeId} data={nodeData as never} />
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          이 노드는 추가 설정이 없습니다.
        </Text>
      )}

      <SchemaPreviewSection selectedNodeId={selectedNodeId} nodeData={nodeData} />

      {/* 검증 이슈 요약 */}
      {(nodeData.validationIssues ?? []).length > 0 && (
        <>
          <Divider style={{ margin: '8px 0' }} />
          <Text strong style={{ fontSize: 12 }}>검증 이슈</Text>
          <div style={{ marginTop: 4 }}>
            {nodeData.validationIssues!.map((issue, idx) => (
              <div key={idx} style={{ marginBottom: 4 }}>
                <Tag
                  color={issue.severity === 'error' ? 'error' : 'warning'}
                  style={{ fontSize: 11 }}
                >
                  {issue.severity.toUpperCase()}
                </Tag>
                <Text style={{ fontSize: 11 }}>{issue.message}</Text>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
