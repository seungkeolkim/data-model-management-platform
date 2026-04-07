/**
 * Lineage 탭
 *
 * React Flow로 데이터셋 lineage DAG를 시각화한다.
 * 현재 데이터셋은 하이라이트되며, upstream/downstream을 보여준다.
 * lineage가 없으면 (RAW 데이터셋 등) 안내 메시지를 표시한다.
 */
import { useMemo, useCallback } from 'react'
import {
  Spin,
  Empty,
  Tag,
  Typography,
} from 'antd'
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../../api/dataset'
import type { LineageNode, LineageEdge } from '../../types/dataset'

const { Text } = Typography

const TYPE_COLOR: Record<string, string> = {
  RAW: '#8c8c8c',
  SOURCE: '#1677ff',
  PROCESSED: '#52c41a',
  FUSION: '#722ed1',
}

const STATUS_COLOR: Record<string, string> = {
  READY: '#52c41a',
  PENDING: '#8c8c8c',
  PROCESSING: '#1677ff',
  ERROR: '#ff4d4f',
}

interface Props {
  datasetId: string
}

export default function LineageTab({ datasetId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['dataset-lineage', datasetId],
    queryFn: () => datasetsApi.lineage(datasetId).then(r => r.data),
  })

  const { nodes, edges } = useMemo(() => {
    if (!data || data.nodes.length === 0) {
      return { nodes: [], edges: [] }
    }
    return buildFlowGraph(data.nodes, data.edges, datasetId)
  }, [data, datasetId])

  if (isLoading) {
    return <Spin style={{ display: 'block', marginTop: 60, textAlign: 'center' }} />
  }

  if (!data || data.nodes.length <= 1 && data.edges.length === 0) {
    return (
      <Empty
        description="이 데이터셋에 대한 lineage 정보가 없습니다."
        style={{ marginTop: 40 }}
      >
        <Text type="secondary">
          RAW 데이터셋이거나 파이프라인으로 생성되지 않은 데이터셋입니다.
        </Text>
      </Empty>
    )
  }

  // 현재 데이터셋 노드의 pipeline.png URL
  const currentNode = data?.nodes.find(n => n.id === datasetId)
  const pipelineImageUrl = currentNode?.pipeline_image_url ?? null

  return (
    <div>
      <div style={{ height: 500, border: '1px solid #f0f0f0', borderRadius: 6 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {/* pipeline.png 폴백 이미지 — 생성 시점에 저장된 DAG 스냅샷 */}
      {pipelineImageUrl && (
        <div style={{ marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>
            파이프라인 실행 시점 DAG 스냅샷
          </Text>
          <img
            src={pipelineImageUrl}
            alt="Pipeline DAG"
            style={{
              maxWidth: '100%',
              border: '1px solid #f0f0f0',
              borderRadius: 6,
              background: '#fafafa',
            }}
          />
        </div>
      )}
    </div>
  )
}


/**
 * lineage 데이터를 React Flow 노드/엣지로 변환한다.
 * 간단한 자동 레이아웃: 깊이 기반 X 좌표, 같은 깊이는 Y 분산.
 */
function buildFlowGraph(
  lineageNodes: LineageNode[],
  lineageEdges: LineageEdge[],
  currentDatasetId: string,
): { nodes: Node[]; edges: Edge[] } {
  // 깊이 계산 (BFS from roots)
  const childToParents: Record<string, string[]> = {}
  const parentToChildren: Record<string, string[]> = {}
  for (const edge of lineageEdges) {
    if (!childToParents[edge.target]) childToParents[edge.target] = []
    childToParents[edge.target].push(edge.source)
    if (!parentToChildren[edge.source]) parentToChildren[edge.source] = []
    parentToChildren[edge.source].push(edge.target)
  }

  // root = 부모가 없는 노드
  const allIds = new Set(lineageNodes.map(n => n.id))
  const roots = lineageNodes.filter(n => !childToParents[n.id]?.some(pid => allIds.has(pid)))

  const depth: Record<string, number> = {}
  const queue: string[] = []
  for (const root of roots) {
    depth[root.id] = 0
    queue.push(root.id)
  }
  // 아직 depth가 없는 노드가 있으면 (고립 노드) depth 0 할당
  for (const node of lineageNodes) {
    if (!(node.id in depth)) {
      depth[node.id] = 0
      queue.push(node.id)
    }
  }

  while (queue.length > 0) {
    const current = queue.shift()!
    const children = parentToChildren[current] ?? []
    for (const childId of children) {
      const newDepth = depth[current] + 1
      if (!(childId in depth) || depth[childId] < newDepth) {
        depth[childId] = newDepth
        queue.push(childId)
      }
    }
  }

  // 깊이별 노드 그룹
  const depthGroups: Record<number, LineageNode[]> = {}
  for (const node of lineageNodes) {
    const nodeDepth = depth[node.id] ?? 0
    if (!depthGroups[nodeDepth]) depthGroups[nodeDepth] = []
    depthGroups[nodeDepth].push(node)
  }

  const HORIZONTAL_SPACING = 280
  const VERTICAL_SPACING = 100

  const flowNodes: Node[] = []
  for (const [depthStr, group] of Object.entries(depthGroups)) {
    const depthNum = Number(depthStr)
    const startY = -(group.length - 1) * VERTICAL_SPACING / 2

    for (let i = 0; i < group.length; i++) {
      const node = group[i]
      const isCurrent = node.id === currentDatasetId
      const borderColor = isCurrent ? '#1677ff' : TYPE_COLOR[node.dataset_type] ?? '#d9d9d9'
      const bgColor = isCurrent ? '#e6f4ff' : '#fff'

      flowNodes.push({
        id: node.id,
        position: { x: depthNum * HORIZONTAL_SPACING, y: startY + i * VERTICAL_SPACING },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: { label: '' },
        style: {
          border: `2px solid ${borderColor}`,
          borderRadius: 8,
          background: bgColor,
          padding: 0,
          width: 220,
        },
        type: 'default',
        // label을 HTML로 렌더링하기 위해 data.label에 React element 전달
        ...({
          data: {
            label: (
              <div style={{ padding: '8px 12px', fontSize: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  {node.group_name}
                  {isCurrent && <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>현재</Tag>}
                </div>
                <div style={{ color: '#8c8c8c', marginBottom: 2 }}>
                  {node.split} / {node.version}
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <Tag
                    color={TYPE_COLOR[node.dataset_type]}
                    style={{ fontSize: 10, margin: 0 }}
                  >
                    {node.dataset_type}
                  </Tag>
                  <span style={{
                    display: 'inline-block',
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: STATUS_COLOR[node.status] ?? '#8c8c8c',
                  }} />
                  <span style={{ color: '#8c8c8c', fontSize: 11 }}>
                    {node.image_count != null ? `${node.image_count}장` : ''}
                  </span>
                </div>
              </div>
            ),
          },
        }),
      })
    }
  }

  const flowEdges: Edge[] = lineageEdges.map(edge => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    animated: edge.target === currentDatasetId,
    label: edge.pipeline_summary ?? undefined,
    labelStyle: { fontSize: 10, fill: '#666' },
    labelBgStyle: { fill: '#fff', fillOpacity: 0.85 },
    labelBgPadding: [4, 2] as [number, number],
    style: { stroke: '#b0b0b0' },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#b0b0b0' },
  }))

  return { nodes: flowNodes, edges: flowEdges }
}
