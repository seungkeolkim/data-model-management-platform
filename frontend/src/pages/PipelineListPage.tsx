/**
 * PipelineListPage — Pipeline (정적 템플릿) 목록.
 *
 * v7.10 핸드오프 027 §9-7. URL: `/pipelines` (§9-7 재배선 시 기존 실행 이력 페이지는
 * `/pipelines/runs` 로 이동).
 *
 * 각 행 우측에 "실행" 버튼 — 클릭 시 Version Resolver Modal (027 §4-3) 로 input
 * version 확정 후 `POST /pipelines/entities/{id}/runs` dispatch.
 * is_active=FALSE (soft-deleted) Pipeline 은 실행 버튼 비활성 + soft-deleted 배지.
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
} from 'antd'
import { PlayCircleOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { pipelineEntitiesApi } from '@/api/pipeline'
import type { PipelineEntityResponse, PipelineListItem } from '@/types/pipeline'
import { VersionResolverModal } from '@/components/pipeline/VersionResolverModal'
import { CreatePipelineButton } from '@/components/pipeline/CreatePipelineButton'

const { Title, Text } = Typography

export function PipelineListPage() {
  const queryClient = useQueryClient()
  const [includeInactive, setIncludeInactive] = useState(false)
  const [nameFilter, setNameFilter] = useState('')
  const [resolverPipeline, setResolverPipeline] = useState<PipelineEntityResponse | null>(null)
  const [resolverOpen, setResolverOpen] = useState(false)

  const listQuery = useQuery({
    queryKey: ['pipeline-entities', { includeInactive, nameFilter }],
    queryFn: () =>
      pipelineEntitiesApi
        .list({
          include_inactive: includeInactive,
          name_filter: nameFilter || undefined,
          limit: 100,
        })
        .then((r) => r.data),
  })

  const totalFallback = useMemo(() => listQuery.data?.total ?? 0, [listQuery.data])

  const togglePipelineActive = useMutation({
    mutationFn: async (vars: { id: string; nextValue: boolean }) => {
      const r = await pipelineEntitiesApi.update(vars.id, { is_active: vars.nextValue })
      return r.data
    },
    onSuccess: (_data, vars) => {
      message.success(
        vars.nextValue
          ? '활성화했습니다. 이제 run 을 제출할 수 있습니다.'
          : '비활성으로 전환했습니다. 자동화가 있으면 error 상태가 됩니다.',
      )
      queryClient.invalidateQueries({ queryKey: ['pipeline-entities'] })
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err as Error)?.message
        ?? '알 수 없는 오류'
      message.error(`처리 실패: ${msg}`)
    },
  })

  const openResolverForPipeline = async (row: PipelineListItem) => {
    // 목록 응답에는 config 가 빠져 있으므로 상세 요청 후 Modal 에 전달
    try {
      const detail = await pipelineEntitiesApi.get(row.id)
      setResolverPipeline(detail.data)
      setResolverOpen(true)
    } catch (err) {
      const msg = (err as Error)?.message ?? '상세 조회 실패'
      message.error(`Pipeline 상세 조회 실패: ${msg}`)
    }
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
            <Tag style={{ margin: 0, fontSize: 10 }}>v{row.version}</Tag>
            {!row.is_active && (
              <Tooltip title="is_active=FALSE (soft-deleted). 새 run 제출 차단.">
                <Tag color="default" style={{ margin: 0, fontSize: 10 }}>비활성</Tag>
              </Tooltip>
            )}
            {row.has_automation && <Tag color="purple" style={{ margin: 0, fontSize: 10 }}>auto</Tag>}
          </Space>
          {row.description && (
            <Text type="secondary" style={{ fontSize: 11 }}>{row.description}</Text>
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
      width: 230,
      render: (_v, row) => (
        <Space size={6}>
          <Tooltip title={row.is_active ? '실행 전 input version 을 선택합니다' : '비활성 Pipeline 은 실행 불가'}>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              disabled={!row.is_active}
              onClick={() => openResolverForPipeline(row)}
            >
              실행
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
              onClick={() => queryClient.invalidateQueries({ queryKey: ['pipeline-entities'] })}
            >
              새로고침
            </Button>
            {/* v7.10 §9-7 피드백: "새 파이프라인" 진입은 실행 이력이 아닌 목록 페이지 쪽. */}
            <CreatePipelineButton />
          </Space>
        </Space>
        <Alert
          type="info"
          showIcon
          closable
          message="Pipeline = 정적 템플릿. 실행 시 버전을 선택하세요."
          description="에디터에서는 (group, split) 까지만 저장됩니다. 버전은 각 실행 시 Version Resolver 모달에서 선택합니다."
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
        />
      </Space>

      <VersionResolverModal
        open={resolverOpen}
        pipeline={resolverPipeline}
        onClose={() => setResolverOpen(false)}
        onSubmitted={(runId) => {
          message.success(`파이프라인 실행이 제출되었습니다. (run_id=${runId.slice(0, 8)}...)`)
        }}
      />
    </div>
  )
}
