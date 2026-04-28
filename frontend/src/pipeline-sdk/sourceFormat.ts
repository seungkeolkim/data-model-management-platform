/**
 * v3 source 토큰 처리 (v7.11 — feature/pipeline-family-and-version).
 *
 * 토큰 형식:
 *   - `source:dataset_split:<split_id>`     — 사용자 spec (Pipeline.config 측)
 *   - `source:dataset_version:<version_id>` — resolved 스냅샷 (PipelineRun.transform_config 측)
 *   - `task_<node_id>`                      — task 간 참조 (변경 없음)
 *
 * 백엔드 `lib/pipeline/config.py` 의 `parse_source_ref` 와 1:1 대응.
 */

export const SOURCE_TYPE_SPLIT = 'dataset_split' as const
export const SOURCE_TYPE_VERSION = 'dataset_version' as const

export type SourceType = typeof SOURCE_TYPE_SPLIT | typeof SOURCE_TYPE_VERSION

export interface ParsedSourceRef {
  type: SourceType
  id: string
}

/**
 * v3 source 토큰 파싱. source 가 아니면 null. 형식이 잘못되면 throw.
 */
export function parseSourceRef(ref: string): ParsedSourceRef | null {
  if (typeof ref !== 'string' || !ref.startsWith('source:')) return null
  const parts = ref.split(':')
  if (parts.length !== 3) {
    throw new Error(
      `source 토큰이 v3 포맷이 아닙니다 — "source:<type>:<id>" 형식이 필요: ${ref}`,
    )
  }
  const [, type, id] = parts
  if (type !== SOURCE_TYPE_SPLIT && type !== SOURCE_TYPE_VERSION) {
    throw new Error(`source 토큰 type 이 잘못됨: ${type}. 유효: ${SOURCE_TYPE_SPLIT} | ${SOURCE_TYPE_VERSION}`)
  }
  if (!id) throw new Error(`source 토큰 id 가 비어있음: ${ref}`)
  return { type, id }
}

/** spec 단계 split 토큰 빌더. */
export function buildSplitSourceRef(splitId: string): string {
  return `source:${SOURCE_TYPE_SPLIT}:${splitId}`
}

/** resolved 단계 version 토큰 빌더 (executor 호환). */
export function buildVersionSourceRef(versionId: string): string {
  return `source:${SOURCE_TYPE_VERSION}:${versionId}`
}

/** ref 가 source 토큰이면 id 반환, 아니면 null. type 무관 (편의용). */
export function getSourceIdAny(ref: string): string | null {
  const parsed = parseSourceRef(ref)
  return parsed ? parsed.id : null
}
