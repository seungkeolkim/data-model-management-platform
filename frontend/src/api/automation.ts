/**
 * Automation API — 목업 비동기 wrapper (v7.13 baseline 자료구조).
 *
 * 페이지 / 컴포넌트는 항상 이 파일의 함수를 호출한다. 내부 fixture 가 5엔티티 (Family / concept /
 * version / automation / run) 로 분리됐으므로 wrapper 도 그 단위로 분할됐다 — 추후 실 백엔드가 붙을 때
 * 이 파일만 교체하면 호출부를 건드리지 않는다.
 *
 * 비동기로 감싸는 이유: 실 API 는 반드시 Promise. React Query / useEffect 호출부가 목업에서도 같은
 * 형태로 동작하도록 한다. 50~150ms 의 랜덤 지연으로 실제 네트워크 흉내.
 *
 * 변경 가능한 in-memory 세션 스토어:
 *   - sessionConcepts / sessionVersions / sessionAutomations 3종.
 *   - description 편집 / automation 설정 토글 등은 이 스토어에 반영돼 페이지 이동 후에도 유지.
 *   - 새로고침하면 원본 fixture 로 초기화 (의도된 동작 — 실 API 전환 시 사라짐).
 */
import type {
  AutomationReassignHint,
  AutomationTriggerSource,
  AutomationUpdate,
  ChainingGraph,
  ExecutionBatch,
  PipelineAutomation,
  PipelineConcept,
  PipelineFamily,
  PipelineRun,
  PipelineRunStatus,
  PipelineVersion,
  TriggerKind,
  UpstreamSplitDelta,
} from '@/types/automation'
import {
  MOCK_AUTOMATIONS,
  MOCK_CHAINING_GRAPH,
  MOCK_CONCEPTS,
  MOCK_EXECUTION_BATCHES,
  MOCK_FAMILIES,
  MOCK_RUNS,
  MOCK_UPSTREAM_DELTAS,
  MOCK_VERSIONS,
} from '@/mocks/automation'

// =============================================================================
// 내부 유틸
// =============================================================================

