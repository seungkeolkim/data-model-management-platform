import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Card, Alert, Empty, Space, Typography, Tag } from 'antd'
import { getChainingGraph } from '@/api/automation'
import type { Pipeline, ChainingGraph } from '@/types/automation'
import { AUTOMATION_STATUS_COLOR, StatusBadge, TaskTypeTag } from './StatusBadge'

const { Text } = Typography

// React Flow 노드 기본 크기. grid layout 에 사용.
const NODE_WIDTH = 240
const NODE_HEIGHT = 110
const COL_GAP = 300
const ROW_GAP = 160

interface AutomationChainingDagProps {
  /**
   * 좌측 목록에서 선택된 파이프라인 ID. 설정되면 DAG 에서 해당 노드 + 직접 연결된 엣지만 선명하게,
   * 그 외 노드 / 엣지는 opacity 를 낮춰 시각적으로 구분한다. null 이면 전체 평범 렌더.
   */
  selectedPipelineId: string | null
}

/**
 * Chaining DAG 시각화 (Automation 관리 페이지 우측, §6-2 / §E-20).
 *
 * 표시 규칙
 *   - "stopped + 이력 0 건" 파이프라인은 제외 (§9-6). 본 목업은 모든 파이프라인이 이력을 갖도록 구성돼
 *     있어 전량 표시되지만, 필터 로직은 미리 두어 실 API 전환 후에도 그대로 동작.
 *   - 노드 색상 팔레트는 StatusBadge 의 AUTOMATION_STATUS_COLOR 와 일치 — 배지 / DAG 색상 언어 통일.
 *   - cycle 엣지 / 관련 노드는 빨강으로 강조 (§B-11 시연).
 *   - 좌측 목록 행이 선택되면 해당 노드를 굵은 테두리 + box-shadow 로 강조, 다른 노드는 흐리게 (opacity 0.3).
 *
 * 레이아웃
 *   - 단순 grid (3 columns). depth 기반 topological 레이아웃은 dagre 같은 라이브러리 도입 이전에는
 *     cycle 케이스를 깔끔히 처리하기 번거로워, 목업에서는 수동 grid + fitView 로 시작.
 */
