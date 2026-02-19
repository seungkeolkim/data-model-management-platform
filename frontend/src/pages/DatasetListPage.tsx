import { Typography, Button, Space, Empty, Spin, Alert } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

/**
 * 데이터셋 목록 페이지 (Phase 1에서 구현)
 * - TanStack Table (서버사이드 정렬/필터/페이지네이션)
 * - 필터 패널: dataset_type, task_types, annotation_format, modality, split, status
 * - group 단위 행, 펼치면 split x version 매트릭스
 */
export default function DatasetListPage() {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>데이터셋</Title>
          <Text type="secondary">학습 데이터셋을 관리합니다.</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} size="large">
          데이터셋 등록
        </Button>
      </div>

      {/* Phase 1에서 구현 */}
      <Empty
        description={
          <span>
            데이터셋이 없습니다.<br />
            <Text type="secondary" style={{ fontSize: 12 }}>Phase 1에서 목록 구현 예정</Text>
          </span>
        }
        style={{ marginTop: 80 }}
      />
    </div>
  )
}
