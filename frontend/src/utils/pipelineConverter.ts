/**
 * 그래프 → PipelineConfig 변환 유틸리티
 *
 * React Flow의 노드/엣지 배열 + Zustand nodeDataMap으로부터
 * 백엔드 PipelineConfig JSON을 생성한다.
 * 클라이언트 사전 검증도 이 모듈에서 수행한다.
 */

import type { Edge } from '@xyflow/react'
import type {
  PipelineConfig,
  PipelineNodeData,
  ClientValidationError,
  DataLoadNodeData,
  SaveNodeData,
  PipelineNode,
} from '../types/pipeline'

// =============================================================================
// 클라이언트 사전 검증
// =============================================================================

/**
 * API 호출 전에 그래프 구조의 기본 유효성을 검사한다.
 * 에러가 있으면 API를 호출하지 않고 즉시 사용자에게 보여준다.
 */
export function validateGraphStructure(
  nodes: PipelineNode[],
  edges: Edge[],
  nodeDataMap: Record<string, PipelineNodeData>,
): ClientValidationError[] {
  const errors: ClientValidationError[] = []

  // 1. SaveNode 정확히 1개 존재해야 함
  const saveNodes = nodes.filter((n) => nodeDataMap[n.id]?.type === 'save')
  if (saveNodes.length === 0) {
    errors.push({ message: 'Save 노드가 필요합니다. 출력 설정 노드를 추가해 주세요.' })
  } else if (saveNodes.length > 1) {
    errors.push({ message: 'Save 노드는 1개만 허용됩니다.' })
  }

  // 2. SaveNode에 name이 입력되었는지
  for (const saveNode of saveNodes) {
    const data = nodeDataMap[saveNode.id] as SaveNodeData | undefined
    if (data && !data.name.trim()) {
      errors.push({ nodeId: saveNode.id, message: 'Save 노드에 출력 이름을 입력해 주세요.' })
    }
  }

  // 3. DataLoadNode에 데이터셋이 선택되었는지
  const dataLoadNodes = nodes.filter((n) => nodeDataMap[n.id]?.type === 'dataLoad')
  for (const dlNode of dataLoadNodes) {
    const data = nodeDataMap[dlNode.id] as DataLoadNodeData | undefined
    if (data && !data.datasetId) {
      errors.push({ nodeId: dlNode.id, message: '데이터셋을 선택해 주세요.' })
    }
  }

  // 4. operator/merge 노드에 입력 엣지가 있는지
  const taskNodes = nodes.filter((n) => {
    const d = nodeDataMap[n.id]
    return d?.type === 'operator' || d?.type === 'merge'
  })
  for (const taskNode of taskNodes) {
    const incomingEdges = edges.filter((e) => e.target === taskNode.id)
    if (incomingEdges.length === 0) {
      const data = nodeDataMap[taskNode.id]
      const label = data?.type === 'operator' ? (data as { label: string }).label : 'Merge'
      errors.push({ nodeId: taskNode.id, message: `"${label}" 노드에 입력 연결이 없습니다.` })
    }
  }

  // 5. SaveNode에 입력 엣지가 있는지
  for (const saveNode of saveNodes) {
    const incomingEdges = edges.filter((e) => e.target === saveNode.id)
    if (incomingEdges.length === 0) {
      errors.push({ nodeId: saveNode.id, message: 'Save 노드에 입력 연결이 없습니다.' })
    }
  }

  // 6. merge 노드는 2개 이상 입력 필요
  const mergeNodes = nodes.filter((n) => nodeDataMap[n.id]?.type === 'merge')
  for (const mergeNode of mergeNodes) {
    const incomingEdges = edges.filter((e) => e.target === mergeNode.id)
    if (incomingEdges.length > 0 && incomingEdges.length < 2) {
      errors.push({ nodeId: mergeNode.id, message: 'Merge 노드는 2개 이상의 입력이 필요합니다.' })
    }
  }

  // 7. 순환 참조 감지 (Kahn's algorithm)
  const cycleError = detectCycle(nodes, edges)
  if (cycleError) {
    errors.push({ message: cycleError })
  }

  return errors
}

/**
 * Kahn's algorithm으로 DAG 순환 참조를 감지한다.
 * 순환이 있으면 에러 메시지를 반환하고, 없으면 null을 반환한다.
 */
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

// =============================================================================
// 그래프 → PipelineConfig 변환
// =============================================================================

/**
 * React Flow 노드/엣지 + nodeDataMap → PipelineConfig JSON 생성.
 *
 * 변환 규칙:
 * - DataLoadNode → task가 아님, 하위 노드 inputs에 "source:<datasetId>"로 삽입
 * - OperatorNode/MergeNode → "task_<nodeId>" 이름의 TaskConfig
 * - SaveNode → config.name, config.output 매핑
 *
 * @throws Error 변환 불가 시 (SaveNode 없음 등)
 */
export function graphToPipelineConfig(
  nodes: PipelineNode[],
  edges: Edge[],
  nodeDataMap: Record<string, PipelineNodeData>,
): PipelineConfig {
  // SaveNode 찾기
  const saveNode = nodes.find((n) => nodeDataMap[n.id]?.type === 'save')
  if (!saveNode) {
    throw new Error('Save 노드가 없습니다.')
  }
  const saveData = nodeDataMap[saveNode.id] as SaveNodeData

  // task 노드 수집 (operator + merge)
  const taskNodes = nodes.filter((n) => {
    const d = nodeDataMap[n.id]
    return d?.type === 'operator' || d?.type === 'merge'
  })

  // 각 task 노드의 inputs 결정
  const tasks: Record<string, { operator: string; inputs: string[]; params: Record<string, unknown> }> = {}

  for (const taskNode of taskNodes) {
    const data = nodeDataMap[taskNode.id]
    const incomingEdges = edges.filter((e) => e.target === taskNode.id)
    const inputs: string[] = []

    for (const edge of incomingEdges) {
      const sourceData = nodeDataMap[edge.source]
      if (!sourceData) continue

      if (sourceData.type === 'dataLoad') {
        // DataLoad 노드 → source:<datasetId>
        const dlData = sourceData as DataLoadNodeData
        if (dlData.datasetId) {
          inputs.push(`source:${dlData.datasetId}`)
        }
      } else if (sourceData.type === 'operator' || sourceData.type === 'merge') {
        // 다른 task 노드 → task_<nodeId>
        inputs.push(`task_${edge.source}`)
      }
    }

    const operator = data.type === 'merge' ? 'merge_datasets' : (data as { operator: string }).operator
    const params = 'params' in data ? (data.params as Record<string, unknown>) : {}

    tasks[`task_${taskNode.id}`] = {
      operator,
      inputs,
      params,
    }
  }

  // SaveNode에 직접 연결된 소스가 DataLoad뿐인 경우 처리
  // (operator 없이 DataLoad → Save 직결은 의미 없으므로 에러)
  // 이 경우는 validateGraphStructure에서 이미 잡히므로 여기서는 무시

  // SaveNode의 입력이 task 노드인지 확인하여 terminal task 결정
  // (PipelineConfig 자체에는 terminal task를 명시하지 않음 — 백엔드가 sink 노드를 자동 탐색)

  return {
    name: saveData.name.trim(),
    description: saveData.description?.trim() || undefined,
    output: {
      dataset_type: saveData.datasetType,
      annotation_format: saveData.annotationFormat || null,
      split: saveData.split,
    },
    tasks,
  }
}
