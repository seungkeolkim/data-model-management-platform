/**
 * 클라이언트 사전 검증.
 *
 * - 각 노드의 definition.validate() 수집
 * - 구조 검증: SaveNode 정확히 1개, 순환 참조 없음
 */
import type { Edge } from '@xyflow/react'
import type { ClientValidationError, PipelineNode, PipelineNodeData } from '@/types/pipeline'
import { getNodeDefinition } from '../registry'
import type { AnyNodeData, NodeKind } from '../types'

export function validateGraphStructure(
  nodes: PipelineNode[],
  edges: Edge[],
  nodeDataMap: Record<string, PipelineNodeData>,
): ClientValidationError[] {
  const errors: ClientValidationError[] = []

  // SaveNode 개수 검사
  const saveNodes = nodes.filter((n) => nodeDataMap[n.id]?.type === 'save')
  if (saveNodes.length === 0) {
    errors.push({ message: 'Save 노드가 필요합니다. 출력 설정 노드를 추가해 주세요.' })
  } else if (saveNodes.length > 1) {
    errors.push({ message: 'Save 노드는 1개만 허용됩니다.' })
  }

  // 각 노드별 validate
  for (const node of nodes) {
    const data = nodeDataMap[node.id]
    if (!data) continue
    const definition = getNodeDefinition(data.type as NodeKind)
    if (!definition?.validate) continue
    const nodeErrors = definition.validate(
      data as never,
      {
        nodes: nodes as PipelineNode[] as unknown as { id: string; data: AnyNodeData }[] as never,
        edges,
        nodeDataMap: nodeDataMap as Record<string, AnyNodeData>,
        nodeId: node.id,
      },
    )
    errors.push(...nodeErrors)
  }

  const cycleError = detectCycle(nodes, edges)
  if (cycleError) errors.push({ message: cycleError })

  return errors
}

function detectCycle(nodes: PipelineNode[], edges: Edge[]): string | null {
  const nodeIds = new Set(nodes.map((n) => n.id))
  const inDegree = new Map<string, number>()
  const adjacency = new Map<string, string[]>()
  for (const id of nodeIds) {
    inDegree.set(id, 0)
    adjacency.set(id, [])
  }
  for (const edge of edges) {
    if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
      adjacency.get(edge.source)!.push(edge.target)
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1)
    }
  }
  const queue: string[] = []
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id)
  }
  let processedCount = 0
  while (queue.length > 0) {
    const current = queue.shift()!
    processedCount++
    for (const neighbor of adjacency.get(current) ?? []) {
      const newDeg = (inDegree.get(neighbor) ?? 1) - 1
      inDegree.set(neighbor, newDeg)
      if (newDeg === 0) queue.push(neighbor)
    }
  }
  if (processedCount < nodeIds.size) {
    return '순환 참조가 감지되었습니다. 노드 연결을 확인해 주세요.'
  }
  return null
}
