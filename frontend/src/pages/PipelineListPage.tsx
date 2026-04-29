/**
 * PipelineListPage — Pipeline (concept) 목록 + 행 클릭 인라인 expand.
 *
 * v7.11 (feature/pipeline-family-and-version):
 *   - 행 클릭 시 그 행이 아래로 펼쳐짐 — 개념 메타 + 모든 versions (세로 목록)
 *   - 각 version 행: 클릭 시 미니 상세 토글, "상세" 버튼 → 풀 페이지
 *   - 행의 "상세 보기" 버튼 → 최신 active version 풀 페이지로 이동
 *   - "실행" 버튼 → Version Resolver Modal (최신 active version 의 config 사용)
 *
 * URL: `/pipelines` (concept 목록), `/pipelines/runs` (별도 PipelineHistoryPage),
 *       `/pipeline-versions/:id` (PipelineVersion 상세 페이지 — F-8).
 */
import { useMemo, useState } from 'react'
import {
  Typography,
  Table,
  Tag,
  Button,
  Space,
  Switch,
  Input,
  message,
  Alert,
  Tooltip,
  Descriptions,
  Empty,
} from 'antd'
import {
  PlayCircleOutlined,
  EditOutlined,
  ReloadOutlined,
  EyeOutlined,
  RightOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import {
  pipelineConceptsApi,
  pipelineVersionsApi,
} from '@/api/pipeline'
import type {
  PipelineEntityResponse,
  PipelineListItem,
  PipelineVersionResponse,
  PipelineVersionSummary,
} from '@/types/pipeline'
import { VersionResolverModal } from '@/components/pipeline/VersionResolverModal'
import { CreatePipelineButton } from '@/components/pipeline/CreatePipelineButton'

const { Title, Text } = Typography

export function PipelineListPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [includeInactive, setIncludeInactive] = useState(false)
  const [nameFilter, setNameFilter] = useState('')

  // 행 인라인 expand 상태 — 한 번에 한 concept 만 펼침
  const [expandedConceptId, setExpandedConceptId] = useState<string | null>(null)
  const [expandedVersionId, setExpandedVersionId] = useState<string | null>(null)

  // 실행 모달 상태 — version 단위
  const [resolverVersion, setResolverVersion] = useState<PipelineVersionResponse | null>(null)
  const [resolverOpen, setResolverOpen] = useState(false)

  const listQuery = useQuery({
    queryKey: ['pipeline-concepts', { includeInactive, nameFilter }],
    queryFn: () =>
      pipelineConceptsApi
        .list({
          include_inactive: includeInactive,
          name_filter: nameFilter || undefined,
          limit: 100,
        })
        .then((r) => r.data),
  })

  // 펼친 concept 의 상세 (versions 포함)
  const conceptDetailQuery = useQuery({
    queryKey: ['pipeline-concept-detail', expandedConceptId],
    queryFn: () =>
      expandedConceptId
        ? pipelineConceptsApi.get(expandedConceptId).then((r) => r.data)
        : null,
    enabled: !!expandedConceptId,
  })

  // 펼친 version 의 상세 (config / 메타)
  const versionDetailQuery = useQuery({
    queryKey: ['pipeline-version-detail', expandedVersionId],
    queryFn: () =>
      expandedVersionId
        ? pipelineVersionsApi.get(expandedVersionId).then((r) => r.data)
        : null,
    enabled: !!expandedVersionId,
  })

  const totalFallback = useMemo(() => listQuery.data?.total ?? 0, [listQuery.data])

  const togglePipelineActive = useMutation({
    mutationFn: async (vars: { id: string; nextValue: boolean }) => {
      const r = await pipelineConceptsApi.update(vars.id, { is_active: vars.nextValue })
      return r.data
    },
    onSuccess: (_data, vars) => {
      message.success(
        vars.nextValue
          ? '활성화했습니다. 이제 run 을 제출할 수 있습니다.'
          : '비활성으로 전환했습니다. 자동화가 있으면 error 상태가 됩니다.',
      )
      queryClient.invalidateQueries({ queryKey: ['pipeline-concepts'] })
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err as Error)?.message
        ?? '알 수 없는 오류'
      message.error(`처리 실패: ${msg}`)
    },
  })

  const openResolverForLatestVersion = async (row: PipelineListItem) => {
    // 목록 행에는 latest_version 문자열만 있고 id 가 없음.
    // concept 상세를 가져와 latest active version id 를 추출 후 version 상세 fetch.
    try {
      const concept = (await pipelineConceptsApi.get(row.id)).data
      const latest = concept.latest_version
      if (!latest) {
        message.warning('실행 가능한 active version 이 없습니다.')
        return
      }
      const detail = await pipelineVersionsApi.get(latest.id)
      setResolverVersion(detail.data)
      setResolverOpen(true)
    } catch (err) {
      const msg = (err as Error)?.message ?? '버전 조회 실패'
      message.error(`PipelineVersion 조회 실패: ${msg}`)
    }
  }

  const openResolverForVersion = async (versionId: string) => {
    try {
      const detail = await pipelineVersionsApi.get(versionId)
      setResolverVersion(detail.data)
      setResolverOpen(true)
    } catch (err) {
      const msg = (err as Error)?.message ?? '버전 조회 실패'
      message.error(`PipelineVersion 조회 실패: ${msg}`)
    }
  }

  const goToVersionDetail = (versionId: string) => {
    navigate(`/pipeline-versions/${versionId}`)
  }

  const goToLatestActiveDetail = (concept: PipelineEntityResponse) => {
    if (!concept.latest_version) {
      message.warning('active version 이 없습니다.')
      return
    }
    goToVersionDetail(concept.latest_version.id)
  }

  const columns: ColumnsType<PipelineListItem> = [
    {
      title: '이름',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, row) => (
        <Space direction="vertical" size={0}>
          <Space size={4}>
            <Text strong>{name}</Text>
            {row.latest_version && (
              <Tag style={{ margin: 0, fontSize: 10 }}>v{row.latest_version}</Tag>
            )}
            {row.version_count > 1 && (
              <Tag color="cyan" style={{ margin: 0, fontSize: 10 }}>
                +{row.version_count - 1}개 버전
              </Tag>
            )}
            {!row.is_active && (
              <Tooltip title="is_active=FALSE (soft-deleted). 새 run 제출 차단.">
                <Tag color="default" style={{ margin: 0, fontSize: 10 }}>비활성</Tag>
              </Tooltip>
            )}
            {row.has_automation && (
              <Tag color="purple" style={{ margin: 0, fontSize: 10 }}>auto</Tag>
            )}
            {row.family_name && (
              <Tag color="gold" style={{ margin: 0, fontSize: 10 }}>
                {row.family_name}
              </Tag>
            )}
          </Space>
          {row.description && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {row.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: 'Task',
      dataIndex: 'task_type',
      key: 'task_type',
      width: 140,
      render: (taskType: string) => {
        const color =
          taskType === 'DETECTION' ? 'geekblue'
          : taskType === 'CLASSIFICATION' ? 'magenta'
          : 'default'
        return <Tag color={color} style={{ margin: 0 }}>{taskType}</Tag>
      },
    },
    {
      title: 'Output',
      key: 'output',
      width: 200,
      render: (_v, row) => (
        <Text style={{ fontSize: 12 }}>
          {row.output_group_name ?? '—'} / {row.output_split ?? '—'}
        </Text>
      ),
    },
    {
      title: '실행',
      dataIndex: 'run_count',
      key: 'run_count',
      width: 110,
      render: (count: number, row) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{count}회</Text>
          {row.last_run_at && (
            <Text type="secondary" style={{ fontSize: 10 }}>
              {dayjs(row.last_run_at).format('YY-MM-DD HH:mm')}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '수정',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 120,
      render: (dt: string) => (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {dayjs(dt).format('YY-MM-DD HH:mm')}
        </Text>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 280,
      render: (_v, row) => (
        <Space size={6} onClick={(e) => e.stopPropagation()}>
          <Tooltip title={row.is_active ? '실행 전 input version 선택' : '비활성 Pipeline 은 실행 불가'}>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              disabled={!row.is_active}
              onClick={() => openResolverForLatestVersion(row)}
            >
              실행
            </Button>
          </Tooltip>
          <Tooltip title="최신 active version 으로 풀 상세 진입">
            <Button
              size="small"
              icon={<EyeOutlined />}
              disabled={!row.latest_version}
              onClick={async () => {
                try {
                  const concept = (await pipelineConceptsApi.get(row.id)).data
                  goToLatestActiveDetail(concept)
                } catch (err) {
                  message.error(`Pipeline 조회 실패: ${(err as Error)?.message ?? ''}`)
                }
              }}
            >
              상세 보기
            </Button>
          </Tooltip>
          <Tooltip title={row.is_active ? '비활성으로 전환 — 새 run 제출 차단' : '활성으로 복원'}>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => togglePipelineActive.mutate({ id: row.id, nextValue: !row.is_active })}
            >
              {row.is_active ? '비활성' : '복원'}
            </Button>
          </Tooltip>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <style>{`
        .pipeline-concept-expanded-row > .ant-table-cell {
          border-left: 3px solid #1677ff !important;
        }
      `}</style>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Title level={3} style={{ margin: 0 }}>
            파이프라인 목록
            <Text type="secondary" style={{ fontSize: 13, marginLeft: 12 }}>
              {totalFallback}건
            </Text>
          </Title>
          <Space>
            <Input.Search
              placeholder="이름으로 검색"
              allowClear
              style={{ width: 220 }}
              onSearch={(value) => setNameFilter(value)}
            />
            <Space size={4}>
              <Text style={{ fontSize: 12 }}>비활성 포함</Text>
              <Switch
                size="small"
                checked={includeInactive}
                onChange={setIncludeInactive}
              />
            </Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => queryClient.invalidateQueries({ queryKey: ['pipeline-concepts'] })}
            >
              새로고침
            </Button>
            <CreatePipelineButton />
          </Space>
        </Space>
        <Alert
          type="info"
          showIcon
          closable
          message="행을 클릭하면 그 행 아래로 버전 목록이 펼쳐집니다."
          description="Pipeline = 개념 정체성. 같은 Pipeline 안에 여러 version 이 누적되며, 실행 시점에 input version 을 선택합니다."
          style={{ marginBottom: 0 }}
        />
        <Table<PipelineListItem>
          rowKey="id"
          loading={listQuery.isLoading}
          dataSource={listQuery.data?.items ?? []}
          columns={columns}
          pagination={false}
          size="middle"
          rowClassName={(row) => (row.is_active ? '' : 'inactive-row')}
          expandable={{
            expandedRowKeys: expandedConceptId ? [expandedConceptId] : [],
            expandedRowClassName: () => 'pipeline-concept-expanded-row',
            // 한 번에 한 행만 펼치도록 onExpand 에서 직접 컨트롤
            onExpand: (expanded, record) => {
              setExpandedConceptId(expanded ? record.id : null)
              setExpandedVersionId(null)
            },
            expandedRowRender: (record) => {
              const isCurrent = expandedConceptId === record.id
              return (
                <ExpandedConceptContent
                  conceptDetail={isCurrent ? conceptDetailQuery.data ?? null : null}
                  loading={isCurrent && conceptDetailQuery.isLoading}
                  expandedVersionId={expandedVersionId}
                  setExpandedVersionId={setExpandedVersionId}
                  versionDetail={versionDetailQuery.data ?? null}
                  versionDetailLoading={versionDetailQuery.isLoading}
                  onVersionDetailClick={goToVersionDetail}
                  onVersionRunClick={openResolverForVersion}
                  onConceptDetailClick={goToLatestActiveDetail}
                />
              )
            },
          }}
          onRow={(row) => ({
            onClick: () => {
              const next = expandedConceptId === row.id ? null : row.id
              setExpandedConceptId(next)
              setExpandedVersionId(null)
            },
            style: { cursor: 'pointer' },
          })}
        />
      </Space>

      <VersionResolverModal
        open={resolverOpen}
        pipelineVersion={resolverVersion}
        onClose={() => setResolverOpen(false)}
        onSubmitted={(runId) => {
          message.success(`파이프라인 실행 제출 완료 (run_id=${runId.slice(0, 8)}...)`)
        }}
      />
    </div>
  )
}


interface VersionRowProps {
  summary: PipelineVersionSummary
  expanded: boolean
  detail: PipelineVersionResponse | null
  detailLoading: boolean
  onToggle: () => void
  onDetailClick: () => void
  onRunClick: () => void
}

function VersionRow({
  summary,
  expanded,
  detail,
  detailLoading,
  onToggle,
  onDetailClick,
  onRunClick,
}: VersionRowProps) {
  const taskCount = detail?.config?.tasks
    ? Object.keys(detail.config.tasks as Record<string, unknown>).length
    : null
  return (
    <div
      style={{
        border: '1px solid #f0f0f0',
        borderRadius: 6,
        padding: '8px 10px',
        background: expanded ? '#fafafa' : '#fff',
      }}
    >
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Space
          size={6}
          style={{ cursor: 'pointer', flex: 1 }}
          onClick={onToggle}
        >
          <RightOutlined
            rotate={expanded ? 90 : 0}
            style={{ fontSize: 11, color: '#888' }}
          />
          <Tag style={{ margin: 0 }}>v{summary.version}</Tag>
          {!summary.is_active && <Tag color="default">비활성</Tag>}
          {summary.has_automation && <Tag color="purple">auto</Tag>}
          <Text type="secondary" style={{ fontSize: 11 }}>
            {dayjs(summary.created_at).format('YY-MM-DD HH:mm')}
          </Text>
        </Space>
        <Space size={6} onClick={(e) => e.stopPropagation()}>
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            disabled={!summary.is_active}
            onClick={onRunClick}
          >
            실행
          </Button>
          <Button size="small" icon={<EyeOutlined />} onClick={onDetailClick}>
            상세
          </Button>
        </Space>
      </Space>
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px dashed #eee' }}>
          {detailLoading && <Text type="secondary">로딩…</Text>}
          {detail && (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                노드 수: {taskCount ?? '—'} | schema_version:{' '}
                {String((detail.config as Record<string, unknown>)?.schema_version ?? '—')}
              </Text>
              <Text type="secondary" style={{ fontSize: 11 }}>
                config 본문은 "상세" 버튼으로 풀 페이지에서 확인하세요.
              </Text>
            </Space>
          )}
        </div>
      )}
    </div>
  )
}


/**
 * 행 클릭 시 인라인으로 펼쳐지는 concept 메타 + versions 목록.
 * Table.expandable.expandedRowRender 안에서 호출.
 */
interface ExpandedConceptContentProps {
  conceptDetail: PipelineEntityResponse | null
  loading: boolean
  expandedVersionId: string | null
  setExpandedVersionId: (id: string | null) => void
  versionDetail: PipelineVersionResponse | null
  versionDetailLoading: boolean
  onVersionDetailClick: (versionId: string) => void
  onVersionRunClick: (versionId: string) => void
  onConceptDetailClick: (concept: PipelineEntityResponse) => void
}

function ExpandedConceptContent({
  conceptDetail,
  loading,
  expandedVersionId,
  setExpandedVersionId,
  versionDetail,
  versionDetailLoading,
  onVersionDetailClick,
  onVersionRunClick,
  onConceptDetailClick,
}: ExpandedConceptContentProps) {
  if (loading) {
    return <Text type="secondary">로딩 중…</Text>
  }
  if (!conceptDetail) {
    return <Text type="secondary">상세 정보를 불러오지 못했습니다.</Text>
  }
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Title level={5} style={{ margin: 0 }}>
            {conceptDetail.name}
          </Title>
          <Button
            type="primary"
            size="small"
            icon={<EyeOutlined />}
            disabled={!conceptDetail.latest_version}
            onClick={() => onConceptDetailClick(conceptDetail)}
          >
            상세 보기 (최신 active)
          </Button>
        </Space>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="설명" span={2}>
            {conceptDetail.description ?? <Text type="secondary">—</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="Family">
            {conceptDetail.family_name ?? <Text type="secondary">미분류</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="Task">{conceptDetail.task_type}</Descriptions.Item>
          <Descriptions.Item label="Output">
            {conceptDetail.output_group_name} / {conceptDetail.output_split}
          </Descriptions.Item>
          <Descriptions.Item label="활성">
            {conceptDetail.is_active ? <Tag color="green">active</Tag> : <Tag>비활성</Tag>}
          </Descriptions.Item>
        </Descriptions>

        <div>
          <Title level={5} style={{ margin: '0 0 8px 0' }}>
            버전 ({conceptDetail.versions.length}개)
          </Title>
          {conceptDetail.versions.length === 0 && (
            <Empty description="version 이 아직 없습니다." />
          )}
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            {conceptDetail.versions.map((v) => (
              <VersionRow
                key={v.id}
                summary={v}
                expanded={expandedVersionId === v.id}
                onToggle={() =>
                  setExpandedVersionId(expandedVersionId === v.id ? null : v.id)
                }
                detail={expandedVersionId === v.id ? versionDetail ?? null : null}
                detailLoading={
                  expandedVersionId === v.id && versionDetailLoading
                }
                onDetailClick={() => onVersionDetailClick(v.id)}
                onRunClick={() => onVersionRunClick(v.id)}
              />
            ))}
          </Space>
        </div>
      </Space>
    </div>
  )
}
