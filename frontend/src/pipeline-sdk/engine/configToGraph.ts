/**
 * PipelineConfig → 그래프 역변환.
 *
 * 실행 순서:
 *   1. 정의된 순서대로 matchFromConfig 호출 → task/source 점유 기록
 *      (dataLoad → operator → merge → placeholder → save)
 *   2. ownership 맵을 뒤집어 sourceDatasetId/taskKey → nodeId 인덱스 생성
 *   3. 각 task의 inputs를 해석하여 엣지 생성
 *   4. save 노드는 sink task(다른 task의 input으로 참조되지 않는 task)에 연결
 *   5. 자동 레이아웃 적용
 */
import type { Edge } from '@xyflow/react'
import type {
  PipelineConfig,
  PipelineNodeData,
  PipelineNode,
  PipelineEdge,
} from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'
import { getNodeDefinition } from '../registry'
import type { AnyNodeData, MatchContext, NodeKind } from '../types'

export interface DatasetDisplayInfo {
  datasetId: string
  groupId: string
  groupName: string
  split: string
  version: string
}

/** 각 definition의 matchFromConfig 호출 순서 (나중 항목이 남은 task 흡수) */
const MATCH_ORDER: NodeKind[] = ['dataLoad', 'operator', 'merge', 'placeholder', 'save']

export function pipelineConfigToGraph(
  config: PipelineConfig,
  manipulatorMap: Record<string, Manipulator>,
  datasetDisplayMap: Record<string, DatasetDisplayInfo>,
): {
  nodes: PipelineNode[]
  edges: PipelineEdge[]
  nodeDataMap: Record<string, PipelineNodeData>
} {
  const nodes: PipelineNode[] = []
  const nodeDataMap: Record<string, AnyNodeData> = {}

  const ctx: MatchContext = {
    config,
    manipulatorMap,
    datasetDisplayMap,
    claimedTaskKeys: new Set<string>(),
    claimedSourceDatasetIds: new Set<string>(),
  }

  // taskKey → nodeId, datasetId → nodeId 인덱스 (엣지 복원용)
  const taskKeyToNodeId = new Map<string, string>()
  const datasetIdToNodeId = new Map<string, string>()

  for (const kind of MATCH_ORDER) {
    const definition = getNodeDefinition(kind)
    if (!definition?.matchFromConfig) continue
    const restored = definition.matchFromConfig(ctx) ?? []
    for (const entry of restored) {
      nodeDataMap[entry.nodeId] = entry.data
      nodes.push({
        id: entry.nodeId,
        type: kind,
        position: { x: 0, y: 0 },
        data: entry.data as PipelineNode['data'],
      })
      for (const taskKey of entry.ownedTaskKeys) {
        ctx.claimedTaskKeys.add(taskKey)
        taskKeyToNodeId.set(taskKey, entry.nodeId)
      }
      for (const datasetId of entry.ownedSourceDatasetIds ?? []) {
        ctx.claimedSourceDatasetIds.add(datasetId)
        datasetIdToNodeId.set(datasetId, entry.nodeId)
      }
    }
  }

  // 엣지 생성
  const edges: PipelineEdge[] = []
  let edgeCounter = 0
  const makeEdgeId = () => `edge_restore_${++edgeCounter}`

  for (const [taskKey, taskConfig] of Object.entries(config.tasks)) {
    const targetNodeId = taskKeyToNodeId.get(taskKey)
    if (!targetNodeId) continue
    for (const input of taskConfig.inputs) {
      let sourceNodeId: string | undefined
      if (input.startsWith('source:')) {
        const datasetId = input.split(':', 2)[1]
        sourceNodeId = datasetIdToNodeId.get(datasetId)
      } else {
        sourceNodeId = taskKeyToNodeId.get(input)
      }
      if (sourceNodeId) {
        edges.push({
          id: makeEdgeId(),
          source: sourceNodeId,
          target: targetNodeId,
          animated: true,
        })
      }
    }
  }

  // Save 노드 → sink task 연결
  const saveNodeId = nodes.find((n) => n.type === 'save')?.id
  if (saveNodeId) {
    // Passthrough 모드: tasks 가 비어있으면 DataLoad → Save 직결.
    //   v2: passthrough_source_split_id / v1 legacy: passthrough_source_dataset_id
    const passthroughSourceRef =
      config.passthrough_source_split_id || config.passthrough_source_dataset_id
    if (Object.keys(config.tasks).length === 0 && passthroughSourceRef) {
      const dataLoadNodeId = datasetIdToNodeId.get(passthroughSourceRef)
      if (dataLoadNodeId) {
        edges.push({
          id: makeEdgeId(),
          source: dataLoadNodeId,
          target: saveNodeId,
          animated: true,
        })
      }
    }
    const referencedTaskKeys = new Set<string>()
    for (const taskConfig of Object.values(config.tasks)) {
      for (const input of taskConfig.inputs) {
        if (!input.startsWith('source:')) {
          referencedTaskKeys.add(input)
        }
      }
    }
    for (const taskKey of Object.keys(config.tasks)) {
      if (referencedTaskKeys.has(taskKey)) continue
      const sourceNodeId = taskKeyToNodeId.get(taskKey)
      if (sourceNodeId) {
        edges.push({
          id: makeEdgeId(),
          source: sourceNodeId,
          target: saveNodeId,
          animated: true,
        })
      }
    }
  }

  applyAutoLayout(nodes, edges)
  return { nodes, edges, nodeDataMap: nodeDataMap as Record<string, PipelineNodeData> }
}

