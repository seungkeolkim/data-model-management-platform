import { useParams } from 'react-router-dom'
import { Typography, Tabs, Empty } from 'antd'

const { Title, Text } = Typography

/**
 * 데이터셋 상세 페이지
 * 탭 구성:
 *   - 기본 정보 (Phase 1)
 *   - 샘플 보기 (Phase 2-b, 현재 빈 슬롯)
 *   - EDA (Phase 2-a, 현재 빈 슬롯)
 *   - Lineage (Phase 2-b, 현재 빈 슬롯)
 */
export default function DatasetDetailPage() {
  const { groupId } = useParams()

  const tabs = [
    {
      key: 'info',
      label: '기본 정보',
      children: (
        <Empty description={<Text type="secondary">Phase 1에서 구현 예정</Text>} />
      ),
    },
    {
      key: 'samples',
      label: '샘플 보기',
      children: (
        <Empty description={<Text type="secondary">Phase 2-b에서 구현 예정</Text>} />
      ),
    },
    {
      key: 'eda',
      label: 'EDA',
      children: (
        <Empty description={<Text type="secondary">Phase 2-a에서 구현 예정</Text>} />
      ),
    },
    {
      key: 'lineage',
      label: 'Lineage',
      children: (
        <Empty description={<Text type="secondary">Phase 2-b에서 구현 예정</Text>} />
      ),
    },
  ]

  return (
    <div>
      <Title level={3}>데이터셋 상세</Title>
      <Text type="secondary">group ID: {groupId}</Text>
      <Tabs items={tabs} style={{ marginTop: 16 }} />
    </div>
  )
}