/** 50~150ms 사이 랜덤 지연. 목업이지만 실제 로딩 UX 를 흉내. */
function simulatedDelay(): Promise<void> {
  const ms = 50 + Math.floor(Math.random() * 100)
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** deep clone — 호출 측에서 결과를 mutate 해도 fixture 상수가 오염되지 않게 한다. */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

// =============================================================================
// 변경 가능한 in-memory 세션 스토어
// =============================================================================

let sessionFamilies: PipelineFamily[] = clone(MOCK_FAMILIES)
let sessionConcepts: PipelineConcept[] = clone(MOCK_CONCEPTS)
let sessionAutomations: PipelineAutomation[] = clone(MOCK_AUTOMATIONS)
/**
 * Versions 는 automation 임베드 필드를 가지므로 자동화 설정 변경 시 함께 동기화돼야 한다.
 * 내부 헬퍼 `syncAutomationOnVersion()` 가 이를 담당한다.
 */
let sessionVersions: PipelineVersion[] = clone(MOCK_VERSIONS)

/**
 * sessionAutomations 의 한 entry 와 sessionVersions 의 임베드 automation 을 동기화.
 * automation 변경 후 호출하면 같은 version 의 임베드 필드도 갱신된다.
 */
function syncAutomationOnVersion(versionId: string): void {
  const versionIndex = sessionVersions.findIndex((v) => v.id === versionId)
  if (versionIndex < 0) return
  const automation = sessionAutomations.find(
    (a) => a.pipeline_version_id === versionId && a.is_active,
  )
  sessionVersions[versionIndex] = {
    ...sessionVersions[versionIndex],
    automation: automation ? { ...automation } : null,
  }
}

// =============================================================================
// 조회 — PipelineFamily
// =============================================================================

export async function listFamilies(): Promise<PipelineFamily[]> {
  await simulatedDelay()
  return clone(sessionFamilies)
}

// =============================================================================
// 조회 — Pipeline (concept)
// =============================================================================

export interface ListConceptsFilters {
  /** 복수 family ID. 비어있거나 undefined 면 family 필터 미적용. */
  family_id?: string[]
  /** family_id 가 NULL (= 미분류) 인 concept 도 포함할지. 기본값 true. */
  include_unfiled?: boolean
  /** 비활성(soft delete) 포함 여부. 기본 false. */
  include_inactive?: boolean
}

export async function listConcepts(
  filters?: ListConceptsFilters,
): Promise<PipelineConcept[]> {
  await simulatedDelay()
  const includeUnfiled = filters?.include_unfiled ?? true
  const includeInactive = filters?.include_inactive ?? false
  const items = sessionConcepts.filter((concept) => {
    if (!includeInactive && !concept.is_active) return false
    const familyFilterActive = (filters?.family_id?.length ?? 0) > 0
    if (!familyFilterActive) return true
    if (concept.family_id === null) {
      return includeUnfiled
    }
    return filters!.family_id!.includes(concept.family_id)
  })
  return clone(items)
}

export async function getConcept(conceptId: string): Promise<PipelineConcept | null> {
  await simulatedDelay()
  const found = sessionConcepts.find((c) => c.id === conceptId)
  return found ? clone(found) : null
}

/**
 * Description 업데이트 mock. 실 API 로는 `PATCH /pipelines/{id}` 매핑.
 * concept 의 description 만 갱신. 같은 concept 의 모든 version 표시명에는 영향 없음.
 */
export async function updateConceptDescription(
  conceptId: string,
  description: string,
): Promise<PipelineConcept> {
  await simulatedDelay()
  const index = sessionConcepts.findIndex((c) => c.id === conceptId)
  if (index < 0) {
    throw new Error(`Concept not found: ${conceptId}`)
  }
  const next: PipelineConcept = {
    ...sessionConcepts[index],
    description: description.trim() === '' ? null : description,
    updated_at: new Date().toISOString(),
  }
  sessionConcepts[index] = next
  return clone(next)
}

// =============================================================================
// 조회 — PipelineVersion
// =============================================================================

/**
 * 특정 concept 의 version 목록. 최신 → 과거 순으로 정렬.
 * 비활성 version 포함 여부는 includeInactive 로 제어 (기본 false).
 */
export async function listVersions(
  conceptId: string,
  options?: { include_inactive?: boolean },
): Promise<PipelineVersion[]> {
  await simulatedDelay()
  const includeInactive = options?.include_inactive ?? false
  const items = sessionVersions
    .filter((v) => v.pipeline_id === conceptId)
    .filter((v) => includeInactive || v.is_active)
    .sort((a, b) => {
      // version 문자열 ("2.0" 등) 을 major 기준 desc 정렬. minor 동률 시 created_at desc.
      const aMajor = parseInt(a.version.split('.')[0] ?? '0', 10)
      const bMajor = parseInt(b.version.split('.')[0] ?? '0', 10)
      if (aMajor !== bMajor) return bMajor - aMajor
      return b.created_at.localeCompare(a.created_at)
    })
  return clone(items)
}

export async function getVersion(versionId: string): Promise<PipelineVersion | null> {
  await simulatedDelay()
  const found = sessionVersions.find((v) => v.id === versionId)
  return found ? clone(found) : null
}

/**
 * 같은 concept 안에서 active automation 이 다른 version 에 붙어있다면 hint 반환.
 * 027 §12-6 의 "노티만 띄움, 자동 reassign 안 함" 정책에 쓰인다.
 *
 * 본인 version 에 automation 이 이미 붙어있거나, 같은 concept 의 어느 version 에도 active automation
 * 이 없으면 null 반환.
 */
export async function getReassignHint(
  versionId: string,
): Promise<AutomationReassignHint | null> {
  await simulatedDelay()
  const target = sessionVersions.find((v) => v.id === versionId)
  if (!target) return null
  // 본인 version 에 이미 active automation 이 있으면 hint 불요.
  if (target.automation && target.automation.is_active) return null
  // 같은 concept 의 다른 version 중 active automation 보유한 것 찾기.
  const conceptVersions = sessionVersions.filter(
    (v) => v.pipeline_id === target.pipeline_id && v.id !== target.id,
  )
  const automationVersion = conceptVersions.find(
    (v) => v.automation && v.automation.is_active,
  )
  if (!automationVersion || !automationVersion.automation) return null
  return {
    pipeline_id: target.pipeline_id,
    current_version_id: target.id,
    current_version: target.version,
    active_on_version_id: automationVersion.id,
    active_on_version: automationVersion.version,
    automation_id: automationVersion.automation.id,
  }
}

// =============================================================================
// 조회 — PipelineAutomation
// =============================================================================

/** active 한 automation 전체. 사이드 페이지 등에서 "지금 자동화 등록된 것" 한 번에 조회용. */
export async function listAutomations(): Promise<PipelineAutomation[]> {
  await simulatedDelay()
  const items = sessionAutomations.filter((a) => a.is_active)
  return clone(items)
}

export async function getAutomation(automationId: string): Promise<PipelineAutomation | null> {
  await simulatedDelay()
  const found = sessionAutomations.find((a) => a.id === automationId)
  return found ? clone(found) : null
}

// =============================================================================
// 변이 — Automation 설정 업데이트
// =============================================================================

/**
 * automationId 로 직접 가리키는 automation 의 status / mode / poll_interval 을 갱신.
 * stopped 로 내려가면 mode / interval 자동 초기화. error 상태에서 stopped/active 로 복귀하면
 * error_reason 도 초기화 (목업 정책).
 */
export async function updateAutomation(
  automationId: string,
  update: AutomationUpdate,
): Promise<PipelineAutomation> {
  await simulatedDelay()
  const index = sessionAutomations.findIndex((a) => a.id === automationId)
  if (index < 0) {
    throw new Error(`Automation not found: ${automationId}`)
  }
  const current = sessionAutomations[index]
  const next: PipelineAutomation = {
    ...current,
    status: update.status ?? current.status,
    mode: update.mode !== undefined ? update.mode : current.mode,
    poll_interval:
      update.poll_interval !== undefined ? update.poll_interval : current.poll_interval,
    updated_at: new Date().toISOString(),
  }
  if (next.status !== 'error') {
    next.error_reason = null
  }
  if (next.status === 'stopped') {
    next.mode = null
    next.poll_interval = null
    next.next_scheduled_at = null
  }
  sessionAutomations[index] = next
  syncAutomationOnVersion(next.pipeline_version_id)
  return clone(next)
}

/**
 * 새 automation 을 특정 version 에 등록 (목업).
 * 같은 version 에 이미 active automation 이 있으면 ValueError 류 에러.
 * 027 §12-3 partial unique active 와 같은 제약을 mock 에서 강제.
 */
export async function createAutomationForVersion(
  versionId: string,
  init: AutomationUpdate & { mode: 'polling' | 'triggering' },
): Promise<PipelineAutomation> {
  await simulatedDelay()
  const version = sessionVersions.find((v) => v.id === versionId)
  if (!version) {
    throw new Error(`Version not found: ${versionId}`)
  }
  const existing = sessionAutomations.find(
    (a) => a.pipeline_version_id === versionId && a.is_active,
  )
  if (existing) {
    throw new Error(
      `이미 이 version 에 활성 automation 이 등록돼 있습니다: ${existing.id}`,
    )
  }
  const now = new Date().toISOString()
  const next: PipelineAutomation = {
    id: `a-mock-${Math.random().toString(36).slice(2, 10)}`,
    pipeline_version_id: versionId,
    status: init.status ?? 'stopped',
    mode: init.mode,
    poll_interval: init.poll_interval ?? null,
    error_reason: null,
    last_seen_input_versions: {},
    is_active: true,
    deleted_at: null,
    next_scheduled_at: null,
    last_dispatched_at: null,
    created_at: now,
    updated_at: now,
  }
  sessionAutomations = [...sessionAutomations, next]
  syncAutomationOnVersion(versionId)
  return clone(next)
}

/**
 * Automation reassign — 027 §6-4 (a). active automation 을 같은 concept 의 다른 version 으로 이동.
 * 검증: 새 version 에 이미 active automation 이 있으면 거부.
 */
export async function reassignAutomation(
  automationId: string,
  newVersionId: string,
): Promise<PipelineAutomation> {
  await simulatedDelay()
  const index = sessionAutomations.findIndex((a) => a.id === automationId)
  if (index < 0) {
    throw new Error(`Automation not found: ${automationId}`)
  }
  const current = sessionAutomations[index]
  const newVersion = sessionVersions.find((v) => v.id === newVersionId)
  if (!newVersion) {
    throw new Error(`Version not found: ${newVersionId}`)
  }
  // 새 version 에 이미 active automation 있으면 거부.
  const conflict = sessionAutomations.find(
    (a) => a.pipeline_version_id === newVersionId && a.is_active && a.id !== automationId,
  )
  if (conflict) {
    throw new Error(
      `대상 version 에 이미 활성 automation 이 있습니다: ${conflict.id}`,
    )
  }
  // 같은 concept 안에서만 이동 허용 (실 baseline 제약과 동일).
  const oldVersion = sessionVersions.find((v) => v.id === current.pipeline_version_id)
  if (oldVersion && oldVersion.pipeline_id !== newVersion.pipeline_id) {
    throw new Error('같은 Pipeline (concept) 안에서만 reassign 할 수 있습니다.')
  }
  const previousVersionId = current.pipeline_version_id
  const next: PipelineAutomation = {
    ...current,
    pipeline_version_id: newVersionId,
    updated_at: new Date().toISOString(),
  }
  sessionAutomations[index] = next
  syncAutomationOnVersion(previousVersionId)
  syncAutomationOnVersion(newVersionId)
  return clone(next)
}

/**
 * Automation soft delete (027 §12-3). is_active=false / deleted_at=now.
 * row 는 보존 — 과거 PipelineRun.automation_id 참조를 깨뜨리지 않기 위해.
 */
export async function deleteAutomation(automationId: string): Promise<void> {
  await simulatedDelay()
  const index = sessionAutomations.findIndex((a) => a.id === automationId)
  if (index < 0) {
    throw new Error(`Automation not found: ${automationId}`)
  }
  const now = new Date().toISOString()
  const next: PipelineAutomation = {
    ...sessionAutomations[index],
    is_active: false,
    deleted_at: now,
    updated_at: now,
  }
  sessionAutomations[index] = next
  syncAutomationOnVersion(next.pipeline_version_id)
}

// =============================================================================
// 변이 — 수동 재실행
// =============================================================================

export type ManualRerunMode = 'if_delta' | 'force_latest'

export interface ManualRerunResult {
  /** true 면 "실행 dispatch 됨" — 토스트 문구 분기에 사용 */
  dispatched: boolean
  /** 사용자에게 보여줄 메시지 */
  message: string
}

/**
 * 수동 재실행 mock. 실 Celery dispatch 는 일어나지 않는다.
 *   - if_delta     : 상류 delta 가 있으면 dispatched=true, 없으면 false (no-delta skip)
 *   - force_latest : 항상 dispatched=true
 *
 * delta 여부는 MOCK_UPSTREAM_DELTAS (version 단위) 를 참조.
 */
export async function rerunAutomationManually(
  versionId: string,
  mode: ManualRerunMode,
): Promise<ManualRerunResult> {
  await simulatedDelay()
  if (mode === 'force_latest') {
    return {
      dispatched: true,
      message: '강제 최신 재실행이 dispatch 됐습니다. 실행 이력에서 확인하세요.',
    }
  }
  const deltas = MOCK_UPSTREAM_DELTAS[versionId] ?? []
  const hasDelta = deltas.some((delta) => delta.has_delta)
  if (hasDelta) {
    return {
      dispatched: true,
      message: '변경사항이 감지돼 실행이 dispatch 됐습니다.',
    }
  }
  return {
    dispatched: false,
    message: '변경사항이 없어 재실행되지 않았습니다 (no-delta skip).',
  }
}

// =============================================================================
// 조회 — Chaining DAG
// =============================================================================

/**
 * Chaining DAG 는 fixture 상수에 미리 빌드돼 있지만, automation status 가 세션 동안 토글될 수 있으므로
 * 호출 시점의 sessionVersions 로부터 status / error_reason 을 다시 join 해서 반환한다.
 */
export async function getChainingGraph(): Promise<ChainingGraph> {
  await simulatedDelay()
  const overlay = new Map(
    sessionVersions.map((v) => [v.id, v.automation] as const),
  )
  const nodes = MOCK_CHAINING_GRAPH.nodes.map((node) => {
    const automation = overlay.get(node.pipeline_version_id)
    return {
      ...node,
      automation_status: automation?.status ?? 'stopped',
      automation_error_reason: automation?.error_reason ?? null,
    }
  })
  return clone({
    nodes,
    edges: MOCK_CHAINING_GRAPH.edges,
    cycles: MOCK_CHAINING_GRAPH.cycles,
  })
}

// =============================================================================
// 조회 — PipelineRun
// =============================================================================

export interface ListRunsFilters {
  /** 복수 선택 가능. 비어있으면 전체. */
  trigger_kind?: TriggerKind[]
  automation_trigger_source?: AutomationTriggerSource[]
  /** version 단위 필터. 같은 concept 의 모든 version 에 걸친 필터를 원하면 listRunsByConcept 사용. */
  pipeline_version_id?: string
  status?: PipelineRunStatus[]
}

export async function listRuns(filters?: ListRunsFilters): Promise<PipelineRun[]> {
  await simulatedDelay()
  const items = MOCK_RUNS.filter((run) => {
    if (filters?.trigger_kind?.length && !filters.trigger_kind.includes(run.trigger_kind)) {
      return false
    }
    if (
      filters?.automation_trigger_source?.length &&
      (run.automation_trigger_source === null ||
        !filters.automation_trigger_source.includes(run.automation_trigger_source))
    ) {
      return false
    }
    if (
      filters?.pipeline_version_id &&
      run.pipeline_version_id !== filters.pipeline_version_id
    ) {
      return false
    }
    if (filters?.status?.length && !filters.status.includes(run.status)) return false
    return true
  })
  return clone(items)
}

/**
 * 특정 concept 에 속한 모든 version 의 run 을 모아 반환. 상세 페이지 "이 파이프라인 누적 실행" 에 쓰임.
 */
export async function listRunsByConcept(conceptId: string): Promise<PipelineRun[]> {
  await simulatedDelay()
  const versionIds = new Set(
    sessionVersions.filter((v) => v.pipeline_id === conceptId).map((v) => v.id),
  )
  const items = MOCK_RUNS.filter((run) => versionIds.has(run.pipeline_version_id))
  return clone(items)
}

export async function listExecutionBatches(): Promise<ExecutionBatch[]> {
  await simulatedDelay()
  return clone(MOCK_EXECUTION_BATCHES)
}

// =============================================================================
// 조회 — 상류 DatasetSplit delta
// =============================================================================

export async function getUpstreamDeltas(
  versionId: string,
): Promise<UpstreamSplitDelta[]> {
  await simulatedDelay()
  return clone(MOCK_UPSTREAM_DELTAS[versionId] ?? [])
}

