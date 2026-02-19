import { Typography, Empty, Text } from 'antd'

const { Title } = Typography

/**
 * Manipulator 관리 페이지 (Phase 2에서 구현)
 */
export default function ManipulatorListPage() {
  return (
    <div>
      <Title level={3}>Manipulator 관리</Title>
      <Empty
        description={
          <Typography.Text type="secondary">
            Phase 2에서 구현 예정 — 등록된 Manipulator 목록, params_schema 확인, status 변경
          </Typography.Text>
        }
        style={{ marginTop: 80 }}
      />
    </div>
  )
}
