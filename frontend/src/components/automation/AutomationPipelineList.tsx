import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Button,
  Card,
  Select,
  Space,
  Table,
  Typography,
  Alert,
  Tag,
  Tooltip,
} from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { listPipelines } from '@/api/automation'
import type {
  Pipeline,
  AutomationStatus,
  AutomationMode,
  PollInterval,
} from '@/types/automation'
import {
  StatusBadge,
  TaskTypeTag,
  AUTOMATION_STATUS_LABEL,
  AUTOMATION_ERROR_REASON_LABEL,
} from './StatusBadge'

const { Text } = Typography

const POLL_INTERVAL_OPTIONS: PollInterval[] = ['10m', '1h', '6h', '24h']

/**
 * 파이프라인명 / 모드 라벨 — 테이블 표시용.
 */
const MODE_LABEL: Record<AutomationMode, string> = {
  polling: 'Polling',
  triggering: 'Triggering',
}

interface AutomationPipelineListProps {
  /** 목록 ↔ 우측 DAG 연동용 선택 파이프라인 ID. null 이면 선택 없음. */
  selectedPipelineId: string | null
  onSelectPipeline: (pipelineId: string | null) => void
}

/**
 * Automation 관리 페이지의 좌측 목록.
 *
 * 필터는 상태 · 모드 · 주기 3종 (023 §6-2). 모두 복수 선택.
 * 정렬은 antd Table 기본 sorter (파이프라인명 / 최근 실행 / 주기).
 * 수동 재실행 버튼은 목록 행에 배치하지 않는다 (§G-29 — 상세 탭 only).
 *
 * 행 클릭 = **선택** (우측 DAG 하이라이트). 상세 이동은 행 끝의 "상세 →" 버튼으로 분리 —
 * master-detail UX 로 사용자가 목록에서 여러 파이프라인을 돌려보며 DAG 구성을 비교할 수 있게 한다.
 */
