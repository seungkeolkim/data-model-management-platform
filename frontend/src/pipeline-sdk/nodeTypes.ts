/**
 * React Flow `nodeTypes` prop 생성.
 *
 * registry의 모든 definition을 돌면서 `{ kind: NodeComponent }` 맵을 만든다.
 * 새 특수 노드 추가 시 이 파일을 수정할 필요 없다.
 */
import type { NodeTypes } from '@xyflow/react'
import { getAllNodeDefinitions } from './registry'

export function buildNodeTypesFromRegistry(): NodeTypes {
  const map: NodeTypes = {}
  for (const definition of getAllNodeDefinitions()) {
    map[definition.kind] = definition.NodeComponent
  }
  return map
}
