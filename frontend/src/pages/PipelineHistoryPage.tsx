/**
 * PipelineHistoryPage — 파이프라인 실행 이력 목록
 *
 * AppLayout 내부에 렌더링되는 사이드바가 있는 페이지.
 * 실행 이력을 테이블로 표시하고, "새 파이프라인" 버튼으로 에디터로 이동한다.
 * 행 클릭 시 Drawer로 파이프라인 실행 상세 정보를 표시한다.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Table, Button, Tag, Typography, Space, Card,
  Progress,
} from 'antd'
import type { TableProps } from 'antd'
import type { SortOrder } from 'antd/es/table/interface'
import {
  ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { pipelinesApi } from '@/api/pipeline'
import type { PipelineExecutionResponse } from '@/types/pipeline'
import { formatDate } from '@/utils/format'
import ExecutionDetailDrawer from '@/components/pipeline/ExecutionDetailDrawer'
import { useResizableColumnWidths } from '@/components/common/ResizableTableColumns'
import dayjs from 'dayjs'

/** 백엔드 정렬 키와 1:1 대응 — Table column key 와 일치시켜 onChange 에서 그대로 사용. */
type RunSortKey =
  | 'created_at'
  | 'status'
  | 'started_at'
  | 'finished_at'
  | 'pipeline_name'
  | 'pipeline_version'
  | 'output_dataset_group_name'
  | 'output_dataset_split'
  | 'output_dataset_version'

const { Title, Text } = Typography

/** 상태별 Tag 색상 */
const STATUS_TAG: Record<string, { color: string; label: string }> = {
  PENDING: { color: 'default', label: '대기' },
  RUNNING: { color: 'processing', label: '실행 중' },
  DONE: { color: 'success', label: '완료' },
  FAILED: { color: 'error', label: '실패' },
}

/**
 * 소요 시간을 읽기 좋은 문자열로 변환.
 * started_at/finished_at의 차이만 계산. finishedAt이 없으면 '-' 반환.
 */
