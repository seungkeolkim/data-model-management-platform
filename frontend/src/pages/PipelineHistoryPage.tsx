/**
 * PipelineHistoryPage — 파이프라인 실행 이력 목록
 *
 * AppLayout 내부에 렌더링되는 사이드바가 있는 페이지.
 * 실행 이력을 테이블로 표시하고, "새 파이프라인" 버튼으로 에디터로 이동한다.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Table, Button, Tag, Typography, Space, Card, Modal } from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  AimOutlined,
  AppstoreOutlined,
  TagsOutlined,
  SearchOutlined,
  PictureOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { pipelinesApi } from '@/api/pipeline'
import type { PipelineExecutionResponse } from '@/types/pipeline'
import type { TaskType } from '@/types/dataset'
import { formatDate } from '@/utils/format'

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
    key: 'ATTR_CLASSIFICATION',
    label: 'Attribute Classification',
    description: '속성 분류 데이터 변형',
    icon: <TagsOutlined style={{ fontSize: 28 }} />,
    color: '#fa8c16',
    ready: false,
  },
  {
    key: 'ZERO_SHOT',
    label: 'Zero-Shot',
    description: '제로샷 학습용 데이터 변형',
    icon: <SearchOutlined style={{ fontSize: 28 }} />,
    color: '#722ed1',
    ready: false,
  },
  {
    key: 'CLASSIFICATION',
    label: 'Classification',
    description: '이미지 분류 데이터 변형',
    icon: <PictureOutlined style={{ fontSize: 28 }} />,
    color: '#13c2c2',
    ready: false,
  },
]

export default function PipelineHistoryPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [isTypeSelectOpen, setIsTypeSelectOpen] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['pipeline-executions', page, pageSize],
    queryFn: () =>
      pipelinesApi.list({ page, page_size: pageSize }).then((r) => r.data),
  })

  const columns: ColumnsType<PipelineExecutionResponse> = [
    {
      title: '실행 ID',
      dataIndex: 'id',
      width: 120,
      render: (id: string) => (
        <Typography.Text code style={{ fontSize: 11 }}>
          {id.slice(0, 8)}...
        </Typography.Text>
      ),
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
      title: '현재 단계',
      dataIndex: 'current_stage',
      width: 160,
      render: (stage: string | null) => stage ?? '-',
    },
    {
      title: '진행률',
      width: 120,
      render: (_: unknown, record: PipelineExecutionResponse) => {
        if (!record.total_count) return '-'
        return `${record.processed_count} / ${record.total_count}`
      },
    },
    {
      title: '시작',
      dataIndex: 'started_at',
      width: 160,
      render: (val: string | null) => (val ? formatDate(val) : '-'),
    },
    {
      title: '완료',
      dataIndex: 'finished_at',
      width: 160,
      render: (val: string | null) => (val ? formatDate(val) : '-'),
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

      {/* 태스크 타입 선택 모달 */}
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
