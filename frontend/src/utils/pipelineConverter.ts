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
  OperatorNodeData,
  MergeNodeData,
  SaveNodeData,
  PipelineNode,
  PipelineEdge,
} from '../types/pipeline'
import type { Manipulator } from '../types/dataset'

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

// =============================================================================
// PipelineConfig → 그래프 역변환 (JSON 불러오기)
// =============================================================================

/**
 * PipelineConfig JSON에서 사용되는 소스 dataset_id 목록을 추출한다.
 * DataLoadNode 복원 시 API 조회가 필요한 ID 목록을 사전에 파악하기 위해 사용.
 */
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

/**
 * DataLoadNode 복원에 필요한 데이터셋 표시 정보.
 * 외부에서 API 조회 후 이 형태로 전달한다.
 */
export interface DatasetDisplayInfo {
  datasetId: string
  groupId: string
  groupName: string
  split: string
  version: string
}

/**
 * PipelineConfig JSON → React Flow 노드/엣지 + nodeDataMap 역변환.
 *
 * manipulator 메타(label, category, paramsSchema)와 dataset 표시 정보는
 * 호출자가 미리 조회하여 전달한다. 이 함수 자체는 순수 동기 함수.
 *
 * @param config - PipelineConfig JSON
 * @param manipulatorMap - operator name → Manipulator 메타 매핑 (팔레트 로딩과 동일한 데이터)
 * @param datasetDisplayMap - dataset_id → 표시 정보 매핑 (API 조회 결과)
 * @returns 복원된 노드/엣지/nodeDataMap
 */
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
  const edges: PipelineEdge[] = []
  const nodeDataMap: Record<string, PipelineNodeData> = {}

  // ── 1. 소스 dataset_id별 DataLoadNode 생성 ──
  // 동일 dataset_id가 여러 task에서 참조되더라도 DataLoadNode는 1개만 생성
  const datasetIdToNodeId = new Map<string, string>()
  const sourceDatasetIds = extractSourceDatasetIdsFromConfig(config)

  for (const datasetId of sourceDatasetIds) {
    const nodeId = `dl_${datasetId.slice(0, 8)}`
    datasetIdToNodeId.set(datasetId, nodeId)

    const displayInfo = datasetDisplayMap[datasetId]
    const dataLoadData: DataLoadNodeData = {
      type: 'dataLoad',
      groupId: displayInfo?.groupId ?? null,
      groupName: displayInfo?.groupName ?? '',
      split: displayInfo?.split ?? null,
      datasetId,
      version: displayInfo?.version ?? null,
      datasetLabel: displayInfo
        ? `${displayInfo.groupName} / ${displayInfo.split} / ${displayInfo.version}`
        : `source:${datasetId.slice(0, 8)}...`,
    }

    nodeDataMap[nodeId] = dataLoadData
    nodes.push({
      id: nodeId,
      type: 'dataLoad',
      position: { x: 0, y: 0 }, // 레이아웃에서 재배치
      data: dataLoadData as PipelineNode['data'],
    })
  }

  // ── 2. task 노드 생성 (operator / merge) ──
  // config의 task key는 "task_<원본nodeId>" 형태 → 원본 nodeId 복원
  const taskKeyToNodeId = new Map<string, string>()

  for (const [taskKey, taskConfig] of Object.entries(config.tasks)) {
    // task key에서 "task_" 접두사를 제거하여 원본 노드 ID 복원
    const nodeId = taskKey.startsWith('task_') ? taskKey.slice(5) : taskKey

    taskKeyToNodeId.set(taskKey, nodeId)

    if (taskConfig.operator === 'merge_datasets') {
      // MergeNode
      const mergeData: MergeNodeData = {
        type: 'merge',
        operator: 'merge_datasets',
        params: { ...taskConfig.params },
        inputCount: taskConfig.inputs.length,
      }
      nodeDataMap[nodeId] = mergeData
      nodes.push({
        id: nodeId,
        type: 'merge',
        position: { x: 0, y: 0 },
        data: mergeData as PipelineNode['data'],
      })
    } else {
      // OperatorNode
      const manipulatorMeta = manipulatorMap[taskConfig.operator]
      const description = manipulatorMeta?.description ?? taskConfig.operator
      // "버튼 텍스트 (도움말)" 패턴에서 짧은 라벨 추출
      const labelMatch = description.match(/^(.+?)\s*\((.+)\)\s*$/)
      const label = labelMatch ? labelMatch[1] : description

      const operatorData: OperatorNodeData = {
        type: 'operator',
        operator: taskConfig.operator,
        category: manipulatorMeta?.category ?? 'UNKNOWN',
        label,
        params: { ...taskConfig.params },
        paramsSchema: (manipulatorMeta?.params_schema as Record<string, unknown>) ?? null,
      }
      nodeDataMap[nodeId] = operatorData
      nodes.push({
        id: nodeId,
        type: 'operator',
        position: { x: 0, y: 0 },
        data: operatorData as PipelineNode['data'],
      })
    }
  }

  // ── 3. SaveNode 생성 ──
  const saveNodeId = `save_${Date.now()}`
  const saveData: SaveNodeData = {
    type: 'save',
    name: config.name,
    description: config.description ?? '',
    datasetType: config.output.dataset_type as SaveNodeData['datasetType'],
    annotationFormat: config.output.annotation_format,
    split: config.output.split as SaveNodeData['split'],
  }
  nodeDataMap[saveNodeId] = saveData
  nodes.push({
    id: saveNodeId,
    type: 'save',
    position: { x: 0, y: 0 },
    data: saveData as PipelineNode['data'],
  })

  // ── 4. 엣지 생성 ──
  let edgeCounter = 0
  const makeEdgeId = () => `edge_restore_${++edgeCounter}`

  for (const [taskKey, taskConfig] of Object.entries(config.tasks)) {
    const targetNodeId = taskKeyToNodeId.get(taskKey)!

    for (const input of taskConfig.inputs) {
      let sourceNodeId: string | undefined

      if (input.startsWith('source:')) {
        // DataLoadNode → task 연결
        const datasetId = input.split(':', 2)[1]
        sourceNodeId = datasetIdToNodeId.get(datasetId)
      } else {
        // 다른 task → task 연결
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

  // SaveNode 연결: DAG의 싱크 노드(다른 task의 input에 참조되지 않는 task)를 찾아서 연결
  const referencedTaskKeys = new Set<string>()
  for (const taskConfig of Object.values(config.tasks)) {
    for (const input of taskConfig.inputs) {
      if (!input.startsWith('source:')) {
        referencedTaskKeys.add(input)
      }
    }
  }
  const sinkTaskKeys = Object.keys(config.tasks).filter(
    (key) => !referencedTaskKeys.has(key),
  )
  for (const sinkKey of sinkTaskKeys) {
    const sourceNodeId = taskKeyToNodeId.get(sinkKey)!
    edges.push({
      id: makeEdgeId(),
      source: sourceNodeId,
      target: saveNodeId,
      animated: true,
    })
  }

  // ── 5. 자동 레이아웃 (topological sort 기반 좌→우 배치) ──
  _applyAutoLayout(nodes, edges)

  return { nodes, edges, nodeDataMap }
}

/**
 * topological sort 기반 좌→우 자동 레이아웃.
 * 같은 depth의 노드를 세로로 나열하고, depth가 증가할수록 오른쪽에 배치한다.
 */
function _applyAutoLayout(nodes: PipelineNode[], edges: PipelineEdge[]): void {
  const HORIZONTAL_GAP = 320  // depth 간 가로 간격
  const VERTICAL_GAP = 160    // 같은 depth 내 세로 간격
  const START_X = 60
  const START_Y = 80

  // 노드별 depth 계산 (longest path from root)
  const nodeIdSet = new Set(nodes.map((n) => n.id))
  const inEdges = new Map<string, string[]>()   // target → source[]
  const outEdges = new Map<string, string[]>()   // source → target[]
  const inDegree = new Map<string, number>()

  for (const nodeId of nodeIdSet) {
    inEdges.set(nodeId, [])
    outEdges.set(nodeId, [])
    inDegree.set(nodeId, 0)
  }

  for (const edge of edges) {
    if (nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target)) {
      outEdges.get(edge.source)!.push(edge.target)
      inEdges.get(edge.target)!.push(edge.source)
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1)
    }
  }

  // BFS로 longest-path depth 계산
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
      if (newDepth > (depth.get(neighbor) ?? 0)) {
        depth.set(neighbor, newDepth)
      }
      const newInDeg = (inDegree.get(neighbor) ?? 1) - 1
      inDegree.set(neighbor, newInDeg)
      if (newInDeg === 0) {
        queue.push(neighbor)
      }
    }
  }

  // depth가 설정되지 않은 노드(고립 노드)는 depth 0
  for (const node of nodes) {
    if (!depth.has(node.id)) {
      depth.set(node.id, 0)
    }
  }

  // depth별 노드 그룹핑
  const depthGroups = new Map<number, PipelineNode[]>()
  for (const node of nodes) {
    const d = depth.get(node.id)!
    if (!depthGroups.has(d)) depthGroups.set(d, [])
    depthGroups.get(d)!.push(node)
  }

  // 배치 — depth가 큰(오른쪽) 노드부터 배치할 필요 없이, 단순히 depth * gap
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
