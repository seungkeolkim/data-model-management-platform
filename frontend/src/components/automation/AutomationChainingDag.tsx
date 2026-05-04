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
import type { ChainingGraph, ChainingNode } from '@/types/automation'
import {
  AUTOMATION_STATUS_COLOR,
  StatusBadge,
  TaskTypeTag,
  VersionTag,
} from './StatusBadge'

const { Text } = Typography

// React Flow 노드 기본 크기. grid layout 에 사용.
const NODE_WIDTH = 240
const NODE_HEIGHT = 110
const COL_GAP = 300
const ROW_GAP = 160

interface AutomationChainingDagProps {
  /**
   * 좌측 목록에서 선택된 PipelineVersion ID. 설정되면 DAG 에서 해당 노드 + 직접 연결된 엣지만 선명하게,
   * 그 외 노드 / 엣지는 opacity 를 낮춰 시각적으로 구분한다. null 이면 전체 평범 렌더.
   *
   * 027 §13 격하 후 노드 단위가 PipelineVersion 으로 바뀌었으므로 키도 versionId 다.
   */
  selectedVersionId: string | null
}

/**
 * Chaining DAG 시각화 — v7.13 baseline (PipelineVersion 단위).
 *
 * 노드 = PipelineVersion 1건. 라벨에 concept name + version (v1.0) + task_type 태그 + 상태 배지.
 * 엣지 = 두 version 이 같은 DatasetSplit 을 output / input 으로 공유하는 경우 자동 생성.
 *
 * 표시 규칙
 *   - automation 미등록 + run 0건 version 은 fixture 단계에서 이미 제외됐다.
 *   - 노드 색상 팔레트는 StatusBadge 의 AUTOMATION_STATUS_COLOR 와 일치 — 배지 / DAG 색상 언어 통일.
 *   - cycle 엣지 / 관련 노드는 빨강으로 강조.
 *   - 좌측 목록 행이 선택되면 해당 version 노드를 굵은 테두리 + box-shadow 로 강조, 다른 노드는 흐리게.
 *
 * 레이아웃
 *   - 단순 grid (3 columns) + fitView. dagre / elk 는 노드 수가 늘어 가독성이 떨어지면 도입 검토.
 */
export default function AutomationChainingDag({
  selectedVersionId,
}: AutomationChainingDagProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['automation', 'chaining'],
    queryFn: getChainingGraph,
  })

  const { nodes, edges, hasRenderable } = useMemo(
    () =>
      buildReactFlowGraph(
        data ?? { nodes: [], edges: [], cycles: [] },
        selectedVersionId,
      ),
    [data, selectedVersionId],
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
          <Empty description="표시할 파이프라인이 없습니다 (automation 미등록 + run 없음은 제외)" />
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
 * ChainingGraph (PipelineVersion 단위) → React Flow (nodes / edges) 변환.
 */
function buildReactFlowGraph(
  graph: ChainingGraph,
  selectedVersionId: string | null,
): {
  nodes: Node[]
  edges: Edge[]
  hasRenderable: boolean
} {
  const visibleNodes = graph.nodes
  const visibleIds = new Set(visibleNodes.map((node) => node.pipeline_version_id))

  // 사이클에 포함된 version ID 집합 — 테두리 빨강 강조용.
  const cycleVersionIds = new Set<string>()
  for (const cycle of graph.cycles) {
    for (const versionId of cycle) cycleVersionIds.add(versionId)
  }

  // 선택된 version 의 1-hop 이웃 집합 — 선택 강조 시 같이 선명하게 보인다.
  const neighborIds = new Set<string>()
  if (selectedVersionId) {
    neighborIds.add(selectedVersionId)
    for (const edge of graph.edges) {
      if (edge.source_version_id === selectedVersionId) {
        neighborIds.add(edge.target_version_id)
      }
      if (edge.target_version_id === selectedVersionId) {
        neighborIds.add(edge.source_version_id)
      }
    }
  }

  const nodes: Node[] = visibleNodes.map((node, index) => {
    const column = index % 3
    const row = Math.floor(index / 3)
    const isInCycle = cycleVersionIds.has(node.pipeline_version_id)
    const palette = AUTOMATION_STATUS_COLOR[node.automation_status]
    const isSelected = selectedVersionId === node.pipeline_version_id
    const dimmed = selectedVersionId !== null && !neighborIds.has(node.pipeline_version_id)
    return {
      id: node.pipeline_version_id,
      position: { x: column * COL_GAP, y: row * ROW_GAP },
      data: { label: <VersionNodeCard node={node} /> },
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
    .filter(
      (edge) =>
        visibleIds.has(edge.source_version_id) && visibleIds.has(edge.target_version_id),
    )
    .map((edge, index) => {
      const touchesSelected =
        selectedVersionId !== null &&
        (edge.source_version_id === selectedVersionId ||
          edge.target_version_id === selectedVersionId)
      const dimmed = selectedVersionId !== null && !touchesSelected
      const edgeLabel = `${edge.via_group_name} (${edge.via_split})`
      return {
        id: `edge-${index}`,
        source: edge.source_version_id,
        target: edge.target_version_id,
        label: edgeLabel,
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

  return { nodes, edges, hasRenderable: visibleNodes.length > 0 }
}

/**
 * DAG 노드 카드 — concept name + version 태그 + family 색 swatch + 상태 배지.
 */
function VersionNodeCard({ node }: { node: ChainingNode }) {
  return (
    <div style={{ padding: 8 }}>
      <Space size={4} align="center" style={{ marginBottom: 4 }}>
        <TaskTypeTag taskType={node.task_type} />
        <span
          style={{
            fontWeight: 600,
            fontSize: 12,
            wordBreak: 'break-all',
          }}
        >
          {node.pipeline_name}
        </span>
        <VersionTag version={node.pipeline_version} />
      </Space>
      <Space size={4} wrap>
        <StatusBadge status={node.automation_status} />
        {node.family_color && (
          <Tag color={node.family_color} style={{ fontSize: 10 }}>
            {node.family_name ?? 'family'}
          </Tag>
        )}
      </Space>
    </div>
  )
}
