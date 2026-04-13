/**
 * SDK 부팅 — 모든 NodeDefinition을 registry에 등록하고 무결성 검사.
 *
 * 앱 진입점에서 1회 import되면 side-effect으로 등록이 완료된다.
 * registry 키 집합 ↔ NodeDataByKind 키 집합 불일치는 즉시 throw.
 */
import { registerNodeDefinition, assertRegistryCompleteness } from './registry'
import { dataLoadDefinition } from './definitions/dataLoadDefinition'
import { operatorDefinition } from './definitions/operatorDefinition'
import { mergeDefinition } from './definitions/mergeDefinition'
import { saveDefinition } from './definitions/saveDefinition'
import { placeholderDefinition } from './definitions/placeholderDefinition'

registerNodeDefinition(dataLoadDefinition)
registerNodeDefinition(operatorDefinition)
registerNodeDefinition(mergeDefinition)
registerNodeDefinition(saveDefinition)
registerNodeDefinition(placeholderDefinition)

assertRegistryCompleteness()
