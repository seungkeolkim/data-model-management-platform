import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueries, useQuery } from '@tanstack/react-query'
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
import { listConcepts, listVersions } from '@/api/automation'
import type {
  AutomationMode,
  AutomationStatus,
  PipelineConcept,
  PipelineVersion,
  PollInterval,
} from '@/types/automation'
import {
  AUTOMATION_ERROR_REASON_LABEL,
  AUTOMATION_STATUS_LABEL,
  StatusBadge,
  TaskTypeTag,
  VersionTag,
} from './StatusBadge'

const { Text } = Typography

const POLL_INTERVAL_OPTIONS: PollInterval[] = ['10m', '1h', '6h', '24h']

const MODE_LABEL: Record<AutomationMode, string> = {
  polling: 'Polling',
  triggering: 'Triggering',
}

interface AutomationPipelineListProps {
  /**
   * 우측 DAG 하이라이트용 PipelineVersion ID. expand 안의 version 행 클릭 시 갱신.
   * concept 행 자체는 expand 토글만 하고 selection 에 영향 주지 않는다 — DAG 노드가 version 단위라
   * concept 단위 선택은 의미가 모호하기 때문.
   */
  selectedVersionId: string | null
  onSelectVersion: (versionId: string | null) => void
}

/**
 * Automation 관리 페이지의 좌측 목록 — v7.13 baseline (concept + version 2계층).
 *
 * 행 단위 = Pipeline (concept). 클릭 = 인라인 expand 토글 (한 번에 한 concept).
 * Expand 안에서 versions 세로 목록을 보여주고 각 version 행에 automation 상세 + "상세 →" 버튼 노출.
 * Version 행 클릭 = 우측 DAG 의 해당 노드 강조.
 *
 * 필터는 status / mode / poll_interval 3종 (각 복수 선택). 매칭 기준: concept 산하 어느 version 이라도
 * 해당 조건을 만족하면 concept 행을 표시. 모드 / 주기 필터는 active automation 이 등록된 version 만
 * 후보로 본다 (등록 없는 version 은 모드 자체가 의미 없음).
 *
 * 수동 재실행 버튼은 목록 행에 두지 않는다 (027 §6 원칙) — 사용자가 상세 페이지로 들어가 내용을 확인한
 * 뒤 실행하도록.
 */
