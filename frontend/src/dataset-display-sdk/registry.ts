/**
 * Dataset Display SDK 중앙 registry.
 *
 * pipeline-sdk/registry.ts 와 동일 패턴. bootstrap.ts 에서 definition들을 등록하고
 * assertRegistryCompleteness로 DatasetKind 집합과 일치 여부를 부팅 시 검증한다.
 */
import type { DatasetGroup } from '../types/dataset'
import type { DatasetKind, DatasetKindDefinition } from './types'

type DefinitionsRegistry = Partial<Record<DatasetKind, DatasetKindDefinition>>

const registry: DefinitionsRegistry = {}

export function registerDatasetKindDefinition(definition: DatasetKindDefinition): void {
  if (registry[definition.kind]) {
    throw new Error(`DatasetKindDefinition 중복 등록: ${definition.kind}`)
  }
  registry[definition.kind] = definition
}

export function getDatasetKindDefinition(kind: DatasetKind): DatasetKindDefinition | undefined {
  return registry[kind]
}

export function getAllDatasetKindDefinitions(): DatasetKindDefinition[] {
  return Object.values(registry).filter((definition): definition is DatasetKindDefinition => !!definition)
}

/**
 * 그룹을 실제 kind로 해석. 여러 definition이 matches=true로 판정하면
 * 등록 순서를 따른다(classification을 먼저 등록해 CLS_MANIFEST가 detection으로 잘못 잡히는 것을 막는다).
 * 어떤 kind와도 매칭되지 않으면 fallback으로 detection을 반환 — 현 시점 detection이 사실상 기본값이기 때문.
 */
export function resolveDatasetKind(group: DatasetGroup): DatasetKindDefinition {
  for (const definition of getAllDatasetKindDefinitions()) {
    if (definition.matches(group)) return definition
  }
  const detection = registry['detection']
  if (!detection) {
    throw new Error('detection definition이 등록되어 있지 않습니다. bootstrap.ts를 확인하세요.')
  }
  return detection
}

/** 등록된 kind 집합이 예상과 일치하는지 검증. 새 kind 추가 시 expected 배열도 갱신. */
export function assertDatasetKindRegistryCompleteness(): void {
  const expected: DatasetKind[] = ['detection', 'classification']
  const actual = Object.keys(registry) as DatasetKind[]

  const missing = expected.filter((k) => !actual.includes(k))
  const extra = actual.filter((k) => !expected.includes(k))

  if (missing.length > 0 || extra.length > 0) {
    throw new Error(
      `DatasetKindDefinition registry 불일치. ` +
      `missing=${JSON.stringify(missing)}, extra=${JSON.stringify(extra)}. ` +
      `dataset-display-sdk/bootstrap.ts의 등록 호출을 확인하세요.`,
    )
  }
}

export function _resetDatasetKindRegistryForTest(): void {
  for (const key of Object.keys(registry)) {
    delete registry[key as DatasetKind]
  }
}
