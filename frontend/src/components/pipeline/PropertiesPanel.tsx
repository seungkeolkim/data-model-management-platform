/**
 * PropertiesPanel — 우측 속성 패널
 *
 * 선택된 노드의 상세 설정을 편집한다.
 * OperatorNode의 경우 DynamicParamForm을 렌더링하여 params를 편집한다.
 * DataLoad, Merge, Save 노드는 노드 자체에 인라인 폼이 있으므로
 * 여기서는 보조 정보만 표시한다.
 */

import { Typography, Divider, Tag, Empty } from 'antd'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import DynamicParamForm from './DynamicParamForm'
import type { OperatorNodeData } from '@/types/pipeline'

const { Text, Title } = Typography

export default function PropertiesPanel() {
  const selectedNodeId = usePipelineEditorStore((s) => s.selectedNodeId)
  const nodeDataMap = usePipelineEditorStore((s) => s.nodeDataMap)
  const updateNodeParams = usePipelineEditorStore((s) => s.updateNodeParams)
  const setNodeData = usePipelineEditorStore((s) => s.setNodeData)

  const nodeData = selectedNodeId ? nodeDataMap[selectedNodeId] : null

  if (!nodeData) {
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

      {/* 노드 타입별 패널 내용 */}
      {nodeData.type === 'dataLoad' && (
        <>
          <Tag color="green">Data Load</Tag>
          <Divider style={{ margin: '8px 0' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            데이터셋 선택은 노드에서 직접 수행합니다.
          </Text>
          {nodeData.datasetId && (
            <div style={{ marginTop: 8 }}>
              <Text style={{ fontSize: 12 }}>선택된 ID:</Text>
              <br />
              <Text code style={{ fontSize: 11 }}>{nodeData.datasetId}</Text>
            </div>
          )}
        </>
      )}

      {nodeData.type === 'operator' && (
        <>
          <Tag color="blue">{nodeData.category}</Tag>
          <Text strong style={{ fontSize: 13, display: 'block', marginTop: 4 }}>
            {nodeData.label}
          </Text>
          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 2 }}>
            {nodeData.operator}
          </Text>
          <Divider style={{ margin: '8px 0' }} />

          {/* params_schema 기반 동적 폼 */}
          <DynamicParamForm
            paramsSchema={nodeData.paramsSchema as Record<string, never> | null}
            params={nodeData.params as Record<string, unknown>}
            onChange={(newParams) => {
              if (selectedNodeId) {
                setNodeData(selectedNodeId, { ...nodeData, params: newParams } as OperatorNodeData)
              }
            }}
          />
        </>
      )}

      {nodeData.type === 'merge' && (
        <>
          <Tag color="purple">Merge</Tag>
          <Divider style={{ margin: '8px 0' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            2개 이상의 데이터셋을 병합합니다.
            연결된 입력이 자동으로 inputs에 매핑됩니다.
          </Text>
        </>
      )}

      {nodeData.type === 'save' && (
        <>
          <Tag color="orange">Save</Tag>
          <Divider style={{ margin: '8px 0' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            출력 설정은 노드에서 직접 편집합니다.
          </Text>
        </>
      )}

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
