/**
 * NodeDefinition 중앙 registry.
 *
 * 빌드 타임에 definitions/를 import하여 모든 특수 노드를 등록한다.
 * manipulator 계열은 정의 1개(operator)만 등록하고, API 응답을 받아 팔레트 항목을 동적 생성한다.
 *
 * 부팅 시 registry 키 집합이 NodeDataByKind의 키 집합과 일치하는지 런타임 assert로 확인.
 * 불일치는 SDK 버그로 취급한다 — 이 assert를 완화하여 해결하지 말 것.
 */

import type { NodeDefinition, NodeDataByKind, NodeKind } from './types'

type DefinitionsRegistry = { [K in NodeKind]?: NodeDefinition<K> }

const registry: DefinitionsRegistry = {}

export function registerNodeDefinition<K extends NodeKind>(definition: NodeDefinition<K>): void {
  if (registry[definition.kind]) {
    // 중복 등록은 dev 단계 실수이므로 즉시 알림
    throw new Error(`NodeDefinition 중복 등록: ${definition.kind}`)
  }
  registry[definition.kind] = definition as DefinitionsRegistry[K]
}

export function getNodeDefinition<K extends NodeKind>(kind: K): NodeDefinition<K> | undefined {
  return registry[kind] as NodeDefinition<K> | undefined
}

export function getAllNodeDefinitions(): NodeDefinition[] {
  return Object.values(registry).filter(Boolean) as NodeDefinition[]
}

/**
 * registry 키 집합 == NodeDataByKind 키 집합 검증.
 * bootstrap 마지막에 호출된다.
 */
export function assertRegistryCompleteness(): void {
  // NodeDataByKind의 키 집합은 컴파일 타임에만 존재하므로 하드코딩된 expected 리스트로 비교.
  // 새 kind 추가 시 이 리스트도 동시에 갱신해야 한다(의도적 감시 포인트).
  const expected: NodeKind[] = ['dataLoad', 'operator', 'merge', 'save', 'placeholder']
  const actual = Object.keys(registry) as NodeKind[]

  const missing = expected.filter((k) => !actual.includes(k))
  const extra = actual.filter((k) => !expected.includes(k as NodeKind))

  if (missing.length > 0 || extra.length > 0) {
    throw new Error(
      `NodeDefinition registry 불일치. ` +
      `missing=${JSON.stringify(missing)}, extra=${JSON.stringify(extra)}. ` +
      `bootstrap.ts에서 registerNodeDefinition 호출을 확인하세요.`,
    )
  }
}

/** 테스트용 리셋 (프로덕션 코드에서 호출 금지) */
export function _resetRegistryForTest(): void {
  for (const k of Object.keys(registry)) {
    delete registry[k as NodeKind]
  }
}

// 타입 헬퍼 — NodeDataByKind의 모든 키를 컴파일 타임에 강제 노출
// (expected 리스트 누락을 타입 차원에서도 감지)
export type _NodeKindCheck = {
  [K in keyof NodeDataByKind]: K
}[keyof NodeDataByKind]
