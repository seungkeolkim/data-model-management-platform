import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, Table, Tag, Typography, Alert } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { listRuns } from '@/api/automation'
import type {
  AutomationTriggerSource,
  PipelineRun,
  PipelineRunStatus,
} from '@/types/automation'

const { Text } = Typography

const TRIGGER_SOURCE_LABEL: Record<AutomationTriggerSource, string> = {
  polling: 'polling',
  triggering: 'triggering',
  manual_rerun: '수동 재실행',
}

const STATUS_COLOR: Record<PipelineRunStatus, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  DONE: 'success',
  FAILED: 'error',
  SKIPPED_NO_DELTA: 'default',
  SKIPPED_UPSTREAM_FAILED: 'default',
}

const STATUS_LABEL: Record<PipelineRunStatus, string> = {
  PENDING: 'Pending',
  RUNNING: 'Running',
  DONE: 'Done',
  FAILED: 'Failed',
  SKIPPED_NO_DELTA: 'Skipped (no-delta)',
  SKIPPED_UPSTREAM_FAILED: 'Skipped (upstream)',
}

/**
 * 파이프라인 상세 Automation 탭의 "최근 automation 실행 N 건 요약".
 *
 * v7.13 baseline 에서 자료구조가 PipelineVersion 단위로 격하됐으므로 이 컴포넌트도 versionId 키로
 * 동작한다. automation 경로 실행만 (trigger_kind !== manual_from_editor) 노출 — manual 실행은
 * 데이터 변형 탭의 실행 이력에서 확인.
 */
export default function RecentAutomationRuns({ versionId }: { versionId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['automation', 'recent-runs', versionId],
    queryFn: () => listRuns({ pipeline_version_id: versionId }),
  })

  // automation 경로만 필터. 최근순 정렬. 상위 5건만 요약.
  const recentRuns = useMemo(() => {
    const automationOnly = (data ?? []).filter(
      (run) => run.trigger_kind !== 'manual_from_editor',
    )
    return [...automationOnly]
      .sort((first, second) => {
        const firstTime = first.started_at ? Date.parse(first.started_at) : 0
        const secondTime = second.started_at ? Date.parse(second.started_at) : 0
        return secondTime - firstTime
      })
      .slice(0, 5)
  }, [data])

  const columns: ColumnsType<PipelineRun> = [
    {
      title: '시작 시각',
      key: 'started_at',
      render: (_, run) =>
        run.started_at ? (
          <Text style={{ fontSize: 12 }}>
            {new Date(run.started_at).toLocaleString('ko-KR')}
          </Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: 'Source',
      key: 'source',
      render: (_, run) =>
        run.automation_trigger_source ? (
          <Tag style={{ fontSize: 11 }}>
            {TRIGGER_SOURCE_LABEL[run.automation_trigger_source]}
          </Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '상태',
      key: 'status',
      render: (_, run) => <Tag color={STATUS_COLOR[run.status]}>{STATUS_LABEL[run.status]}</Tag>,
    },
    {
      title: '출력 버전',
      key: 'output_version',
      render: (_, run) =>
        run.output_dataset_version ? (
          <Tag color="blue">{run.output_dataset_version}</Tag>
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
      <Table<PipelineRun>
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
