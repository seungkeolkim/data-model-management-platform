import { Typography, Empty, Tag } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'

const { Title } = Typography

interface Props {
  title: string
  phase: string
}

export default function ComingSoonPage({ title, phase }: Props) {
  return (
    <div>
      <Title level={3}>
        {title} <Tag color="default">{phase}</Tag>
      </Title>
      <Empty
        image={<ClockCircleOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />}
        imageStyle={{ height: 80 }}
        description={
          <Typography.Text type="secondary">
            {phase} 개발 예정입니다.
          </Typography.Text>
        }
        style={{ marginTop: 80 }}
      />
    </div>
  )
}
