/**
 * Lineage 탭
 *
 * React Flow로 데이터셋 lineage DAG를 시각화한다.
 * 현재 데이터셋은 하이라이트되며, upstream/downstream을 보여준다.
 * lineage가 없으면 (RAW 데이터셋 등) 안내 메시지를 표시한다.
 */
import { useState, useMemo, useCallback } from 'react'
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
  useNodesState,
  useEdgesState,
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

  const initialGraph = useMemo(() => {
    if (!data || data.nodes.length === 0) {
      return { nodes: [] as Node[], edges: [] as Edge[] }
    }
    return buildFlowGraph(data.nodes, data.edges, datasetId)
  }, [data, datasetId])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialGraph.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialGraph.edges)

  // data가 바뀌면 노드/엣지 재설정
  useMemo(() => {
    setNodes(initialGraph.nodes)
    setEdges(initialGraph.edges)
  }, [initialGraph])

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
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          nodesConnectable={false}
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
 *
 * 데이터셋은 사각 노드, manipulator(태스크)는 둥근 노드로 표시.
 * transform_config.tasks가 있으면 manipulator를 중간 노드로 배치하고,
 * 파싱 실패 시 소스→출력 직접 엣지로 폴백한다.
 *
 * 레이아웃: 깊이 기반 X 좌표, 같은 깊이는 Y 분산.
 */
