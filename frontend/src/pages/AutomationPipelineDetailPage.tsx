import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { ArrowLeftOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  getConcept,
  getReassignHint,
  getVersion,
  listVersions,
  reassignAutomation,
  updateConceptDescription,
} from '@/api/automation'
import AutomationSettingsForm from '@/components/automation/AutomationSettingsForm'
import UpstreamDeltaList from '@/components/automation/UpstreamDeltaList'
import RecentAutomationRuns from '@/components/automation/RecentAutomationRuns'
import ManualRerunModal from '@/components/automation/ManualRerunModal'
import { TaskTypeTag, VersionTag } from '@/components/automation/StatusBadge'

const { Title, Text } = Typography
const { TextArea } = Input

/**
 * Automation 상세 페이지 — v7.13 baseline (PipelineVersion 단위, URL `:versionId`).
 *
 * URL 키가 versionId 인 이유: automation 이 PipelineVersion 단위로 1:0..1 로 붙으므로 URL 도 version 을
 * 가리키는 게 직관적 (북마크 / 공유 시 "어느 version 의 automation 을 보고 있는지" 가 URL 만으로 명확).
 *
 * 주요 영역:
 *   1. 헤더 — concept name + 현재 version Tag + 같은 concept 의 다른 version 드롭다운 + 수동 재실행 버튼
 *   2. Reassign hint Alert — 027 §12-6: 같은 concept 의 다른 version 에 active automation 이 있으면
 *      상단에 Alert + "이 version 으로 이동" 버튼. 닫기 가능 (다음 페이지 진입 시 다시 노출).
 *   3. Concept description 편집 — concept 단위 (updateConceptDescription).
 *      Version 의 description ("이 버전에서 무엇을 바꿨는가" 메모) 은 헤더 옆에 readonly 로 별도 표시.
 *   4. 메타 카드 — task_type / family / input splits / output / task summaries
 *   5. 좌: AutomationSettingsForm (등록 / 미등록 분기) — 우: UpstreamDeltaList + RecentAutomationRuns
 *   6. 수동 재실행 모달
 */
