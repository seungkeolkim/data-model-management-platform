/**
 * PropertiesPanel — 우측 속성 패널
 *
 * 선택된 노드의 상세 설정을 편집한다.
 * OperatorNode의 경우 DynamicParamForm을 렌더링하여 params를 편집한다.
 * DataLoad 노드는 선택 완료 시 데이터 타입, 포맷, 클래스 매핑 등 상세 정보를 표시한다.
 */

import { useMemo } from 'react'
import { Typography, Divider, Tag, Empty, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import { datasetsForPipelineApi } from '@/api/pipeline'
import DynamicParamForm from './DynamicParamForm'
import type { OperatorNodeData, DataLoadNodeData } from '@/types/pipeline'

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
        <DataLoadProperties nodeData={nodeData} />
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

// =============================================================================
// DataLoadProperties — DataLoad 노드 선택 상태 + 데이터셋 상세 정보
// =============================================================================

/** 속성 행 표시용 헬퍼 */
function PropRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
      <div style={{ fontSize: 12, textAlign: 'right' }}>{value}</div>
    </div>
  )
}

function DataLoadProperties({ nodeData }: { nodeData: DataLoadNodeData }) {
  // 그룹 정보 조회 (datasets 포함) — 선택된 그룹이 있을 때만
  const { data: groupData } = useQuery({
    queryKey: ['dataset-group-detail', nodeData.groupId],
    queryFn: () => datasetsForPipelineApi.getGroup(nodeData.groupId!).then((r) => r.data),
    enabled: !!nodeData.groupId,
    staleTime: 30_000,
  })

  // 선택된 dataset 찾기
  const selectedDataset = useMemo(() => {
    if (!groupData || !nodeData.datasetId) return null
    return groupData.datasets.find((ds) => ds.id === nodeData.datasetId) ?? null
  }, [groupData, nodeData.datasetId])

  // 클래스 매핑 테이블 데이터
  const classTableData = useMemo(() => {
    const classMapping = selectedDataset?.metadata?.class_info?.class_mapping
    if (!classMapping) return []
    return Object.entries(classMapping)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([index, name]) => ({ index, name }))
  }, [selectedDataset])

  return (
    <>
      <Tag color="green">Data Load</Tag>
      <Divider style={{ margin: '8px 0' }} />

      {/* 선택 상태 요약 */}
      <Text type="secondary" style={{ fontSize: 12 }}>
        데이터셋 · Split · 버전을 노드에서 순서대로 선택합니다.
      </Text>

      {nodeData.groupName && (
        <div style={{ marginTop: 8 }}>
          <PropRow label="그룹" value={<Text strong style={{ fontSize: 12 }}>{nodeData.groupName}</Text>} />
        </div>
      )}
      {nodeData.split && (
        <PropRow label="Split" value={nodeData.split} />
      )}
      {nodeData.version && (
        <PropRow label="버전" value={nodeData.version} />
      )}
      {nodeData.datasetId && (
        <PropRow label="ID" value={<Text code style={{ fontSize: 10 }}>{nodeData.datasetId.slice(0, 12)}...</Text>} />
      )}

      {/* 데이터셋 상세 정보 — 3단계 선택 완료 시에만 표시 */}
      {selectedDataset && groupData && (
        <>
          <Divider style={{ margin: '8px 0' }} />
          <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
            데이터셋 정보
          </Text>

          <PropRow
            label="데이터 타입"
            value={<Tag color="blue" style={{ margin: 0 }}>{groupData.dataset_type}</Tag>}
          />
          <PropRow
            label="어노테이션 포맷"
            value={<Tag style={{ margin: 0 }}>{selectedDataset.annotation_format ?? '없음'}</Tag>}
          />
          <PropRow label="이미지 수" value={selectedDataset.image_count ?? '-'} />
          <PropRow label="클래스 수" value={selectedDataset.class_count ?? classTableData.length ?? '-'} />

          {/* 클래스 인덱스별 매핑 테이블 */}
          {classTableData.length > 0 && (
            <>
              <Divider style={{ margin: '8px 0' }} />
              <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                클래스 목록
              </Text>
              <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                <Table
                  dataSource={classTableData}
                  columns={[
                    {
                      title: 'ID',
                      dataIndex: 'index',
                      width: 45,
                      render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text>,
                    },
                    {
                      title: '클래스명',
                      dataIndex: 'name',
                      render: (v: string) => <Text style={{ fontSize: 11 }}>{v}</Text>,
                    },
                  ]}
                  rowKey="index"
                  size="small"
                  pagination={false}
                  showHeader
                  style={{ fontSize: 11 }}
                />
              </div>
            </>
          )}
        </>
      )}
    </>
  )
}
