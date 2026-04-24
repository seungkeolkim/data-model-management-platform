import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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
  Input,
  message,
} from 'antd'
import { ReloadOutlined, ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import { getPipeline, updatePipelineDescription } from '@/api/automation'
import AutomationSettingsForm from '@/components/automation/AutomationSettingsForm'
import UpstreamDeltaList from '@/components/automation/UpstreamDeltaList'
import RecentAutomationRuns from '@/components/automation/RecentAutomationRuns'
import ManualRerunModal from '@/components/automation/ManualRerunModal'
import { TaskTypeTag } from '@/components/automation/StatusBadge'

const { Title, Text } = Typography
const { TextArea } = Input

/**
 * 파이프라인 상세 Automation 탭 (목업, 023 §6-4).
 *
 * 실 구현에서 "Pipeline 상세 페이지" 는 여러 탭 중 하나의 Automation 탭으로 존재하지만,
 * 목업 단계에서는 Pipeline 엔티티가 백엔드에 없어 이 페이지 자체가 Automation 탭의 독립 버전이다.
 * 나중에 Pipeline 엔티티 도입 시 tabs 의 한 탭으로 래핑하면 된다.
 */
export default function AutomationPipelineDetailPage() {
  const { pipelineId } = useParams<{ pipelineId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [rerunOpen, setRerunOpen] = useState(false)

  // description inline 편집 상태. draft 는 편집 중인 임시 값, isEditingDescription 이 true 면 textarea
  // + 수정 완료 / 취소 버튼이 노출된다. antd Typography.editable 은 Enter 가 save 로 강제 가로채져
  // 여러 줄 입력이 불가능해 직접 TextArea 로 구현했다.
  const [isEditingDescription, setIsEditingDescription] = useState(false)
  const [descriptionDraft, setDescriptionDraft] = useState('')

  const { data: pipeline, isLoading, error } = useQuery({
    queryKey: ['automation', 'pipeline', pipelineId],
    queryFn: () => (pipelineId ? getPipeline(pipelineId) : Promise.resolve(null)),
    enabled: Boolean(pipelineId),
  })

  // Description inline 편집. 저장 성공 시 상세 / 목록 / DAG 전부 invalidate (목록에서도 description 을
  // 한 줄 요약으로 보여주고 있어 일관성 유지).
  const descriptionMutation = useMutation({
    mutationFn: (nextDescription: string) =>
      updatePipelineDescription(pipelineId!, nextDescription),
    onSuccess: () => {
      message.success('설명이 저장됐습니다')
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`저장 실패: ${error.message}`)
    },
  })

  const startDescriptionEdit = () => {
    setDescriptionDraft(pipeline?.description ?? '')
    setIsEditingDescription(true)
  }

  const cancelDescriptionEdit = () => {
    setIsEditingDescription(false)
  }

  const saveDescriptionEdit = async () => {
    // trailing whitespace 만 다를 경우는 저장 호출 없이 편집 종료.
    const normalized = descriptionDraft.replace(/\s+$/g, '')
    const current = (pipeline?.description ?? '').replace(/\s+$/g, '')
    if (normalized === current) {
      setIsEditingDescription(false)
      return
    }
    try {
      await descriptionMutation.mutateAsync(normalized)
      setIsEditingDescription(false)
    } catch {
      // onError 에서 이미 토스트 노출. 편집 모드는 유지해 사용자가 재시도 가능.
    }
  }

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
      <Button
        type="text"
        size="small"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/automation')}
        style={{ padding: '0 4px', marginBottom: 8 }}
      >
        목록으로
      </Button>
      <Breadcrumb
        style={{ marginBottom: 12 }}
        items={[
          { title: <Link to="/automation">Automation</Link> },
          { title: pipeline.name },
        ]}
      />
      <Space
        align="center"
        style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}
      >
        <Space align="center" size={8}>
          <TaskTypeTag taskType={pipeline.task_type} variant="long" />
          <Title level={3} style={{ margin: 0 }}>
            {pipeline.name}
          </Title>
        </Space>
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

      {/*
        description 섹션 — 독립 Card 로 분리해 시각적 경계 명확화.
        편집 컨트롤은 Card.extra 에 배치. 편집 모드에선 `취소` + `수정 완료` 2 버튼.
        antd Typography.editable 은 Enter 를 save 로 강제해 여러 줄 입력이 막히므로 TextArea 로 직접 구현.
      */}
      <Card
        size="small"
        title="설명"
        style={{ marginBottom: 16 }}
        extra={
          isEditingDescription ? (
            <Space>
              <Button
                size="small"
                onClick={cancelDescriptionEdit}
                disabled={descriptionMutation.isPending}
              >
                취소
              </Button>
              <Button
                size="small"
                type="primary"
                loading={descriptionMutation.isPending}
                onClick={saveDescriptionEdit}
              >
                수정 완료
              </Button>
            </Space>
          ) : (
            <Button
              size="small"
              type="text"
              icon={<EditOutlined />}
              onClick={startDescriptionEdit}
            >
              수정
            </Button>
          )
        }
      >
        {isEditingDescription ? (
          <TextArea
            value={descriptionDraft}
            onChange={(event) => setDescriptionDraft(event.target.value)}
            placeholder="설명을 입력해 주세요 — 다른 사용자가 이 파이프라인의 목적을 한 눈에 알 수 있게. Enter = 줄바꿈, 저장은 수정 완료 버튼."
            autoSize={{ minRows: 3, maxRows: 12 }}
            maxLength={1000}
            showCount
            autoFocus
            style={{ fontSize: 14, lineHeight: 1.6 }}
          />
        ) : (
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.6,
              color: pipeline.description ? undefined : '#8c8c8c',
              whiteSpace: 'pre-wrap',
              minHeight: 24,
            }}
          >
            {pipeline.description ??
              '설명을 입력해 주세요 — 다른 사용자가 이 파이프라인의 목적을 한 눈에 알 수 있게 작성하면 좋습니다.'}
          </div>
        )}
      </Card>

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
