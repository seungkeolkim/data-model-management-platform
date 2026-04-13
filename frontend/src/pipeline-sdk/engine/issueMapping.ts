/**
 * 서버 검증 결과의 issue.field를 각 노드에 매핑.
 *
 * registry 순회 + definition.matchIssueField() 호출로 노드별 validationIssues 갱신.
 */
import type { PipelineValidationIssue } from '@/types/pipeline'
import { getNodeDefinition } from '../registry'
import type { AnyNodeData, NodeKind } from '../types'

export function distributeIssuesToNodes(
  nodeDataMap: Record<string, AnyNodeData>,
  issues: PipelineValidationIssue[],
): Record<string, AnyNodeData> {
  // 먼저 모든 노드의 validationIssues를 초기화
  const updated: Record<string, AnyNodeData> = {}
  for (const [nodeId, data] of Object.entries(nodeDataMap)) {
    updated[nodeId] = { ...data, validationIssues: [] }
  }

  for (const issue of issues) {
    for (const [nodeId, data] of Object.entries(updated)) {
      const definition = getNodeDefinition(data.type as NodeKind)
      if (!definition?.matchIssueField) continue
      const matched = definition.matchIssueField(issue, data as never, nodeId)
      if (!matched) continue
      const existing = data.validationIssues ?? []
      updated[nodeId] = { ...data, validationIssues: [...existing, issue] }
    }
  }

  return updated
}