export default function AutomationPipelineDetailPage() {
  const { versionId } = useParams<{ versionId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [rerunOpen, setRerunOpen] = useState(false)

  // version 조회 — concept FK 도 같이 들어있다 (mock 응답에 임베드).
  const versionQuery = useQuery({
    queryKey: ['automation', 'version', versionId],
    queryFn: () => (versionId ? getVersion(versionId) : Promise.resolve(null)),
    enabled: Boolean(versionId),
  })
  const version = versionQuery.data ?? null

  // concept (description / family / output / latest_active_version 등 표시용).
  const conceptQuery = useQuery({
    queryKey: ['automation', 'concept', version?.pipeline_id],
    queryFn: () => (version ? getConcept(version.pipeline_id) : Promise.resolve(null)),
    enabled: Boolean(version),
  })
  const concept = conceptQuery.data ?? null

  // 같은 concept 의 다른 versions — 헤더 드롭다운에 사용.
  const versionsQuery = useQuery({
    queryKey: ['automation', 'versions', version?.pipeline_id],
    queryFn: () => (version ? listVersions(version.pipeline_id) : Promise.resolve([])),
    enabled: Boolean(version),
  })
  const conceptVersions = versionsQuery.data ?? []

  // Reassign hint — 같은 concept 의 다른 version 에 active automation 이 있으면 노티 (027 §12-6).
  const hintQuery = useQuery({
    queryKey: ['automation', 'reassign-hint', versionId],
    queryFn: () => (versionId ? getReassignHint(versionId) : Promise.resolve(null)),
    enabled: Boolean(versionId),
  })
  const reassignHint = hintQuery.data ?? null

  const reassignMutation = useMutation({
    mutationFn: () =>
      reassignHint && versionId
        ? reassignAutomation(reassignHint.automation_id, versionId)
        : Promise.reject(new Error('reassign 대상이 없습니다')),
    onSuccess: () => {
      message.success('automation 이 이 version 으로 이동됐습니다')
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`reassign 실패: ${error.message}`)
    },
  })

  // Concept description inline 편집.
  const [isEditingDescription, setIsEditingDescription] = useState(false)
  const [descriptionDraft, setDescriptionDraft] = useState('')
  const descriptionMutation = useMutation({
    mutationFn: (nextDescription: string) =>
      concept ? updateConceptDescription(concept.id, nextDescription) : Promise.reject(),
    onSuccess: () => {
      message.success('설명이 저장됐습니다')
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`저장 실패: ${error.message}`)
    },
  })
  const startDescriptionEdit = () => {
    setDescriptionDraft(concept?.description ?? '')
    setIsEditingDescription(true)
  }
  const cancelDescriptionEdit = () => setIsEditingDescription(false)
  const saveDescriptionEdit = async () => {
    const normalized = descriptionDraft.replace(/\s+$/g, '')
    const current = (concept?.description ?? '').replace(/\s+$/g, '')
    if (normalized === current) {
      setIsEditingDescription(false)
      return
    }
    try {
      await descriptionMutation.mutateAsync(normalized)
      setIsEditingDescription(false)
    } catch {
      // onError 토스트로 안내 — 편집 모드 유지.
    }
  }

  if (versionQuery.isLoading || conceptQuery.isLoading) {
    return <Card loading />
  }

  if (versionQuery.error) {
    return (
      <Alert
        type="error"
        message="Pipeline version 로드 실패"
        description={(versionQuery.error as Error).message}
        showIcon
      />
    )
  }

  if (!version || !concept) {
    return (
      <Empty
        description={
          <>
            Pipeline version 을 찾을 수 없습니다.
            <br />
            <Link to="/automation">목록으로 돌아가기</Link>
          </>
        }
      />
    )
  }

  // 수동 재실행은 "automation 등록 + error 아님" 일 때만.
  const automation = version.automation
  const rerunDisabled = !automation || automation.status === 'error'
  const rerunDisableReason = !automation
    ? '이 version 에는 등록된 automation 이 없습니다. 먼저 자동화를 등록하세요.'
    : automation.status === 'error'
      ? 'Error 상태에서는 재실행이 비활성화됩니다.'
      : null

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
          { title: concept.name },
          { title: `v${version.version}` },
        ]}
      />

      {/* 헤더 — concept name + version drop + 수동 재실행 */}
      <Space
        align="center"
        style={{ justifyContent: 'space-between', width: '100%', marginBottom: 16 }}
      >
        <Space align="center" size={8} wrap>
          <TaskTypeTag taskType={concept.task_type} variant="long" />
          <Title level={3} style={{ margin: 0 }}>
            {concept.name}
          </Title>
          <VersionTag version={version.version} />
          {/* 같은 concept 의 다른 version 으로 빠르게 이동 */}
          {conceptVersions.length > 1 && (
            <Select<string>
              size="small"
              style={{ minWidth: 150 }}
              value={version.id}
              onChange={(nextId) => navigate(`/automation/versions/${nextId}`)}
              options={conceptVersions.map((candidate) => ({
                value: candidate.id,
                label: `v${candidate.version}${
                  candidate.automation && candidate.automation.is_active ? ' · automation' : ''
                }`,
              }))}
            />
          )}
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

      {rerunDisableReason && (
        <Alert
          type={automation?.status === 'error' ? 'warning' : 'info'}
          showIcon
          message="수동 재실행이 비활성화 상태입니다"
          description={rerunDisableReason}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Reassign hint — 같은 concept 의 다른 version 에 active automation 이 있다는 안내 (027 §12-6) */}
      {reassignHint && (
        <Alert
          type="info"
          showIcon
          closable
          style={{ marginBottom: 16 }}
          message={`Automation 이 v${reassignHint.active_on_version} 에 등록돼 있습니다`}
          description={
            <Space direction="vertical" size={4}>
              <Text>
                현재 보고 계신 v{reassignHint.current_version} 에는 automation 이 등록돼 있지
                않습니다. 같은 Pipeline 의 v{reassignHint.active_on_version} 에 active automation 이
                있는데, v{reassignHint.current_version} 으로 옮기시려면 아래 버튼을 누르세요.
              </Text>
              <Space>
                <Button
                  type="primary"
                  size="small"
                  loading={reassignMutation.isPending}
                  onClick={() => reassignMutation.mutate()}
                >
                  이 version 으로 옮기기
                </Button>
                <Button
                  size="small"
                  onClick={() =>
                    navigate(`/automation/versions/${reassignHint.active_on_version_id}`)
                  }
                >
                  v{reassignHint.active_on_version} 보러 가기
                </Button>
              </Space>
            </Space>
          }
        />
      )}

      {/* Concept description 카드 — concept 단위 inline 편집 */}
      <Card
        size="small"
        title="설명 (Pipeline 전체)"
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
            placeholder="이 Pipeline 전체의 목적을 설명해 주세요. Enter = 줄바꿈, 저장은 수정 완료 버튼."
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
              color: concept.description ? undefined : '#8c8c8c',
              whiteSpace: 'pre-wrap',
              minHeight: 24,
            }}
          >
            {concept.description ??
              '설명을 입력해 주세요 — 다른 사용자가 이 Pipeline 의 목적을 한 눈에 알 수 있게 작성하면 좋습니다.'}
          </div>
        )}
      </Card>

      {/* 메타 카드 — version description + family + input splits + output + tasks */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          {version.description && (
            <Space size={8} wrap>
              <Text strong>이 버전 메모:</Text>
              <Text>{version.description}</Text>
            </Space>
          )}
          {concept.family_name && concept.family_color && (
            <Space size={8} wrap>
              <Text strong>Family:</Text>
              <Tag color={concept.family_color}>{concept.family_name}</Tag>
            </Space>
          )}
          <Space size={8} wrap>
            <Text strong>입력:</Text>
            {version.input_splits.length === 0 && <Text type="secondary">—</Text>}
            {version.input_splits.map((slot) => (
              <Space key={slot.split_id} size={4}>
                <Tag>{slot.group_name}</Tag>
                <Tag color="geekblue">{slot.split}</Tag>
              </Space>
            ))}
            <Text type="secondary">→</Text>
            <Text strong>출력:</Text>
            <Tag>{concept.output.group_name}</Tag>
            <Tag color="geekblue">{concept.output.split}</Tag>
          </Space>
          {version.task_summaries.length > 0 && (
            <Space size={4} wrap>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Tasks:
              </Text>
              {version.task_summaries.map((task) => (
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
          <AutomationSettingsForm version={version} />
        </Col>
        <Col xs={24} xl={12}>
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <UpstreamDeltaList versionId={version.id} />
            <RecentAutomationRuns versionId={version.id} />
          </Space>
        </Col>
      </Row>

      <ManualRerunModal
        open={rerunOpen}
        versionId={version.id}
        pipelineName={concept.name}
        pipelineVersion={version.version}
        onClose={() => setRerunOpen(false)}
      />
    </div>
  )
}
