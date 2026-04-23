import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Button,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { listExecutions, listExecutionBatches } from '@/api/automation'
import type {
  PipelineExecutionSummary,
  TriggerKind,
  AutomationTriggerSource,
  ExecutionBatch,
} from '@/types/automation'

const { Text } = Typography

const TRIGGER_KIND_LABEL: Record<TriggerKind, string> = {
  manual_from_editor: '수동 (데이터 변형 탭)',
  automation_auto: '자동',
  automation_manual_rerun: '자동 · 수동 재실행',
}
const TRIGGER_SOURCE_LABEL: Record<AutomationTriggerSource, string> = {
  polling: 'polling',
  triggering: 'triggering',
  manual_rerun: 'manual_rerun',
}
const STATUS_COLOR: Record<PipelineExecutionSummary['status'], string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  DONE: 'success',
  FAILED: 'error',
  SKIPPED_NO_DELTA: 'gold',
  SKIPPED_UPSTREAM_FAILED: 'volcano',
}
const STATUS_LABEL: Record<PipelineExecutionSummary['status'], string> = {
  PENDING: 'Pending',
  RUNNING: 'Running',
  DONE: 'Done',
  FAILED: 'Failed',
  SKIPPED_NO_DELTA: 'Skipped (no-delta)',
  SKIPPED_UPSTREAM_FAILED: 'Skipped (upstream)',
}

/**
 * 실행 이력 테이블 — batch 그룹핑 + automation 필터 (023 §6-3 / §F-23~27).
 *
 * 행 구조:
 *   - Batch 부모 행: automation_batch_id 로 묶인 체인 1건. 펼치면 children 에 토폴로지 순서로 실행 표시.
 *   - 단발 실행 행: batch 에 속하지 않는 execution 한 건.
 *
 * 필터는 execution 단위로 매칭하고, batch 의 children 이 필터로 다 걸러지면 batch 도 숨긴다.
 */
