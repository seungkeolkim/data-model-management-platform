/**
 * 그래프 → PipelineConfig 변환.
 *
 * 각 NodeDefinition의 `toConfigContribution`을 수집하여 병합한다.
 * 노드 타입별 분기 없이 registry 순회로 처리된다.
 */
import type { Edge } from '@xyflow/react'
import type { PipelineConfig } from '@/types/pipeline'
import { getNodeDefinition } from '../registry'
import type { AnyNodeData, NodeKind } from '../types'
import type { PipelineNode } from '@/types/pipeline'

/** 현재 SDK가 생성하는 PipelineConfig의 schema_version */
export const CURRENT_SCHEMA_VERSION = 1

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
  // 이 경우 Save 노드가 passthrough_source_dataset_id 를 root 에 기여해야 한다.
  if (Object.keys(tasks).length === 0 && !rootParts.passthrough_source_dataset_id) {
    throw new Error('DataLoad 노드와 Save 노드를 직접 연결하거나 처리 노드를 추가해 주세요.')
  }

  return {
    name: rootParts.name,
    description: rootParts.description,
    output: rootParts.output,
    tasks,
    passthrough_source_dataset_id: rootParts.passthrough_source_dataset_id ?? null,
    // schema_version은 백엔드 Pydantic 모델에도 선언되어 있으면 그대로 전달된다.
    schema_version: CURRENT_SCHEMA_VERSION,
  } as PipelineConfig
}
