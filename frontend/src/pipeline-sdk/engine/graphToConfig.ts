/**
 * 그래프 → PipelineConfig 변환.
 *
 * 각 NodeDefinition의 `toConfigContribution`을 수집하여 병합한다.
 * 노드 타입별 분기 없이 registry 순회로 처리된다.
 */
import type { Edge } from '@xyflow/react'
import type { PipelineConfig, PartialPipelineConfig } from '@/types/pipeline'
import { getNodeDefinition } from '../registry'
import type { AnyNodeData, NodeKind } from '../types'
import type { PipelineNode } from '@/types/pipeline'

/**
 * 현재 SDK 가 생성하는 PipelineConfig 의 schema_version.
 * v7.10 (핸드오프 027 §4-2) — 2 로 승격: source 참조가 dataset_version_id 에서
 * split_id 로 격상됨. v1 config 은 legacy (placeholder 로 복원, 재실행 차단).
 */
export const CURRENT_SCHEMA_VERSION = 2

export function graphToPipelineConfig(
  nodes: PipelineNode[],
  edges: Edge[],
  nodeDataMap: Record<string, AnyNodeData>,
): PipelineConfig {
  const getNodeData = (id: string) => nodeDataMap[id]

  const tasks: PipelineConfig['tasks'] = {}
  let rootParts: Partial<PipelineConfig> = {}

  for (const node of nodes) {
    const data = nodeDataMap[node.id]
    if (!data) continue
    const definition = getNodeDefinition(data.type as NodeKind)
    if (!definition?.toConfigContribution) continue

    const contribution = definition.toConfigContribution(
      // 타입 단순화를 위한 any 허용 — SDK 내부에서만 통과
      data as never,
      {
        nodeId: node.id,
        incomingEdges: edges.filter((e) => e.target === node.id),
        getNodeData,
      },
    )
    if (!contribution) continue
    if (contribution.tasks) {
      Object.assign(tasks, contribution.tasks)
    }
    if (contribution.root) {
      rootParts = { ...rootParts, ...contribution.root }
    }
  }

  if (!rootParts.name || !rootParts.output) {
    throw new Error('Save 노드가 없습니다.')
  }
  // tasks 가 비어있어도 허용 — Load→Save 직결(passthrough) 모드.
  // v7.10: Save 노드가 passthrough_source_split_id 를 root 에 기여.
  const rootWithPassthrough = rootParts as Partial<PipelineConfig> & {
    passthrough_source_split_id?: string | null
  }
  if (Object.keys(tasks).length === 0 && !rootWithPassthrough.passthrough_source_split_id) {
    throw new Error('DataLoad 노드와 Save 노드를 직접 연결하거나 처리 노드를 추가해 주세요.')
  }
  // task 의 inputs 가 비어있으면 그래프에서 입력 엣지가 누락된 것 — 사용자에게 명확히 안내.
  // 이 케이스를 backend 가 받으면 Pydantic min_length=1 검증으로 422 가 떨어져 의미가 흐려짐.
  for (const [taskKey, taskValue] of Object.entries(tasks)) {
    if (!taskValue.inputs || taskValue.inputs.length === 0) {
      throw new Error(
        `노드 '${taskKey}' 에 입력 연결이 없습니다. ` +
        `DataLoad 노드 또는 다른 처리 노드와 연결해 주세요.`,
      )
    }
  }

  return {
    name: rootParts.name,
    description: rootParts.description,
    output: rootParts.output,
    tasks,
    // v7.10: v1 호환 필드는 null 로 명시 (백엔드가 v2 를 우선 해석)
    passthrough_source_dataset_id: null,
    passthrough_source_split_id: rootWithPassthrough.passthrough_source_split_id ?? null,
    schema_version: CURRENT_SCHEMA_VERSION,
  } as PipelineConfig
}


/**
 * Save 노드 없이도 동작하는 부분 config 생성.
 *
 * DataLoad 노드들로부터 forward BFS 로 도달 가능한 노드만 수집하고,
 * Save 가 없으면 name/output 을 placeholder 로 채운다.
 * JSON 프리뷰, schema preview 등 "실행 전 미리보기" 에서 사용.
 */
export function graphToPartialPipelineConfig(
  nodes: PipelineNode[],
  edges: Edge[],
  nodeDataMap: Record<string, AnyNodeData>,
): PartialPipelineConfig {
  // 1) forward 인접 리스트 (source → target)
  const forwardAdj = new Map<string, string[]>()
  for (const edge of edges) {
    const targets = forwardAdj.get(edge.source)
    if (targets) {
      targets.push(edge.target)
    } else {
      forwardAdj.set(edge.source, [edge.target])
    }
  }

  // 2) DataLoad 노드들에서 BFS — 도달 가능한 nodeId 집합
  const reachableNodeIds = new Set<string>()
  const bfsQueue: string[] = []
  for (const node of nodes) {
    const data = nodeDataMap[node.id]
    if (data?.type === 'dataLoad') {
      reachableNodeIds.add(node.id)
      bfsQueue.push(node.id)
    }
  }
  while (bfsQueue.length > 0) {
    const currentId = bfsQueue.shift()!
    for (const neighborId of forwardAdj.get(currentId) ?? []) {
      if (!reachableNodeIds.has(neighborId)) {
        reachableNodeIds.add(neighborId)
        bfsQueue.push(neighborId)
      }
    }
  }

  // 3) reachable 노드만 contribution 수집
  const getNodeData = (id: string) => nodeDataMap[id]
  const tasks: PartialPipelineConfig['tasks'] = {}
  let rootParts: Partial<PipelineConfig> = {}

  for (const node of nodes) {
    if (!reachableNodeIds.has(node.id)) continue
    const data = nodeDataMap[node.id]
    if (!data) continue
    const definition = getNodeDefinition(data.type as NodeKind)
    if (!definition?.toConfigContribution) continue

    const contribution = definition.toConfigContribution(
      data as never,
      {
        nodeId: node.id,
        incomingEdges: edges.filter((e) => e.target === node.id),
        getNodeData,
      },
    )
    if (!contribution) continue
    if (contribution.tasks) {
      Object.assign(tasks, contribution.tasks)
    }
    if (contribution.root) {
      rootParts = { ...rootParts, ...contribution.root }
    }
  }

  const rootPartial = rootParts as Partial<PipelineConfig> & {
    passthrough_source_split_id?: string | null
  }
  return {
    name: rootParts.name ?? '<draft>',
    description: rootParts.description,
    output: rootParts.output ?? null,
    tasks,
    passthrough_source_dataset_id: null,
    passthrough_source_split_id: rootPartial.passthrough_source_split_id ?? null,
    schema_version: CURRENT_SCHEMA_VERSION,
  } as PartialPipelineConfig
}