export function extractSourceDatasetIdsFromConfig(config: PipelineConfig): string[] {
  const datasetIds = new Set<string>()
  for (const task of Object.values(config.tasks)) {
    for (const input of task.inputs) {
      if (input.startsWith('source:')) {
        datasetIds.add(input.split(':', 2)[1])
      }
    }
  }
  return [...datasetIds]
}

/** topological sort 기반 좌→우 배치 (기존 pipelineConverter에서 이관) */
function applyAutoLayout(nodes: PipelineNode[], edges: PipelineEdge[]): void {
  const HORIZONTAL_GAP = 320
  const VERTICAL_GAP = 160
  const START_X = 60
  const START_Y = 80

  const nodeIdSet = new Set(nodes.map((n) => n.id))
  const outEdges = new Map<string, string[]>()
  const inDegree = new Map<string, number>()
  for (const nodeId of nodeIdSet) {
    outEdges.set(nodeId, [])
    inDegree.set(nodeId, 0)
  }
  for (const edge of edges) {
    if (nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target)) {
      outEdges.get(edge.source)!.push(edge.target)
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1)
    }
  }
  const depth = new Map<string, number>()
  const queue: string[] = []
  for (const [nodeId, deg] of inDegree) {
    if (deg === 0) {
      queue.push(nodeId)
      depth.set(nodeId, 0)
    }
  }
  while (queue.length > 0) {
    const current = queue.shift()!
    const currentDepth = depth.get(current)!
    for (const neighbor of outEdges.get(current) ?? []) {
      const newDepth = currentDepth + 1
      if (newDepth > (depth.get(neighbor) ?? 0)) depth.set(neighbor, newDepth)
      const newInDeg = (inDegree.get(neighbor) ?? 1) - 1
      inDegree.set(neighbor, newInDeg)
      if (newInDeg === 0) queue.push(neighbor)
    }
  }
  for (const node of nodes) {
    if (!depth.has(node.id)) depth.set(node.id, 0)
  }
  const depthGroups = new Map<number, PipelineNode[]>()
  for (const node of nodes) {
    const d = depth.get(node.id)!
    if (!depthGroups.has(d)) depthGroups.set(d, [])
    depthGroups.get(d)!.push(node)
  }
  for (const [d, groupNodes] of depthGroups) {
    const groupHeight = groupNodes.length * VERTICAL_GAP
    const offsetY = START_Y - groupHeight / 2 + VERTICAL_GAP / 2
    for (let i = 0; i < groupNodes.length; i++) {
      groupNodes[i].position = {
        x: START_X + d * HORIZONTAL_GAP,
        y: offsetY + i * VERTICAL_GAP,
      }
    }
  }
}
