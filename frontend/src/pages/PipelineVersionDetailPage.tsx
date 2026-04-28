/**
 * PipelineVersionDetailPage — PipelineVersion 상세 (readonly DAG + 메타 + 실행 이력).
 *
 * v7.11 (feature/pipeline-family-and-version, F-8):
 *   - DAG 는 에디터 컴포넌트 재사용 대신 readonly ReactFlow 로 분리 — 편집 path 와 격리.
 *   - 우측 사이드 패널: family / pipeline name / output / automation / 시각.
 *   - 헤더 드롭다운: 같은 Pipeline 의 다른 versions 로 전환 (family 가시화).
 *   - 하단: 이 version 의 PipelineRun 이력 inline 테이블.
 *   - "JSON 복사" — version.config 그대로 (v3 dataset_split 포맷).
 */
import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Typography,
  Tag,
  Space,
  Button,
  Descriptions,
  Select,
  Spin,
  Alert,
  Table,
  message,
  Drawer,
  Tooltip,
  Empty,
} from 'antd'
import {
  PlayCircleOutlined,
  CopyOutlined,
  ArrowLeftOutlined,
  CodeOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  ReactFlow,
  Background,
  Controls,
  ReactFlowProvider,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'

import {
  pipelineConceptsApi,
  pipelineVersionsApi,
  manipulatorsApi,
  datasetsForPipelineApi,
} from '@/api/pipeline'
import {
  pipelineConfigToGraph,
  buildNodeTypesFromRegistry,
} from '@/pipeline-sdk'
import type {
  PipelineConfig,
  PipelineNode,
  PipelineEdge,
  PipelineExecutionResponse,
  PipelineVersionResponse,
} from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'
import { VersionResolverModal } from '@/components/pipeline/VersionResolverModal'

const { Title, Text, Paragraph } = Typography

const nodeTypes = buildNodeTypesFromRegistry()

function PipelineVersionDetailContent() {
  const { versionId } = useParams<{ versionId: string }>()
  const navigate = useNavigate()
  const [resolverOpen, setResolverOpen] = useState(false)
  const [jsonDrawerOpen, setJsonDrawerOpen] = useState(false)

  // PipelineVersion 상세
  const versionQuery = useQuery({
    queryKey: ['pipeline-version-detail-page', versionId],
    queryFn: () =>
      versionId ? pipelineVersionsApi.get(versionId).then((r) => r.data) : null,
    enabled: !!versionId,
  })

  const versionDetail = versionQuery.data ?? null

  // 모 Pipeline (concept) — 같은 family 의 sibling version 드롭다운 표시용
  const conceptQuery = useQuery({
    queryKey: ['pipeline-concept-for-version', versionDetail?.pipeline_id],
    queryFn: () =>
      versionDetail?.pipeline_id
        ? pipelineConceptsApi.get(versionDetail.pipeline_id).then((r) => r.data)
        : null,
    enabled: !!versionDetail?.pipeline_id,
  })

  // PipelineRun 이력
  const runsQuery = useQuery({
    queryKey: ['pipeline-version-runs-page', versionId],
    queryFn: () =>
      versionId
        ? pipelineVersionsApi.listRuns(versionId, { page: 1, page_size: 20 }).then((r) => r.data)
        : null,
    enabled: !!versionId,
  })

  // DAG 복원에 필요한 manipulator + dataset display 매핑
  const manipulatorsQuery = useQuery({
    queryKey: ['manipulators-all-for-detail'],
    queryFn: () => manipulatorsApi.list().then((r) => r.data),
    staleTime: 60_000,
  })
  const groupsQuery = useQuery({
    queryKey: ['dataset-groups-all-for-detail'],
    queryFn: () => datasetsForPipelineApi.listGroups().then((r) => r.data),
    staleTime: 60_000,
  })

  const manipulatorMap = useMemo<Record<string, Manipulator>>(() => {
    const map: Record<string, Manipulator> = {}
    for (const m of manipulatorsQuery.data?.items ?? []) map[m.name] = m
    return map
  }, [manipulatorsQuery.data])

  const datasetDisplayMap = useMemo(() => {
    const map: Record<string, { datasetId: string; groupId: string; groupName: string; split: string; version: string }> = {}
    for (const group of groupsQuery.data?.items ?? []) {
      for (const ds of group.datasets ?? []) {
        if (!ds.split_id) continue
        const existing = map[ds.split_id]
        // 같은 split_id 에 대해 가장 최신 version 정보로 채움 (드롭다운 디스플레이용)
        if (!existing || ds.version.localeCompare(existing.version, 'en', { numeric: true }) > 0) {
          map[ds.split_id] = {
            datasetId: ds.id,
            groupId: group.id,
            groupName: group.name,
            split: ds.split,
            version: ds.version,
          }
        }
      }
    }
    return map
  }, [groupsQuery.data])

  // version.config → graph 복원
  const graph = useMemo(() => {
    if (!versionDetail) return null
    if (!manipulatorsQuery.data || !groupsQuery.data) return null
    try {
      const config = versionDetail.config as unknown as PipelineConfig
      return pipelineConfigToGraph(config, manipulatorMap, datasetDisplayMap)
    } catch (err) {
      console.warn('Graph 복원 실패', err)
      return null
    }
  }, [versionDetail, manipulatorMap, datasetDisplayMap, manipulatorsQuery.data, groupsQuery.data])

  const [graphNodes, setGraphNodes] = useState<PipelineNode[]>([])
  const [graphEdges, setGraphEdges] = useState<PipelineEdge[]>([])

  useEffect(() => {
    if (graph) {
      setGraphNodes(graph.nodes)
      setGraphEdges(graph.edges)
    }
  }, [graph])

  if (!versionId) {
    return <Alert type="error" message="versionId 가 URL 에 없습니다." />
  }

  if (versionQuery.isLoading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin tip="로딩 중…" />
      </div>
    )
  }

  if (!versionDetail) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          message="PipelineVersion 을 찾을 수 없습니다."
          description={`id=${versionId}`}
        />
        <Button onClick={() => navigate('/pipelines')} style={{ marginTop: 12 }}>
          파이프라인 목록으로
        </Button>
      </div>
    )
  }

  const handleCopyJson = async () => {
    try {
      const json = JSON.stringify(versionDetail.config, null, 2)
      await navigator.clipboard.writeText(json)
      message.success('PipelineVersion config JSON 을 클립보드에 복사했습니다.')
    } catch (err) {
      message.error(`복사 실패: ${(err as Error)?.message ?? ''}`)
    }
  }

  const switchVersion = (newVersionId: string) => {
    if (newVersionId !== versionId) {
      navigate(`/pipeline-versions/${newVersionId}`)
    }
  }

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 헤더 */}
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
        <Space size={12}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/pipelines')}
          >
            목록
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            {versionDetail.pipeline_name}
          </Title>
          {versionDetail.family_name && (
            <Tag color="gold">{versionDetail.family_name}</Tag>
          )}
          <Select
            value={versionDetail.id}
            style={{ minWidth: 160 }}
            onChange={switchVersion}
            options={(conceptQuery.data?.versions ?? []).map((v) => ({
              value: v.id,
              label: (
                <span>
                  v{v.version}
                  {!v.is_active && <Tag style={{ marginLeft: 6 }}>비활성</Tag>}
                </span>
              ),
            }))}
          />
          {!versionDetail.is_active && <Tag color="default">비활성 version</Tag>}
        </Space>
        <Space>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            disabled={!versionDetail.is_active}
            onClick={() => setResolverOpen(true)}
          >
            실행
          </Button>
          <Tooltip title="이 version 의 config JSON 을 클립보드 복사">
            <Button icon={<CopyOutlined />} onClick={handleCopyJson}>
              JSON 복사
            </Button>
          </Tooltip>
          <Tooltip title="config JSON 본문 보기">
            <Button icon={<CodeOutlined />} onClick={() => setJsonDrawerOpen(true)}>
              JSON 보기
            </Button>
          </Tooltip>
        </Space>
      </Space>

      <div style={{ flex: 1, display: 'flex', gap: 16, overflow: 'hidden' }}>
        {/* DAG (readonly) */}
        <div
          style={{
            flex: 1,
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            background: '#f8f9fa',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {!graph && (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Spin tip="DAG 복원 중…" />
            </div>
          )}
          {graph && (
            <ReactFlow
              nodes={graphNodes}
              edges={graphEdges}
              nodeTypes={nodeTypes}
              fitView
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={true}
              edgesFocusable={false}
              deleteKeyCode={null}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={20} size={1} color="#e0e0e0" />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
        </div>

        {/* 사이드 패널 */}
        <div
          style={{
            width: 320,
            borderLeft: '1px solid #f0f0f0',
            paddingLeft: 16,
            overflowY: 'auto',
          }}
        >
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="버전">
              <Text strong>v{versionDetail.version}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="개념명">
              {versionDetail.pipeline_name}
            </Descriptions.Item>
            <Descriptions.Item label="Family">
              {versionDetail.family_name ?? <Text type="secondary">미분류</Text>}
            </Descriptions.Item>
            <Descriptions.Item label="Task">
              <Tag>{versionDetail.task_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Output">
              {versionDetail.output_group_name} / {versionDetail.output_split}
            </Descriptions.Item>
            <Descriptions.Item label="자동화">
              {versionDetail.has_automation ? (
                <Tag color="purple">등록됨</Tag>
              ) : (
                <Text type="secondary">없음</Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="Active">
              {versionDetail.is_active ? <Tag color="green">active</Tag> : <Tag>비활성</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="생성">
              {dayjs(versionDetail.created_at).format('YYYY-MM-DD HH:mm')}
            </Descriptions.Item>
            <Descriptions.Item label="수정">
              {dayjs(versionDetail.updated_at).format('YYYY-MM-DD HH:mm')}
            </Descriptions.Item>
          </Descriptions>
        </div>
      </div>

      {/* 실행 이력 (하단) */}
      <div style={{ marginTop: 16 }}>
        <Title level={5} style={{ margin: '0 0 8px 0' }}>
          이 버전의 실행 이력 ({runsQuery.data?.total ?? 0}건)
        </Title>
        {(runsQuery.data?.items.length ?? 0) === 0 ? (
          <Empty description="아직 실행 이력이 없습니다." />
        ) : (
          <RunHistoryTable items={runsQuery.data?.items ?? []} />
        )}
      </div>

      <VersionResolverModal
        open={resolverOpen}
        pipelineVersion={versionDetail}
        onClose={() => setResolverOpen(false)}
        onSubmitted={() => {
          message.success('실행 제출 완료')
          runsQuery.refetch()
        }}
      />

      <Drawer
        open={jsonDrawerOpen}
        onClose={() => setJsonDrawerOpen(false)}
        title="PipelineVersion config (JSON)"
        width={640}
      >
        <Paragraph>
          <Button icon={<CopyOutlined />} size="small" onClick={handleCopyJson}>
            클립보드 복사
          </Button>
        </Paragraph>
        <pre
          style={{
            background: '#f5f5f5',
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            overflowX: 'auto',
          }}
        >
          {JSON.stringify(versionDetail.config, null, 2)}
        </pre>
      </Drawer>
    </div>
  )
}

interface RunHistoryTableProps {
  items: PipelineExecutionResponse[]
}

function RunHistoryTable({ items }: RunHistoryTableProps) {
  const columns: ColumnsType<PipelineExecutionResponse> = [
    {
      title: 'Run ID',
      dataIndex: 'id',
      key: 'id',
      width: 140,
      render: (id: string) => (
        <Text code style={{ fontSize: 11 }}>
          {id.slice(0, 8)}…
        </Text>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 130,
      render: (status: string) => {
        const color =
          status === 'DONE' ? 'green'
          : status === 'FAILED' ? 'red'
          : status === 'RUNNING' ? 'blue'
          : 'default'
        return <Tag color={color}>{status}</Tag>
      },
    },
    {
      title: 'Output Dataset',
      key: 'output',
      render: (_v, run) =>
        run.output_dataset_version ? (
          <Text style={{ fontSize: 12 }}>
            v{run.output_dataset_version}
          </Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>—</Text>
        ),
    },
    {
      title: '시작',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 150,
      render: (dt: string | null) =>
        dt ? (
          <Text style={{ fontSize: 11 }}>{dayjs(dt).format('YY-MM-DD HH:mm')}</Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 11 }}>—</Text>
        ),
    },
    {
      title: '종료',
      dataIndex: 'finished_at',
      key: 'finished_at',
      width: 150,
      render: (dt: string | null) =>
        dt ? (
          <Text style={{ fontSize: 11 }}>{dayjs(dt).format('YY-MM-DD HH:mm')}</Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 11 }}>—</Text>
        ),
    },
  ]
  return (
    <Table<PipelineExecutionResponse>
      rowKey="id"
      columns={columns}
      dataSource={items}
      pagination={false}
      size="small"
    />
  )
}

export default function PipelineVersionDetailPage() {
  return (
    <ReactFlowProvider>
      <PipelineVersionDetailContent />
    </ReactFlowProvider>
  )
}