export default function AutomationChainingDag({
  selectedPipelineId,
}: AutomationChainingDagProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['automation', 'chaining'],
    queryFn: getChainingGraph,
  })

  const { nodes, edges, hasRenderable } = useMemo(
    () =>
      buildReactFlowGraph(
        data ?? { nodes: [], edges: [], cycles: [] },
        selectedPipelineId,
      ),
    [data, selectedPipelineId],
  )

  return (
    <Card title="파이프라인 의존 그래프" size="small" styles={{ body: { padding: 8 } }}>
      {error && (
        <Alert
          type="error"
          message="DAG 로드 실패"
          description={(error as Error).message}
          style={{ margin: 8 }}
        />
      )}
      {!isLoading && !hasRenderable && (
        <div style={{ padding: 24 }}>
          <Empty description="표시할 파이프라인이 없습니다 (stopped + 이력 없음은 제외)" />
        </div>
      )}
      {hasRenderable && (
        <div style={{ height: 520, border: '1px solid #f0f0f0', borderRadius: 4 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodesConnectable={false}
            nodesDraggable
            fitView
            fitViewOptions={{ padding: 0.25 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      )}
      <div style={{ padding: 8, paddingTop: 12 }}>
        <Space size={6} wrap>
          <Text type="secondary" style={{ fontSize: 12 }}>
            범례:
          </Text>
          <StatusBadge status="stopped" />
          <StatusBadge status="active" />
          <StatusBadge status="error" />
          <Tag color="red" style={{ fontSize: 11 }}>
            사이클 엣지
          </Tag>
        </Space>
      </div>
    </Card>
  )
}

/**
 * ChainingGraph → React Flow (nodes / edges) 변환.
 *
 * "미실행 + stopped" 필터링은 목업 fixture 상 해당하는 노드가 없지만 방어적으로 포함.
 * 판정 기준은 "마지막 실행 시각이 null 이고 automation_status === stopped" 로 충분.
 */
function buildReactFlowGraph(
  graph: ChainingGraph,
  selectedPipelineId: string | null,
): {
  nodes: Node[]
  edges: Edge[]
  hasRenderable: boolean
} {
  const visiblePipelines = graph.nodes.filter(
    (pipeline) => !(pipeline.automation_status === 'stopped' && pipeline.last_execution_at === null),
  )
  const visibleIds = new Set(visiblePipelines.map((pipeline) => pipeline.id))

  // 사이클에 포함된 파이프라인 ID 집합 — 테두리 빨강 강조용.
  const cycleIds = new Set<string>()
  for (const cycle of graph.cycles) {
    for (const pipelineId of cycle) cycleIds.add(pipelineId)
  }

  // 선택된 파이프라인의 1-hop 이웃 집합 — 선택 강조 시 같이 선명하게 보인다.
  const neighborIds = new Set<string>()
  if (selectedPipelineId) {
    neighborIds.add(selectedPipelineId)
    for (const edge of graph.edges) {
      if (edge.source_pipeline_id === selectedPipelineId) {
        neighborIds.add(edge.target_pipeline_id)
      }
      if (edge.target_pipeline_id === selectedPipelineId) {
        neighborIds.add(edge.source_pipeline_id)
      }
    }
  }

  const nodes: Node[] = visiblePipelines.map((pipeline, index) => {
    const column = index % 3
    const row = Math.floor(index / 3)
    const isInCycle = cycleIds.has(pipeline.id)
    const palette = AUTOMATION_STATUS_COLOR[pipeline.automation_status]
    const isSelected = selectedPipelineId === pipeline.id
    // 선택된 게 있을 때 — 이웃이 아니면 흐림. 선택 없으면 전부 선명.
    const dimmed = selectedPipelineId !== null && !neighborIds.has(pipeline.id)
    return {
      id: pipeline.id,
      position: { x: column * COL_GAP, y: row * ROW_GAP },
      data: { label: <PipelineNodeCard pipeline={pipeline} /> },
      style: {
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        border: `${isSelected ? 3 : 2}px solid ${isInCycle ? '#ff4d4f' : palette.border}`,
        background: palette.background,
        borderRadius: 8,
        padding: 0,
        opacity: dimmed ? 0.3 : 1,
        boxShadow: isSelected ? '0 0 0 3px rgba(22,119,255,0.25)' : undefined,
        transition: 'opacity 0.2s, box-shadow 0.2s, border-width 0.2s',
      },
    }
  })

  const edges: Edge[] = graph.edges
    .filter((edge) => visibleIds.has(edge.source_pipeline_id) && visibleIds.has(edge.target_pipeline_id))
    .map((edge, index) => {
      const touchesSelected =
        selectedPipelineId !== null &&
        (edge.source_pipeline_id === selectedPipelineId ||
          edge.target_pipeline_id === selectedPipelineId)
      const dimmed = selectedPipelineId !== null && !touchesSelected
      return {
        id: `edge-${index}`,
        source: edge.source_pipeline_id,
        target: edge.target_pipeline_id,
        label: edge.via_group_name,
        labelStyle: { fontSize: 10, fill: edge.in_cycle ? '#cf1322' : '#595959' },
        labelBgStyle: { fill: '#fff', fillOpacity: 0.9 },
        style: {
          stroke: edge.in_cycle ? '#ff4d4f' : '#1677ff',
          strokeWidth: edge.in_cycle ? 2.5 : 1.5,
          opacity: dimmed ? 0.2 : 1,
        },
        animated: edge.in_cycle,
        markerEnd: { type: MarkerType.ArrowClosed, color: edge.in_cycle ? '#ff4d4f' : '#1677ff' },
      }
    })

  return { nodes, edges, hasRenderable: visiblePipelines.length > 0 }
}

/**
 * DAG 노드 카드. 이름 + 상태 배지 + 모드·주기 요약을 한 칸에.
 */
function PipelineNodeCard({ pipeline }: { pipeline: Pipeline }) {
  return (
    <div style={{ padding: 8 }}>
      <Space size={4} align="center" style={{ marginBottom: 4 }}>
        <TaskTypeTag taskType={pipeline.task_type} />
        <span
          style={{
            fontWeight: 600,
            fontSize: 12,
            wordBreak: 'break-all',
          }}
        >
          {pipeline.name}
        </span>
      </Space>
      <Space size={4} wrap>
        <StatusBadge status={pipeline.automation_status} />
        {pipeline.automation_mode && (
          <Tag style={{ fontSize: 10 }}>{pipeline.automation_mode}</Tag>
        )}
        {pipeline.automation_poll_interval && (
          <Tag color="geekblue" style={{ fontSize: 10 }}>
            {pipeline.automation_poll_interval}
          </Tag>
        )}
      </Space>
    </div>
  )
}