function buildFlowGraph(
  lineageNodes: LineageNode[],
  lineageEdges: LineageEdge[],
  currentDatasetId: string,
): { nodes: Node[]; edges: Edge[] } {
  const flowNodes: Node[] = []
  const flowEdges: Edge[] = []

  // ── 1. 같은 child_id를 공유하는 엣지를 그룹핑 (동일 파이프라인 실행) ──
  const edgesByChild: Record<string, LineageEdge[]> = {}
  for (const edge of lineageEdges) {
    if (!edgesByChild[edge.target]) edgesByChild[edge.target] = []
    edgesByChild[edge.target].push(edge)
  }

  // ── 2. 파이프라인 태스크(manipulator) 노드 + 엣지 생성 ──
  // childId별로 한 번만 태스크 노드를 만든다
  // 태스크 노드가 삽입되면 해당 child의 lineage 엣지는 직접 연결하지 않음
  const childrenWithTaskNodes = new Set<string>()

  for (const [childId, groupEdges] of Object.entries(edgesByChild)) {
    // transform_config는 동일 child의 모든 엣지에서 같으므로 첫 번째 것 사용
    const transformConfig = groupEdges[0]?.transform_config as
      | { tasks?: Record<string, { operator?: string; inputs?: string[]; params?: Record<string, unknown> }> }
      | null

    if (!transformConfig?.tasks || Object.keys(transformConfig.tasks).length === 0) {
      continue
    }

    const tasks = transformConfig.tasks
    const taskNames = Object.keys(tasks)

    // topological sort (간이 구현)
    const taskOrder = _topologicalSort(tasks)
    if (taskOrder.length === 0) continue

    childrenWithTaskNodes.add(childId)

    // 태스크 노드 생성
    for (const taskName of taskOrder) {
      const taskConf = tasks[taskName]
      const operator = taskConf.operator ?? taskName
      const nodeId = `task_${childId}_${taskName}`

      // 파라미터 요약 — key_value(object)는 "old → new" 형식, 나머지는 "label: value"
      const paramEntries = Object.entries(taskConf.params ?? {})
      const paramLines: string[] = []
      for (const [key, value] of paramEntries) {
        if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
          for (const [k, v] of Object.entries(value as Record<string, string>)) {
            paramLines.push(`${k} → ${v}`)
          }
        } else {
          const valueStr = String(value)
          paramLines.push(`${key}: ${valueStr.length > 20 ? valueStr.slice(0, 17) + '...' : valueStr}`)
        }
      }

      flowNodes.push({
        id: nodeId,
        position: { x: 0, y: 0 }, // 레이아웃에서 재배치됨
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div style={{ padding: '6px 10px', fontSize: 11, textAlign: 'center' }}>
              <div style={{ fontWeight: 600, color: '#d97706' }}>{operator}</div>
              {paramLines.length > 0 && (
                <div style={{ color: '#8c8c8c', fontSize: 10, marginTop: 2 }}>
                  {paramLines.map((line, idx) => (
                    <div key={idx}>{line}</div>
                  ))}
                </div>
              )}
            </div>
          ),
        },
        style: {
          border: '2px solid #f59e0b',
          borderRadius: 20,
          background: '#fffbeb',
          padding: 0,
          width: 180,
        },
        type: 'default',
      })
    }

    // 태스크 간 엣지 + 소스→태스크, 태스크→출력 엣지 생성
    const sourceDatasetIds = new Set(groupEdges.map(e => e.source))

    for (const taskName of taskOrder) {
      const taskConf = tasks[taskName]
      const taskNodeId = `task_${childId}_${taskName}`

      for (const input of taskConf.inputs ?? []) {
        if (input.startsWith('source:')) {
          // source:<dataset_id> → 이 태스크
          const sourceId = input.split(':')[1]
          if (sourceDatasetIds.has(sourceId)) {
            flowEdges.push({
              id: `e_src_${sourceId}_${taskNodeId}`,
              source: sourceId,
              target: taskNodeId,
              animated: true,
              style: { stroke: '#f59e0b' },
              markerEnd: { type: MarkerType.ArrowClosed, color: '#f59e0b' },
            })
          }
        } else {
          // 다른 태스크 → 이 태스크
          flowEdges.push({
            id: `e_task_${childId}_${input}_${taskName}`,
            source: `task_${childId}_${input}`,
            target: taskNodeId,
            animated: true,
            style: { stroke: '#f59e0b' },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#f59e0b' },
          })
        }
      }
    }

    // 최종 태스크(다른 태스크의 input으로 참조되지 않는 것) → 출력 데이터셋
    const referencedAsDep = new Set<string>()
    for (const taskConf of Object.values(tasks)) {
      for (const input of taskConf.inputs ?? []) {
        if (!input.startsWith('source:')) referencedAsDep.add(input)
      }
    }
    const terminalTasks = taskNames.filter(name => !referencedAsDep.has(name))
    for (const terminalName of terminalTasks) {
      flowEdges.push({
        id: `e_task_${childId}_${terminalName}_out`,
        source: `task_${childId}_${terminalName}`,
        target: childId,
        animated: true,
        style: { stroke: '#f59e0b' },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#f59e0b' },
      })
    }
  }

  // ── 3. transform_config가 없는 직접 엣지 (폴백) ──
  for (const edge of lineageEdges) {
    if (childrenWithTaskNodes.has(edge.target)) continue
    flowEdges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      animated: true,
      style: { stroke: '#b0b0b0' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#b0b0b0' },
    })
  }

  // ── 4. 전체 그래프에서 깊이 기반 레이아웃 계산 ──
  // 모든 노드(데이터셋 + 태스크)를 합쳐서 BFS 깊이 계산
  const allNodeIds = new Set([
    ...lineageNodes.map(n => n.id),
    ...flowNodes.map(n => n.id),
  ])
  const adjForward: Record<string, string[]> = {}
  const adjBackward: Record<string, string[]> = {}
  for (const edge of flowEdges) {
    if (!adjForward[edge.source]) adjForward[edge.source] = []
    adjForward[edge.source].push(edge.target)
    if (!adjBackward[edge.target]) adjBackward[edge.target] = []
    adjBackward[edge.target].push(edge.source)
  }

  // root = 부모가 없는 노드
  const roots = [...allNodeIds].filter(id => !adjBackward[id]?.some(pid => allNodeIds.has(pid)))

  const depth: Record<string, number> = {}
  const bfsQueue: string[] = []
  for (const rootId of roots) {
    depth[rootId] = 0
    bfsQueue.push(rootId)
  }
  for (const id of allNodeIds) {
    if (!(id in depth)) {
      depth[id] = 0
      bfsQueue.push(id)
    }
  }
  while (bfsQueue.length > 0) {
    const current = bfsQueue.shift()!
    for (const childId of adjForward[current] ?? []) {
      const newDepth = depth[current] + 1
      if (!(childId in depth) || depth[childId] < newDepth) {
        depth[childId] = newDepth
        bfsQueue.push(childId)
      }
    }
  }

  // ── 5. 데이터셋 노드 생성 (깊이별 Y 배치) ──
  const HORIZONTAL_SPACING = 250
  const VERTICAL_SPACING = 100

  // 깊이별 노드 그룹 (데이터셋 + 태스크 합산)
  const depthGroups: Record<number, string[]> = {}
  for (const id of allNodeIds) {
    const nodeDepth = depth[id] ?? 0
    if (!depthGroups[nodeDepth]) depthGroups[nodeDepth] = []
    depthGroups[nodeDepth].push(id)
  }

  // 각 노드의 위치 계산
  const nodePositions: Record<string, { x: number; y: number }> = {}
  for (const [depthStr, group] of Object.entries(depthGroups)) {
    const depthNum = Number(depthStr)
    const startY = -(group.length - 1) * VERTICAL_SPACING / 2
    for (let i = 0; i < group.length; i++) {
      nodePositions[group[i]] = { x: depthNum * HORIZONTAL_SPACING, y: startY + i * VERTICAL_SPACING }
    }
  }

  // 데이터셋 노드 추가
  const lineageNodeMap = new Map(lineageNodes.map(n => [n.id, n]))
  for (const node of lineageNodes) {
    const isCurrent = node.id === currentDatasetId
    const borderColor = isCurrent ? '#1677ff' : TYPE_COLOR[node.dataset_type] ?? '#d9d9d9'
    const bgColor = isCurrent ? '#e6f4ff' : '#fff'
    const pos = nodePositions[node.id] ?? { x: 0, y: 0 }

    flowNodes.push({
      id: node.id,
      position: pos,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
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
      style: {
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        background: bgColor,
        padding: 0,
        width: 220,
      },
      type: 'default',
    })
  }

  // 태스크 노드 위치 업데이트
  for (const taskNode of flowNodes) {
    if (taskNode.id.startsWith('task_') && nodePositions[taskNode.id]) {
      taskNode.position = nodePositions[taskNode.id]
    }
  }

  return { nodes: flowNodes, edges: flowEdges }
}


/**
 * 태스크 의존관계를 간이 topological sort한다.
 * 실패 시 빈 배열 반환.
 */
function _topologicalSort(
  tasks: Record<string, { inputs?: string[] }>,
): string[] {
  try {
    const taskNames = Object.keys(tasks)
    const inDegree: Record<string, number> = {}
    const adj: Record<string, string[]> = {}
    for (const name of taskNames) {
      inDegree[name] = 0
      adj[name] = []
    }
    for (const [name, conf] of Object.entries(tasks)) {
      for (const input of conf.inputs ?? []) {
        if (!input.startsWith('source:') && input in inDegree) {
          adj[input].push(name)
          inDegree[name]++
        }
      }
    }
    const queue = taskNames.filter(n => inDegree[n] === 0)
    const order: string[] = []
    while (queue.length > 0) {
      const current = queue.shift()!
      order.push(current)
      for (const next of adj[current]) {
        inDegree[next]--
        if (inDegree[next] === 0) queue.push(next)
      }
    }
    return order.length === taskNames.length ? order : []
  } catch {
    return []
  }
}