function formatDuration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt || !finishedAt) return '-'
  const start = dayjs(startedAt)
  const end = dayjs(finishedAt)
  const diffSeconds = end.diff(start, 'second')
  if (diffSeconds < 60) return `${diffSeconds}초`
  const minutes = Math.floor(diffSeconds / 60)
  const seconds = diffSeconds % 60
  if (minutes < 60) return `${minutes}분 ${seconds}초`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}시간 ${remainMinutes}분`
}

/** config.tasks에서 operator 목록을 순서대로 추출 */
function extractOperatorSequence(config: Record<string, unknown> | null): string[] {
  if (!config || !config.tasks) return []
  const tasks = config.tasks as Record<string, { operator?: string }>
  return Object.values(tasks).map((task) => task.operator ?? '(unknown)')
}

export default function PipelineHistoryPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [sortBy, setSortBy] = useState<RunSortKey>('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [selectedExecution, setSelectedExecution] = useState<PipelineExecutionResponse | null>(null)

  // 컬럼별 초기 너비. 헤더 우측 경계 드래그로 조정 가능.
  const {
    widthByKey: columnWidths,
    buildHeaderCellProps,
    tableComponents,
  } = useResizableColumnWidths({
    pipeline_name: 180,
    pipeline_version: 80,
    output_dataset_group_name: 180,
    output_dataset_split: 90,
    output_dataset_version: 80,
    status: 100,
    progress: 140,
    operator_count: 110,
    started_at: 140,
    duration: 110,
    error_message: 220,
  })

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pipeline-executions', page, pageSize, sortBy, sortOrder],
    queryFn: () =>
      pipelinesApi
        .list({ page, page_size: pageSize, sort_by: sortBy, sort_order: sortOrder })
        .then((r) => r.data),
  })

  // AntD Table onChange — sorter 변경만 서버 정렬 파라미터로 반영.
  const handleTableChange: TableProps<PipelineExecutionResponse>['onChange'] = (
    _pagination, _filters, sorter,
  ) => {
    const activeSorter = Array.isArray(sorter) ? sorter[0] : sorter
    if (!activeSorter || !activeSorter.order) {
      // 정렬 해제 → 기본 created_at desc
      setSortBy('created_at')
      setSortOrder('desc')
      return
    }
    const columnKey = activeSorter.columnKey as RunSortKey | undefined
    if (!columnKey) return
    setSortBy(columnKey)
    setSortOrder(activeSorter.order === 'ascend' ? 'asc' : 'desc')
  }

  const sortOrderForColumn = (key: RunSortKey): SortOrder =>
    sortBy === key ? (sortOrder === 'asc' ? 'ascend' : 'descend') : null

  const columns: ColumnsType<PipelineExecutionResponse> = [
    {
      title: '파이프라인명',
      key: 'pipeline_name',
      dataIndex: 'pipeline_name',
      width: columnWidths.pipeline_name,
      onHeaderCell: buildHeaderCellProps('pipeline_name'),
      ellipsis: true,
      sorter: true,
      sortOrder: sortOrderForColumn('pipeline_name'),
      render: (name: string | null) =>
        name ? <Text strong>{name}</Text> : <Text type="secondary">—</Text>,
    },
    {
      title: '버전',
      key: 'pipeline_version',
      dataIndex: 'pipeline_version',
      width: columnWidths.pipeline_version,
      onHeaderCell: buildHeaderCellProps('pipeline_version'),
      sorter: true,
      sortOrder: sortOrderForColumn('pipeline_version'),
      render: (version: string | null) =>
        version ? <Tag style={{ margin: 0 }}>v{version}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: 'Output 그룹',
      key: 'output_dataset_group_name',
      dataIndex: 'output_dataset_group_name',
      width: columnWidths.output_dataset_group_name,
      onHeaderCell: buildHeaderCellProps('output_dataset_group_name'),
      ellipsis: true,
      sorter: true,
      sortOrder: sortOrderForColumn('output_dataset_group_name'),
      render: (name: string | null) =>
        name ? <Text style={{ fontSize: 12 }}>{name}</Text> : <Text type="secondary">—</Text>,
    },
    {
      title: 'Split',
      key: 'output_dataset_split',
      dataIndex: 'output_dataset_split',
      width: columnWidths.output_dataset_split,
      onHeaderCell: buildHeaderCellProps('output_dataset_split'),
      sorter: true,
      sortOrder: sortOrderForColumn('output_dataset_split'),
      render: (split: string | null) =>
        split ? <Tag color="blue" style={{ margin: 0 }}>{split}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '버전',
      key: 'output_dataset_version',
      dataIndex: 'output_dataset_version',
      width: columnWidths.output_dataset_version,
      onHeaderCell: buildHeaderCellProps('output_dataset_version'),
      sorter: true,
      sortOrder: sortOrderForColumn('output_dataset_version'),
      render: (version: string | null) =>
        version ? <Tag style={{ margin: 0 }}>v{version}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '상태',
      key: 'status',
      dataIndex: 'status',
      width: columnWidths.status,
      onHeaderCell: buildHeaderCellProps('status'),
      sorter: true,
      sortOrder: sortOrderForColumn('status'),
      render: (status: string) => {
        const tag = STATUS_TAG[status] ?? { color: 'default', label: status }
        return <Tag color={tag.color}>{tag.label}</Tag>
      },
    },
    {
      title: '진행률',
      key: 'progress',
      width: columnWidths.progress,
      onHeaderCell: buildHeaderCellProps('progress'),
      // 진행률은 서버에서 정렬 가능 컬럼 아님 — sorter 미적용
      render: (_: unknown, record: PipelineExecutionResponse) => {
        if (!record.total_count) return '-'
        const percent = Math.round((record.processed_count / record.total_count) * 100)
        return (
          <Space size={4}>
            <Progress
              percent={percent}
              size="small"
              showInfo={false}
              style={{ width: 60 }}
              status={
                record.status === 'FAILED' ? 'exception'
                  : record.status === 'DONE' ? 'success'
                    : 'active'
              }
            />
            <Text type="secondary" style={{ fontSize: 11 }}>
              {record.processed_count}/{record.total_count}
            </Text>
          </Space>
        )
      },
    },
    {
      title: '처리 단계',
      key: 'operator_count',
      width: columnWidths.operator_count,
      onHeaderCell: buildHeaderCellProps('operator_count'),
      // config 에서 파생되는 값이라 서버 정렬 X
      render: (_: unknown, record: PipelineExecutionResponse) => {
        const recordConfig = record.config as Record<string, unknown> | null
        const ops = extractOperatorSequence(recordConfig)
        if (ops.length === 0) return '-'
        return (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {ops.length}단계
          </Text>
        )
      },
    },
    {
      title: '시작',
      key: 'started_at',
      dataIndex: 'started_at',
      width: columnWidths.started_at,
      onHeaderCell: buildHeaderCellProps('started_at'),
      sorter: true,
      sortOrder: sortOrderForColumn('started_at'),
      render: (val: string | null) => (val ? formatDate(val) : '-'),
    },
    {
      title: '소요 시간',
      key: 'duration',
      width: columnWidths.duration,
      onHeaderCell: buildHeaderCellProps('duration'),
      // 파생 값이라 서버 정렬 X
      render: (_: unknown, record: PipelineExecutionResponse) => {
        if (record.status === 'RUNNING') return '실행 중'
        return formatDuration(record.started_at, record.finished_at)
      },
    },
    {
      title: '에러',
      key: 'error_message',
      dataIndex: 'error_message',
      width: columnWidths.error_message,
      onHeaderCell: buildHeaderCellProps('error_message'),
      ellipsis: true,
      render: (msg: string | null) =>
        msg ? (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            {msg}
          </Typography.Text>
        ) : (
          '-'
        ),
    },
  ]

  return (
    <div className="pipeline-history-page">
      {/*
        AntD 기본은 `.ant-table-content > table { width: 100% }` 라 컨테이너 폭이
        컬럼 합보다 넓을 때 잉여가 `table-layout: fixed` 컬럼들에 비례 분배된다.
        결과적으로 set width 와 실제 render width 가 어긋나고, 가장 넓은 컬럼
        (여기서는 파이프라인명) 이 잉여의 가장 큰 절대량을 받아 우측 공백이
        길어지고, 드래그로 줄여도 잉여 분배가 즉시 메꿔 시각적으로 안 줄어든다.
        → 본 페이지에 한해 inner table 폭을 max-content 로 고정해 분배 차단.
        min-width 는 0 으로 내려 컨테이너가 더 넓어도 table 이 늘지 않게 함.
        남는 공간은 wrapper (.ant-table-content) 우측 여백.
      */}
      <style>{`
        .pipeline-history-page .ant-table-content > table,
        .pipeline-history-page .ant-table-body > table {
          width: max-content !important;
          min-width: 0 !important;
        }
      `}</style>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          파이프라인 실행 이력
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
            새로고침
          </Button>
          {/* "새 파이프라인" 버튼은 v7.10 §9-7 피드백에 따라 "파이프라인 목록" 페이지로 이동.
              실행 이력 페이지에서는 이력 조회 외 다른 동작은 하지 않는다. */}
        </Space>
      </div>

      <Card>
        <Table
          dataSource={data?.items ?? []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          components={tableComponents}
          onChange={handleTableChange}
          onRow={(record) => ({
            onClick: () => setSelectedExecution(record),
            style: { cursor: 'pointer' },
          })}
          pagination={{
            current: page,
            pageSize,
            total: data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `총 ${total}건`,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
            },
          }}
          // 컬럼 너비 합이 컨테이너보다 넓어지면 가로 스크롤. (헤더 드래그로 늘릴 때 필요)
          scroll={{ x: 'max-content' }}
          size="middle"
        />
      </Card>

      {/* 실행 상세 Drawer */}
      <ExecutionDetailDrawer
        execution={selectedExecution}
        onClose={() => setSelectedExecution(null)}
        onNavigateToDataset={(groupId, datasetId) => navigate(`/datasets/${groupId}/${datasetId}`)}
      />

      {/* v7.10 §9-7 피드백: 태스크 타입 선택 Modal + "새 파이프라인" 버튼 은
          CreatePipelineButton 컴포넌트로 추출되어 PipelineListPage 에서 사용된다. */}
    </div>
  )
}
