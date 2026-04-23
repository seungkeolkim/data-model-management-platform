import { Typography, Alert } from 'antd'
import AutomationSectionNav from '@/components/automation/AutomationSectionNav'
import ExecutionHistoryTable from '@/components/automation/ExecutionHistoryTable'

const { Title, Text } = Typography

/**
 * Automation 실행 이력 페이지 (목업, 023 §6-3).
 *
 * /pipelines 이력 페이지(실 백엔드) 와 분리된 경로에 두어 목업 데이터가 실 데이터와 섞이지 않게 한다.
 * 실 구현 진입 시 두 뷰의 통합 여부는 그 시점에 결정.
 */
export default function AutomationHistoryPage() {
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          Automation
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          자동화 실행 이력 (목업)
        </Text>
      </div>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="목업 데이터입니다"
        description="여기의 실행 이력은 프론트 fixture 입니다. 데이터 변형 탭 (/pipelines) 의 실 API 이력과 별도입니다."
      />
      <AutomationSectionNav />
      <ExecutionHistoryTable />
    </div>
  )
}