export default function AutomationPipelineList({
  selectedPipelineId,
  onSelectPipeline,
}: AutomationPipelineListProps) {
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['automation', 'pipelines'],
    queryFn: listPipelines,
  })

  const [statusFilter, setStatusFilter] = useState<AutomationStatus[]>([])
  const [modeFilter, setModeFilter] = useState<AutomationMode[]>([])
  const [intervalFilter, setIntervalFilter] = useState<PollInterval[]>([])

  const filteredPipelines = useMemo(() => {
    if (!data) return []
    return data.filter((pipeline) => {
      if (statusFilter.length && !statusFilter.includes(pipeline.automation_status)) return false
      if (
        modeFilter.length &&
        (pipeline.automation_mode === null || !modeFilter.includes(pipeline.automation_mode))
      ) {
        return false
      }
      if (
        intervalFilter.length &&
        (pipeline.automation_poll_interval === null ||
          !intervalFilter.includes(pipeline.automation_poll_interval))
      ) {
        return false
      }
      return true
    })
  }, [data, statusFilter, modeFilter, intervalFilter])

  const resetFilters = () => {
    setStatusFilter([])
    setModeFilter([])
    setIntervalFilter([])
  }

  const columns: ColumnsType<Pipeline> = [
    {
      title: '파이프라인명',
      dataIndex: 'name',
      key: 'name',
      sorter: (firstPipeline, secondPipeline) =>
        firstPipeline.name.localeCompare(secondPipeline.name),
      render: (_, pipeline) => (
        <div>
          <Space size={6} align="center">
            <TaskTypeTag taskType={pipeline.task_type} />
            <Text strong>{pipeline.name}</Text>
          </Space>
          {pipeline.description && (
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 2 }}>
              {pipeline.description}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '상태',
      key: 'automation_status',
      render: (_, pipeline) => (
        <Space direction="vertical" size={2}>
          <StatusBadge status={pipeline.automation_status} />
          {pipeline.automation_status === 'error' && pipeline.automation_error_reason && (
            <Text style={{ fontSize: 11, color: '#cf1322' }}>
              {AUTOMATION_ERROR_REASON_LABEL[pipeline.automation_error_reason]}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '모드',
      key: 'automation_mode',
      render: (_, pipeline) =>
        pipeline.automation_mode ? <Tag>{MODE_LABEL[pipeline.automation_mode]}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '주기',
      key: 'automation_poll_interval',
      sorter: (firstPipeline, secondPipeline) =>
        (firstPipeline.automation_poll_interval ?? '').localeCompare(
          secondPipeline.automation_poll_interval ?? '',
        ),
      render: (_, pipeline) =>
        pipeline.automation_poll_interval ? (
          <Tag color="geekblue">{pipeline.automation_poll_interval}</Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '마지막 실행',
      key: 'last_execution_at',
      sorter: (firstPipeline, secondPipeline) => {
        const firstTime = firstPipeline.last_execution_at
          ? Date.parse(firstPipeline.last_execution_at)
          : 0
        const secondTime = secondPipeline.last_execution_at
          ? Date.parse(secondPipeline.last_execution_at)
          : 0
        return firstTime - secondTime
      },
      render: (_, pipeline) =>
        pipeline.last_execution_at ? (
          <Tooltip title={pipeline.last_execution_at}>
            <Text>{new Date(pipeline.last_execution_at).toLocaleString('ko-KR')}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">이력 없음</Text>
        ),
    },
    {
      title: '다음 예정',
      key: 'next_scheduled_at',
      render: (_, pipeline) =>
        pipeline.next_scheduled_at ? (
          <Text type="secondary">
            {new Date(pipeline.next_scheduled_at).toLocaleString('ko-KR')}
          </Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '',
      key: 'detail_action',
      width: 80,
      render: (_, pipeline) => (
        <Button
          size="small"
          type="link"
          icon={<ArrowRightOutlined />}
          onClick={(event) => {
            // 행 클릭(선택) 과 충돌하지 않도록 stopPropagation.
            event.stopPropagation()
            navigate(`/automation/pipelines/${pipeline.id}`)
          }}
        >
          상세
        </Button>
      ),
    },
  ]

  return (
    <Card
      title="파이프라인 목록"
      size="small"
      extra={
        <Space size={6}>
          <Select<AutomationStatus[]>
            mode="multiple"
            allowClear
            placeholder="상태"
            style={{ minWidth: 140 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={(['stopped', 'active', 'error'] as AutomationStatus[]).map((status) => ({
              value: status,
              label: AUTOMATION_STATUS_LABEL[status],
            }))}
          />
          <Select<AutomationMode[]>
            mode="multiple"
            allowClear
            placeholder="모드"
            style={{ minWidth: 140 }}
            value={modeFilter}
            onChange={setModeFilter}
            options={(['polling', 'triggering'] as AutomationMode[]).map((mode) => ({
              value: mode,
              label: MODE_LABEL[mode],
            }))}
          />
          <Select<PollInterval[]>
            mode="multiple"
            allowClear
            placeholder="주기"
            style={{ minWidth: 120 }}
            value={intervalFilter}
            onChange={setIntervalFilter}
            options={POLL_INTERVAL_OPTIONS.map((interval) => ({
              value: interval,
              label: interval,
            }))}
          />
          <Button size="small" onClick={resetFilters}>
            필터 초기화
          </Button>
          <Button size="small" onClick={() => refetch()}>
            새로고침
          </Button>
        </Space>
      }
    >
      {error && (
        <Alert
          type="error"
          message="목록 로드 실패"
          description={(error as Error).message}
          style={{ marginBottom: 12 }}
        />
      )}
      <Table<Pipeline>
        size="small"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={filteredPipelines}
        pagination={{ pageSize: 10, size: 'small' }}
        onRow={(pipeline) => {
          const isSelected = pipeline.id === selectedPipelineId
          return {
            style: {
              cursor: 'pointer',
              // 선택된 행은 배경 강조. antd 기본 selected 스타일 흉내 — 전역 CSS 건드리지 않음.
              background: isSelected ? '#e6f4ff' : undefined,
            },
            // 행 클릭 = 선택 토글. 같은 행 재클릭 시 선택 해제.
            onClick: () =>
              onSelectPipeline(pipeline.id === selectedPipelineId ? null : pipeline.id),
          }
        }}
      />
    </Card>
  )
}
