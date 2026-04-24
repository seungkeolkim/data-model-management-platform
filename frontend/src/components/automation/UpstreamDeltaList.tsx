import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Typography, Alert } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getUpstreamDeltas } from '@/api/automation'
import type { UpstreamGroupDelta } from '@/types/automation'

const { Text } = Typography

/**
 * 상류 DatasetGroup delta 표 (023 §6-4).
 *
 * 각 상류 그룹별로 "현재 최신 버전 vs automation_last_seen_input_versions" 를 비교해
 * delta 여부를 가시화한다. 목업은 Pipeline.input 만 상류로 취급 — 실 구현에서는 chaining 상류
 * 체인 전체로 확장 예정.
 */
export default function UpstreamDeltaList({ pipelineId }: { pipelineId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['automation', 'upstream-deltas', pipelineId],
    queryFn: () => getUpstreamDeltas(pipelineId),
  })

  const columns: ColumnsType<UpstreamGroupDelta> = [
    {
      title: '상류 그룹',
      key: 'group',
      render: (_, delta) => (
        <div>
          <Text strong>{delta.group_name}</Text>
          <div style={{ fontSize: 11, color: '#8c8c8c' }}>
            split: <Tag>{delta.split}</Tag>
          </div>
        </div>
      ),
    },
    {
      title: '최신 버전',
      dataIndex: 'latest_version',
      key: 'latest_version',
      render: (version: string) => <Tag color="blue">{version}</Tag>,
    },
    {
      title: '자동 처리 기준',
      dataIndex: 'last_seen_version',
      key: 'last_seen_version',
      render: (version: string | null) =>
        version ? <Tag>{version}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: 'Delta',
      key: 'delta',
      render: (_, delta) =>
        delta.has_delta ? (
          <Tag color="gold">새 버전 감지됨</Tag>
        ) : (
          <Tag color="default">변경 없음</Tag>
        ),
    },
  ]

  return (
    <Card title="상류 DatasetGroup" size="small">
      {error && (
        <Alert type="error" message="상류 delta 로드 실패" description={(error as Error).message} />
      )}
      <Table<UpstreamGroupDelta>
        size="small"
        rowKey="group_id"
        loading={isLoading}
        columns={columns}
        dataSource={data ?? []}
        pagination={false}
      />
    </Card>
  )
}