export default function ExecutionHistoryTable() {
  const { data: executions, isLoading: execLoading, error: execError, refetch: refetchExec } =
    useQuery({
      queryKey: ['automation', 'executions'],
      queryFn: () => listExecutions(),
    })
  const { data: batches, isLoading: batchLoading, error: batchError, refetch: refetchBatches } =
    useQuery({
      queryKey: ['automation', 'execution-batches'],
      queryFn: listExecutionBatches,
    })

  const [kindFilter, setKindFilter] = useState<TriggerKind[]>([])
  const [sourceFilter, setSourceFilter] = useState<AutomationTriggerSource[]>([])
  const [statusFilter, setStatusFilter] = useState<PipelineExecutionSummary['status'][]>([])

  const rows = useMemo(
    () => buildRows(executions ?? [], batches ?? [], { kindFilter, sourceFilter, statusFilter }),
    [executions, batches, kindFilter, sourceFilter, statusFilter],
  )

  const columns: ColumnsType<HistoryRow> = [
    {
      title: '파이프라인',
      key: 'pipeline_name',
      render: (_, row) =>
        row.kind === 'batch' ? (
          <Space direction="vertical" size={0}>
            <Tag color="purple">Batch</Tag>
            <Text style={{ fontSize: 11, color: '#8c8c8c' }}>{row.batch.batch_id}</Text>
          </Space>
        ) : (
          <Text strong>{row.execution.pipeline_name}</Text>
        ),
    },
    {
      title: 'Trigger',
      key: 'trigger_kind',
      render: (_, row) =>
        row.kind === 'batch' ? (
          <Tag>automation batch</Tag>
        ) : (
          <Tag style={{ fontSize: 11 }}>{TRIGGER_KIND_LABEL[row.execution.trigger_kind]}</Tag>
        ),
    },
    {
      title: 'Source',
      key: 'source',
      render: (_, row) => {
        if (row.kind === 'batch') {
          return <Tag color="geekblue">{TRIGGER_SOURCE_LABEL[row.batch.trigger_source]}</Tag>
        }
        return row.execution.automation_trigger_source ? (
          <Tag color="geekblue" style={{ fontSize: 11 }}>
            {TRIGGER_SOURCE_LABEL[row.execution.automation_trigger_source]}
          </Tag>
        ) : (
          <Text type="secondary">—</Text>
        )
      },
    },
    {
      title: '트리거된 입력 버전',
      key: 'triggered_input_versions',
      render: (_, row) => {
        if (row.kind === 'batch') {
          return <Text type="secondary">(batch)</Text>
        }
        const versions = row.execution.triggered_input_versions
        const entries = Object.entries(versions)
        if (entries.length === 0) return <Text type="secondary">—</Text>
        return (
          <Space size={4} wrap>
            {entries.map(([groupName, version]) => (
              <Tooltip key={groupName} title={`${groupName} = ${version}`}>
                <Tag color="blue" style={{ fontSize: 11 }}>
                  {groupName}@{version}
                </Tag>
              </Tooltip>
            ))}
          </Space>
        )
      },
    },
    {
      title: '상태',
      key: 'status',
      render: (_, row) => {
        if (row.kind === 'batch') {
          return <Tag>{row.batch.executions.length}건</Tag>
        }
        return (
          <Tag color={STATUS_COLOR[row.execution.status]}>
            {STATUS_LABEL[row.execution.status]}
          </Tag>
        )
      },
    },
    {
      title: '시작 시각',
      key: 'started_at',
      render: (_, row) => {
        const started = row.kind === 'batch' ? row.batch.created_at : row.execution.started_at
        return started ? (
          <Text style={{ fontSize: 12 }}>{new Date(started).toLocaleString('ko-KR')}</Text>
        ) : (
          <Text type="secondary">—</Text>
        )
      },
      sorter: (first, second) => {
        const firstTime = getSortTime(first)
        const secondTime = getSortTime(second)
        return firstTime - secondTime
      },
      defaultSortOrder: 'descend',
    },
    {
      title: '소요',
      key: 'duration',
      render: (_, row) => {
        if (row.kind === 'batch') return <Text type="secondary">—</Text>
        const duration = row.execution.duration_seconds
        if (duration === null) return <Text type="secondary">—</Text>
        return <Text style={{ fontSize: 12 }}>{formatDurationSeconds(duration)}</Text>
      },
    },
    {
      title: '결과 버전',
      key: 'output_version',
      render: (_, row) =>
        row.kind === 'batch' ? (
          <Text type="secondary">—</Text>
        ) : row.execution.output_dataset_version ? (
          <Tag color="blue">{row.execution.output_dataset_version}</Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
  ]

  return (
    <Card
      title="실행 이력"
      size="small"
      extra={
        <Space size={6}>
          <Select<TriggerKind[]>
            mode="multiple"
            allowClear
            placeholder="Trigger 종류"
            style={{ minWidth: 200 }}
            value={kindFilter}
            onChange={setKindFilter}
            options={(
              ['manual_from_editor', 'automation_auto', 'automation_manual_rerun'] as TriggerKind[]
            ).map((kind) => ({ value: kind, label: TRIGGER_KIND_LABEL[kind] }))}
          />
          <Select<AutomationTriggerSource[]>
            mode="multiple"
            allowClear
            placeholder="Source"
            style={{ minWidth: 160 }}
            value={sourceFilter}
            onChange={setSourceFilter}
            options={(
              ['polling', 'triggering', 'manual_rerun'] as AutomationTriggerSource[]
            ).map((source) => ({ value: source, label: TRIGGER_SOURCE_LABEL[source] }))}
          />
          <Select<PipelineExecutionSummary['status'][]>
            mode="multiple"
            allowClear
            placeholder="상태"
            style={{ minWidth: 160 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={(
              [
                'PENDING',
                'RUNNING',
                'DONE',
                'FAILED',
                'SKIPPED_NO_DELTA',
                'SKIPPED_UPSTREAM_FAILED',
              ] as PipelineExecutionSummary['status'][]
            ).map((status) => ({ value: status, label: STATUS_LABEL[status] }))}
          />
          <Button
            size="small"
            onClick={() => {
              setKindFilter([])
              setSourceFilter([])
              setStatusFilter([])
            }}
          >
            필터 초기화
          </Button>
          <Button
            size="small"
            onClick={() => {
              refetchExec()
              refetchBatches()
            }}
          >
            새로고침
          </Button>
        </Space>
      }
    >
      {(execError || batchError) && (
        <Alert
          type="error"
          message="이력 로드 실패"
          description={((execError ?? batchError) as Error).message}
          style={{ marginBottom: 12 }}
        />
      )}
      <Table<HistoryRow>
        size="small"
        rowKey="key"
        loading={execLoading || batchLoading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20, size: 'small' }}
        expandable={{
          rowExpandable: (row) => row.kind === 'batch' && row.children !== undefined,
          defaultExpandAllRows: false,
        }}
      />
    </Card>
  )
}

// =============================================================================
// Row 모델 & 빌드 로직
// =============================================================================

type HistoryRow =
  | {
      key: string
      kind: 'batch'
      batch: ExecutionBatch
      children?: HistoryRow[]
    }
  | {
      key: string
      kind: 'execution'
      execution: PipelineExecutionSummary
      children?: undefined
    }

interface FilterState {
  kindFilter: TriggerKind[]
  sourceFilter: AutomationTriggerSource[]
  statusFilter: PipelineExecutionSummary['status'][]
}

function matchesFilters(execution: PipelineExecutionSummary, filters: FilterState): boolean {
  if (filters.kindFilter.length && !filters.kindFilter.includes(execution.trigger_kind)) {
    return false
  }
  if (
    filters.sourceFilter.length &&
    (execution.automation_trigger_source === null ||
      !filters.sourceFilter.includes(execution.automation_trigger_source))
  ) {
    return false
  }
  if (filters.statusFilter.length && !filters.statusFilter.includes(execution.status)) {
    return false
  }
  return true
}

function buildRows(
  allExecutions: PipelineExecutionSummary[],
  batches: ExecutionBatch[],
  filters: FilterState,
): HistoryRow[] {
  // batch 의 child 는 필터 통과한 것만 유지. 전부 걸러지면 batch 자체를 숨김.
  const filteredBatches = batches
    .map((batch) => ({
      ...batch,
      executions: batch.executions.filter((execution) => matchesFilters(execution, filters)),
    }))
    .filter((batch) => batch.executions.length > 0)

  // batch 에 포함된 exec id 는 단발 목록에서 제외.
  const batchExecIds = new Set<string>()
  for (const batch of batches) {
    for (const execution of batch.executions) batchExecIds.add(execution.id)
  }

  const singleExecutions = allExecutions
    .filter((execution) => !batchExecIds.has(execution.id))
    .filter((execution) => matchesFilters(execution, filters))

  const batchRows: HistoryRow[] = filteredBatches.map((batch) => ({
    key: `batch-${batch.batch_id}`,
    kind: 'batch',
    batch,
    children: batch.executions.map((execution) => ({
      key: `exec-${execution.id}`,
      kind: 'execution',
      execution,
    })),
  }))
  const singleRows: HistoryRow[] = singleExecutions.map((execution) => ({
    key: `exec-${execution.id}`,
    kind: 'execution',
    execution,
  }))

  return [...batchRows, ...singleRows]
}

function getSortTime(row: HistoryRow): number {
  if (row.kind === 'batch') {
    return Date.parse(row.batch.created_at)
  }
  return row.execution.started_at ? Date.parse(row.execution.started_at) : 0
}

function formatDurationSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  const remainSeconds = seconds % 60
  if (minutes < 60) return `${minutes}분 ${remainSeconds}초`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}시간 ${remainMinutes}분`
}
