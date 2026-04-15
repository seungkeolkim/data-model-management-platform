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
  Table, Button, Tag, Typography, Space, Card, Modal,
  Progress,
} from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  AimOutlined,
  AppstoreOutlined,
  SearchOutlined,
  PictureOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { pipelinesApi } from '@/api/pipeline'
import type { PipelineExecutionResponse } from '@/types/pipeline'
import type { TaskType } from '@/types/dataset'
import { formatDate } from '@/utils/format'
import ExecutionDetailDrawer from '@/components/pipeline/ExecutionDetailDrawer'
import dayjs from 'dayjs'

const { Title, Text } = Typography

/** 상태별 Tag 색상 */
const STATUS_TAG: Record<string, { color: string; label: string }> = {
  PENDING: { color: 'default', label: '대기' },
  RUNNING: { color: 'processing', label: '실행 중' },
  DONE: { color: 'success', label: '완료' },
  FAILED: { color: 'error', label: '실패' },
}

/** 태스크 타입별 표시 정보 */
const TASK_TYPE_OPTIONS: {
  key: TaskType
  label: string
  description: string
  icon: React.ReactNode
  color: string
  ready: boolean
}[] = [
  {
    key: 'DETECTION',
    label: 'Object Detection',
    description: 'COCO/YOLO 포맷 기반 객체 탐지 데이터 변형',
    icon: <AimOutlined style={{ fontSize: 28 }} />,
    color: '#1677ff',
    ready: true,
  },
  {
    key: 'SEGMENTATION',
    label: 'Segmentation',
    description: '세그멘테이션 마스크 기반 데이터 변형',
    icon: <AppstoreOutlined style={{ fontSize: 28 }} />,
    color: '#52c41a',
    ready: false,
  },
  {
    key: 'CLASSIFICATION',
    label: 'Classification',
    description: '이미지 분류 데이터 변형 (단일/다중 head 포함)',
    icon: <PictureOutlined style={{ fontSize: 28 }} />,
    color: '#13c2c2',
    ready: true,
  },
  {
    key: 'ZERO_SHOT',
    label: 'Zero-Shot',
    description: '제로샷 학습용 데이터 변형',
    icon: <SearchOutlined style={{ fontSize: 28 }} />,
    color: '#722ed1',
    ready: false,
  },
]

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
  const [isTypeSelectOpen, setIsTypeSelectOpen] = useState(false)
  const [selectedExecution, setSelectedExecution] = useState<PipelineExecutionResponse | null>(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pipeline-executions', page, pageSize],
    queryFn: () =>
      pipelinesApi.list({ page, page_size: pageSize }).then((r) => r.data),
  })

  const columns: ColumnsType<PipelineExecutionResponse> = [
    {
      title: '파이프라인',
      width: 180,
      ellipsis: true,
      render: (_: unknown, record: PipelineExecutionResponse) => {
        const recordConfig = record.config as Record<string, unknown> | null
        const name = (recordConfig?.name as string) ?? '-'
        return <Text strong>{name}</Text>
      },
    },
    {
      title: '상태',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => {
        const tag = STATUS_TAG[status] ?? { color: 'default', label: status }
        return <Tag color={tag.color}>{tag.label}</Tag>
      },
    },
    {
      title: '진행률',
      width: 140,
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
      width: 140,
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
      dataIndex: 'started_at',
      width: 140,
      render: (val: string | null) => (val ? formatDate(val) : '-'),
    },
    {
      title: '소요 시간',
      width: 120,
      render: (_: unknown, record: PipelineExecutionResponse) => {
        if (record.status === 'RUNNING') return '실행 중'
        return formatDuration(record.started_at, record.finished_at)
      },
    },
    {
      title: '에러',
      dataIndex: 'error_message',
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
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          파이프라인 실행 이력
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
            새로고침
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setIsTypeSelectOpen(true)}
          >
            새 파이프라인
          </Button>
        </Space>
      </div>

      <Card>
        <Table
          dataSource={data?.items ?? []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
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
          size="middle"
        />
      </Card>

      {/* 실행 상세 Drawer */}
      <ExecutionDetailDrawer
        execution={selectedExecution}
        onClose={() => setSelectedExecution(null)}
        onNavigateToDataset={(groupId, datasetId) => navigate(`/datasets/${groupId}/${datasetId}`)}
      />

      {/* ── 태스크 타입 선택 모달 ── */}
      <Modal
        title="데이터 변형 유형 선택"
        open={isTypeSelectOpen}
        onCancel={() => setIsTypeSelectOpen(false)}
        footer={null}
        width={640}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          변형할 데이터의 유형을 선택하세요. 유형에 따라 사용 가능한 Manipulator가 달라집니다.
        </Text>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {TASK_TYPE_OPTIONS.map((opt) => (
            <div
              key={opt.key}
              onClick={() => {
                if (opt.ready) {
                  setIsTypeSelectOpen(false)
                  navigate(`/pipelines/editor?taskType=${opt.key}`)
                } else {
                  Modal.info({
                    title: '준비 중',
                    content: `${opt.label} 유형의 데이터 변형은 아직 준비 중입니다.`,
                    okText: '확인',
                  })
                }
              }}
              style={{
                border: `1px solid ${opt.ready ? opt.color : '#d9d9d9'}`,
                borderRadius: 8,
                padding: '16px 20px',
                cursor: opt.ready ? 'pointer' : 'default',
                opacity: opt.ready ? 1 : 0.45,
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                gap: 14,
              }}
              onMouseEnter={(e) => {
                if (opt.ready) {
                  e.currentTarget.style.background = `${opt.color}08`
                  e.currentTarget.style.borderColor = opt.color
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = ''
                e.currentTarget.style.borderColor = opt.ready ? opt.color : '#d9d9d9'
              }}
            >
              <div style={{ color: opt.ready ? opt.color : '#bfbfbf' }}>
                {opt.icon}
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14, color: opt.ready ? '#000' : '#8c8c8c' }}>
                  {opt.label}
                  {!opt.ready && (
                    <Tag color="default" style={{ fontSize: 10, marginLeft: 6, padding: '0 4px' }}>
                      준비 중
                    </Tag>
                  )}
                </div>
                <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 2 }}>
                  {opt.description}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  )
}