export default function AutomationPipelineList({
  selectedVersionId,
  onSelectVersion,
}: AutomationPipelineListProps) {
  const navigate = useNavigate()

  // concept 목록.
  const conceptsQuery = useQuery({
    queryKey: ['automation', 'concepts'],
    queryFn: () => listConcepts({ include_inactive: false }),
  })

  // 모든 concept 의 versions 를 일괄 fetch — 목업에서는 데이터 양이 작아 한꺼번에 받는 게 단순.
  // 실 API 전환 시 필요하면 expand 시점 lazy load 로 변경.
  const concepts = conceptsQuery.data ?? []
  const versionsQueries = useQueries({
    queries: concepts.map((concept) => ({
      queryKey: ['automation', 'versions', concept.id],
      queryFn: () => listVersions(concept.id, { include_inactive: false }),
      enabled: concepts.length > 0,
    })),
  })
  const versionsByConceptId = useMemo(() => {
    const result: Record<string, PipelineVersion[]> = {}
    versionsQueries.forEach((query, index) => {
      if (query.data) {
        result[concepts[index].id] = query.data
      }
    })
    return result
  }, [concepts, versionsQueries])

  // 필터 state.
  const [statusFilter, setStatusFilter] = useState<AutomationStatus[]>([])
  const [modeFilter, setModeFilter] = useState<AutomationMode[]>([])
  const [intervalFilter, setIntervalFilter] = useState<PollInterval[]>([])

  /**
   * concept 가 필터에 매칭하는지 판정. expand 자식 version 들 중 하나라도 모든 필터를 만족하면 true.
   * automation 미등록 version 은 mode / interval 비교에서 건너뛰지만, status 필터의 'stopped' 는
   * 미등록 version 도 stopped 로 간주해 매칭 (의미상 자연스러움).
   */
  const filteredConcepts = useMemo(() => {
    if (!concepts.length) return [] as PipelineConcept[]
    const filtersActive =
      statusFilter.length > 0 || modeFilter.length > 0 || intervalFilter.length > 0
    if (!filtersActive) return concepts
    return concepts.filter((concept) => {
      const versions = versionsByConceptId[concept.id] ?? []
      return versions.some((version) => {
        const automation = version.automation
        const status: AutomationStatus = automation?.status ?? 'stopped'
        if (statusFilter.length && !statusFilter.includes(status)) return false
        if (modeFilter.length) {
          if (!automation?.mode) return false
          if (!modeFilter.includes(automation.mode)) return false
        }
        if (intervalFilter.length) {
          if (!automation?.poll_interval) return false
          if (!intervalFilter.includes(automation.poll_interval)) return false
        }
        return true
      })
    })
  }, [concepts, versionsByConceptId, statusFilter, modeFilter, intervalFilter])

  const resetFilters = () => {
    setStatusFilter([])
    setModeFilter([])
    setIntervalFilter([])
  }

  // 한 번에 한 concept 만 펼쳐지도록 expandedRowKeys 를 controlled 로.
  const [expandedConceptIds, setExpandedConceptIds] = useState<string[]>([])

  const conceptColumns: ColumnsType<PipelineConcept> = [
    {
      title: 'Pipeline (concept)',
      dataIndex: 'name',
      key: 'name',
      sorter: (a, b) => a.name.localeCompare(b.name),
      render: (_, concept) => (
        <div>
          <Space size={6} align="center">
            <TaskTypeTag taskType={concept.task_type} />
            <Text strong>{concept.name}</Text>
            {concept.family_name && concept.family_color && (
              <Tag color={concept.family_color} style={{ fontSize: 10 }}>
                {concept.family_name}
              </Tag>
            )}
          </Space>
          {concept.description && (
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 2 }}>
              {concept.description}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '출력',
      key: 'output',
      render: (_, concept) => (
        <Space size={4}>
          <Text style={{ fontSize: 12 }}>{concept.output.group_name}</Text>
          <Tag style={{ fontSize: 10 }}>{concept.output.split}</Tag>
        </Space>
      ),
    },
    {
      title: '버전 / 최신 활성',
      key: 'versions_summary',
      render: (_, concept) => (
        <Space size={4}>
          {concept.latest_active_version ? (
            <VersionTag version={concept.latest_active_version} />
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              활성 없음
            </Text>
          )}
          {concept.version_count > 1 && (
            <Tag color="default" style={{ fontSize: 10 }}>
              {concept.version_count} versions
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: 'Automation 요약',
      key: 'automation_summary',
      render: (_, concept) => {
        const versions = versionsByConceptId[concept.id] ?? []
        const activeAutomations = versions
          .map((version) => version.automation)
          .filter((automation): automation is NonNullable<typeof automation> => Boolean(automation))
        if (activeAutomations.length === 0) {
          return (
            <Text type="secondary" style={{ fontSize: 12 }}>
              등록된 automation 없음
            </Text>
          )
        }
        // status 분포 요약 — Active 1 / Error 1 형식.
        const statusCount: Record<AutomationStatus, number> = {
          stopped: 0,
          active: 0,
          error: 0,
        }
        for (const automation of activeAutomations) {
          statusCount[automation.status] += 1
        }
        return (
          <Space size={4}>
            {(['active', 'error', 'stopped'] as AutomationStatus[])
              .filter((status) => statusCount[status] > 0)
              .map((status) => (
                <Tooltip
                  key={status}
                  title={`${activeAutomations.length} 개 automation 중 ${statusCount[status]} 개가 ${AUTOMATION_STATUS_LABEL[status]}`}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <StatusBadge status={status} />
                    <Text style={{ fontSize: 11 }}>{statusCount[status]}</Text>
                  </span>
                </Tooltip>
              ))}
          </Space>
        )
      },
    },
  ]

  return (
    <>
      {/*
        Expand 된 concept 행 (그 안에 versions Table 이 들어있는 wide cell) 의 좌측에 3px 파란 border.
        PipelineListPage 의 동형 패턴 (027 §14-2 인라인 expand UX) — "어디까지가 펼친 것인지" 시각 구분.
        클래스명은 PipelineListPage 와 충돌하지 않도록 automation- prefix.
      */}
      <style>{`
        .automation-concept-expanded-row > .ant-table-cell {
          border-left: 3px solid #1677ff !important;
        }
      `}</style>
      <Card
        title="Automation 목록 (Pipeline 단위)"
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
          <Button size="small" onClick={() => conceptsQuery.refetch()}>
            새로고침
          </Button>
        </Space>
      }
    >
      {conceptsQuery.error && (
        <Alert
          type="error"
          message="목록 로드 실패"
          description={(conceptsQuery.error as Error).message}
          style={{ marginBottom: 12 }}
        />
      )}
      <Table<PipelineConcept>
        size="small"
        rowKey="id"
        loading={conceptsQuery.isLoading}
        columns={conceptColumns}
        dataSource={filteredConcepts}
        pagination={{ pageSize: 10, size: 'small' }}
        expandable={{
          expandedRowKeys: expandedConceptIds,
          // 좌측 3px 파란 border — 위 <style> 블록과 짝.
          expandedRowClassName: () => 'automation-concept-expanded-row',
          onExpand: (expanded, concept) => {
            // 한 번에 한 concept 만 펼쳐지도록 — 단순 controlled.
            setExpandedConceptIds(expanded ? [concept.id] : [])
          },
          expandedRowRender: (concept) => (
            <ExpandedVersionsTable
              concept={concept}
              versions={versionsByConceptId[concept.id] ?? []}
              loading={
                versionsQueries[concepts.findIndex((c) => c.id === concept.id)]?.isLoading ?? false
              }
              selectedVersionId={selectedVersionId}
              onSelectVersion={onSelectVersion}
              onNavigateToDetail={(versionId) =>
                navigate(`/automation/versions/${versionId}`)
              }
            />
          ),
        }}
        onRow={(concept) => ({
          style: { cursor: 'pointer' },
          // 행 클릭 = expand 토글. version 선택은 expand 안에서 따로.
          onClick: () =>
            setExpandedConceptIds((prev) =>
              prev[0] === concept.id ? [] : [concept.id],
            ),
        })}
      />
    </Card>
    </>
  )
}

// =============================================================================
// Expand 안의 versions 세로 목록
// =============================================================================

interface ExpandedVersionsTableProps {
  concept: PipelineConcept
  versions: PipelineVersion[]
  loading: boolean
  selectedVersionId: string | null
  onSelectVersion: (versionId: string | null) => void
  onNavigateToDetail: (versionId: string) => void
}

function ExpandedVersionsTable({
  concept,
  versions,
  loading,
  selectedVersionId,
  onSelectVersion,
  onNavigateToDetail,
}: ExpandedVersionsTableProps) {
  const versionColumns: ColumnsType<PipelineVersion> = [
    {
      title: '버전',
      key: 'version',
      width: 110,
      render: (_, version) => <VersionTag version={version.version} />,
    },
    {
      title: '버전 메모',
      dataIndex: 'description',
      key: 'description',
      render: (description: string | null) =>
        description ? (
          <Text style={{ fontSize: 12 }}>{description}</Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            —
          </Text>
        ),
    },
    {
      title: 'Automation',
      key: 'automation',
      render: (_, version) => {
        const automation = version.automation
        if (!automation) {
          return (
            <Text type="secondary" style={{ fontSize: 12 }}>
              미등록
            </Text>
          )
        }
        return (
          <Space size={4} direction="vertical" style={{ rowGap: 2 }}>
            <Space size={4}>
              <StatusBadge status={automation.status} />
              {automation.mode && (
                <Tag style={{ fontSize: 10 }}>{MODE_LABEL[automation.mode]}</Tag>
              )}
              {automation.poll_interval && (
                <Tag color="geekblue" style={{ fontSize: 10 }}>
                  {automation.poll_interval}
                </Tag>
              )}
            </Space>
            {automation.status === 'error' && automation.error_reason && (
              <Text style={{ fontSize: 11, color: '#cf1322' }}>
                {AUTOMATION_ERROR_REASON_LABEL[automation.error_reason]}
              </Text>
            )}
          </Space>
        )
      },
    },
    {
      title: '실행 / 마지막',
      key: 'last_run_at',
      render: (_, version) =>
        version.last_run_at ? (
          <Space size={2} direction="vertical">
            <Text style={{ fontSize: 12 }}>
              {new Date(version.last_run_at).toLocaleString('ko-KR')}
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              총 {version.run_count} 회
            </Text>
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            이력 없음
          </Text>
        ),
    },
    {
      title: '',
      key: 'actions',
      width: 90,
      render: (_, version) => (
        <Button
          size="small"
          type="link"
          icon={<ArrowRightOutlined />}
          onClick={(event) => {
            event.stopPropagation()
            onNavigateToDetail(version.id)
          }}
        >
          상세
        </Button>
      ),
    },
  ]

  return (
    <Table<PipelineVersion>
      size="small"
      rowKey="id"
      loading={loading}
      columns={versionColumns}
      dataSource={versions}
      pagination={false}
      // 빈 상태 — concept 가 version 0 인 경우 (실 운영에서는 없음, 방어적).
      locale={{
        emptyText: `${concept.name} 에 등록된 version 이 없습니다`,
      }}
      onRow={(version) => {
        const isSelected = version.id === selectedVersionId
        return {
          style: {
            cursor: 'pointer',
            background: isSelected ? '#e6f4ff' : undefined,
          },
          onClick: () =>
            onSelectVersion(version.id === selectedVersionId ? null : version.id),
        }
      }}
    />
  )
}
