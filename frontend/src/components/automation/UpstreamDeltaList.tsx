import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Typography, Alert } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getUpstreamDeltas } from '@/api/automation'
import type { UpstreamSplitDelta } from '@/types/automation'

const { Text } = Typography

/**
 * 상류 DatasetSplit delta 표 (027 §6 / 028 §1 기준).
 *
 * 각 상류 split 별로 "현재 최신 버전 vs automation.last_seen_input_versions" 를 비교해 delta 여부를
 * 가시화한다. v7.13 baseline 에서 자료구조가 group → split → version 으로 분리됐으므로 표 단위도
 * split 행이 됐다 (group + split 표시).
 *
 * `versionId` 는 PipelineVersion.id — automation 이 version 단위로 붙으므로 자연스럽게 versionId 키로 조회.
 */
export default function UpstreamDeltaList({ versionId }: { versionId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['automation', 'upstream-deltas', versionId],
    queryFn: () => getUpstreamDeltas(versionId),
  })

  const columns: ColumnsType<UpstreamSplitDelta> = [
    {
      title: '상류 그룹 / split',
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
    <Card title="상류 DatasetSplit" size="small">
      {error && (
        <Alert type="error" message="상류 delta 로드 실패" description={(error as Error).message} />
      )}
      <Table<UpstreamSplitDelta>
        size="small"
        rowKey="split_id"
        loading={isLoading}
        columns={columns}
        dataSource={data ?? []}
        pagination={false}
      />
    </Card>
  )
}
