import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Typography,
  Breadcrumb,
  Space,
  Card,
  Row,
  Col,
  Button,
  Empty,
  Alert,
  Tag,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { getPipeline } from '@/api/automation'
import AutomationSettingsForm from '@/components/automation/AutomationSettingsForm'
import UpstreamDeltaList from '@/components/automation/UpstreamDeltaList'
import RecentAutomationRuns from '@/components/automation/RecentAutomationRuns'
import ManualRerunModal from '@/components/automation/ManualRerunModal'

const { Title, Text } = Typography

/**
 * 파이프라인 상세 Automation 탭 (목업, 023 §6-4).
 *
 * 실 구현에서 "Pipeline 상세 페이지" 는 여러 탭 중 하나의 Automation 탭으로 존재하지만,
 * 목업 단계에서는 Pipeline 엔티티가 백엔드에 없어 이 페이지 자체가 Automation 탭의 독립 버전이다.
 * 나중에 Pipeline 엔티티 도입 시 tabs 의 한 탭으로 래핑하면 된다.
 */
export default function AutomationPipelineDetailPage() {
  const { pipelineId } = useParams<{ pipelineId: string }>()
  const [rerunOpen, setRerunOpen] = useState(false)

  const { data: pipeline, isLoading, error } = useQuery({
    queryKey: ['automation', 'pipeline', pipelineId],
    queryFn: () => (pipelineId ? getPipeline(pipelineId) : Promise.resolve(null)),
    enabled: Boolean(pipelineId),
  })

  if (isLoading) {
    return <Card loading />
  }

  if (error) {
    return (
      <Alert
        type="error"
        message="파이프라인 로드 실패"
        description={(error as Error).message}
        showIcon
      />
    )
  }

  if (!pipeline) {
    return (
      <Empty
        description={
          <>
            파이프라인을 찾을 수 없습니다.
            <br />
            <Link to="/automation">목록으로 돌아가기</Link>
          </>
        }
      />
    )
  }

  const rerunDisabled = pipeline.automation_status === 'error'

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 12 }}
        items={[
          { title: <Link to="/automation">Automation</Link> },
          { title: pipeline.name },
        ]}
      />
      <Space
        align="start"
        style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            {pipeline.name}
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {pipeline.description ?? '설명 없음'}
          </Text>
        </div>
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          onClick={() => setRerunOpen(true)}
          disabled={rerunDisabled}
        >
          수동 재실행
        </Button>
      </Space>

      {rerunDisabled && (
        <Alert
          type="warning"
          showIcon
          message="Error 상태에서는 수동 재실행이 비활성화됩니다"
          description="먼저 Status 를 stopped 로 내리거나 error 사유를 해결한 뒤 다시 시도하세요."
          style={{ marginBottom: 16 }}
        />
      )}

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <Space size={8} wrap>
            <Text strong>입력:</Text>
            <Tag>{pipeline.input.group_name}</Tag>
            <Tag color="geekblue">{pipeline.input.split}</Tag>
            <Text type="secondary">→</Text>
            <Text strong>출력:</Text>
            <Tag>{pipeline.output.group_name}</Tag>
            <Tag color="geekblue">{pipeline.output.split}</Tag>
          </Space>
          {pipeline.tasks.length > 0 && (
            <Space size={4} wrap>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Tasks:
              </Text>
              {pipeline.tasks.map((task) => (
                <Tag key={task.task_id} color="purple" style={{ fontSize: 11 }}>
                  {task.display_name}
                </Tag>
              ))}
            </Space>
          )}
        </Space>
      </Card>

      <Row gutter={16}>
        <Col xs={24} xl={12}>
          <AutomationSettingsForm pipeline={pipeline} />
        </Col>
        <Col xs={24} xl={12}>
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <UpstreamDeltaList pipelineId={pipeline.id} />
            <RecentAutomationRuns pipelineId={pipeline.id} />
          </Space>
        </Col>
      </Row>

      <ManualRerunModal
        open={rerunOpen}
        pipelineId={pipeline.id}
        pipelineName={pipeline.name}
        onClose={() => setRerunOpen(false)}
      />
    </div>
  )
}
