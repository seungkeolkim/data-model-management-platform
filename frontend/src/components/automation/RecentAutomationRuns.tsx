import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Typography, Alert } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { listExecutions } from '@/api/automation'
import type { PipelineExecutionSummary, AutomationTriggerSource } from '@/types/automation'

const { Text } = Typography

const TRIGGER_SOURCE_LABEL: Record<AutomationTriggerSource, string> = {
  polling: 'polling',
  triggering: 'triggering',
  manual_rerun: '수동 재실행',
}

const STATUS_COLOR: Record<PipelineExecutionSummary['status'], string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  DONE: 'success',
  FAILED: 'error',
  SKIPPED_NO_DELTA: 'default',
  SKIPPED_UPSTREAM_FAILED: 'default',
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
 * 파이프라인 상세 Automation 탭의 "최근 automation 실행 N 건 요약" (023 §6-4).
 *
 * 현 탭에서는 해당 파이프라인의 실행만 필터하고, automation 경로 (trigger_kind !== manual_from_editor)
 * 만 보여준다. manual_from_editor 는 데이터 변형 탭 이력에서 확인.
 */
export default function RecentAutomationRuns({ pipelineId }: { pipelineId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['automation', 'recent-runs', pipelineId],
    queryFn: () => listExecutions({ pipeline_id: pipelineId }),
  })

  // automation 경로만 필터. 최근순 정렬. 상위 5건만 요약.
  const recentRuns = useMemo(() => {
    const automationOnly = (data ?? []).filter(
      (execution) => execution.trigger_kind !== 'manual_from_editor',
    )
    return [...automationOnly]
      .sort((first, second) => {
        const firstTime = first.started_at ? Date.parse(first.started_at) : 0
        const secondTime = second.started_at ? Date.parse(second.started_at) : 0
        return secondTime - firstTime
      })
      .slice(0, 5)
  }, [data])

  const columns: ColumnsType<PipelineExecutionSummary> = [
    {
      title: '시작 시각',
      key: 'started_at',
      render: (_, execution) =>
        execution.started_at ? (
          <Text style={{ fontSize: 12 }}>
            {new Date(execution.started_at).toLocaleString('ko-KR')}
          </Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: 'Source',
      key: 'source',
      render: (_, execution) =>
        execution.automation_trigger_source ? (
          <Tag style={{ fontSize: 11 }}>
            {TRIGGER_SOURCE_LABEL[execution.automation_trigger_source]}
          </Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '상태',
      key: 'status',
      render: (_, execution) => (
        <Tag color={STATUS_COLOR[execution.status]}>{STATUS_LABEL[execution.status]}</Tag>
      ),
    },
    {
      title: '출력 버전',
      key: 'output_version',
      render: (_, execution) =>
        execution.output_dataset_version ? (
          <Tag color="blue">{execution.output_dataset_version}</Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
  ]

  return (
    <Card title="최근 자동화 실행" size="small">
      {error && (
        <Alert type="error" message="실행 이력 로드 실패" description={(error as Error).message} />
      )}
      <Table<PipelineExecutionSummary>
        size="small"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={recentRuns}
        pagination={false}
        locale={{ emptyText: '자동화 실행 이력 없음' }}
      />
    </Card>
  )
}
