/**
 * Automation API — 목업 비동기 wrapper (023 §9-1 A 안).
 *
 * 페이지 / 컴포넌트는 항상 이 파일의 함수를 호출한다. 내부 구현이 목업 fixture 를 그대로 반환하는
 * 구조라, 추후 실 백엔드가 붙을 때 이 파일만 교체하면 호출부를 건드리지 않아도 된다.
 *
 * 비동기로 감싸 두는 이유: 실 API 는 반드시 Promise 라, React Query / useEffect 호출부가
 * 목업에서도 같은 형태로 동작하도록 한다. 지연은 50~150ms 사이 랜덤으로 주어 UI 로딩 스피너 / skeleton
 * 동작을 실제 환경에 가깝게 확인할 수 있게 한다.
 */
import type {
  Pipeline,
  PipelineAutomationUpdate,
  ChainingGraph,
  PipelineExecutionSummary,
  ExecutionBatch,
  UpstreamGroupDelta,
  TriggerKind,
  AutomationTriggerSource,
} from '@/types/automation'
import {
  MOCK_PIPELINES,
  MOCK_CHAINING_GRAPH,
  MOCK_EXECUTIONS,
  MOCK_EXECUTION_BATCHES,
  MOCK_UPSTREAM_DELTAS,
} from '@/mocks/automation'

// =============================================================================
// 내부 유틸 — 네트워크 지연 흉내
// =============================================================================

function simulatedDelay(): Promise<void> {
  // 50~150ms 사이 랜덤 지연. 목업이지만 실제 로딩 UX 를 대략 흉내낸다.
  const ms = 50 + Math.floor(Math.random() * 100)
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** deep clone — 호출 측에서 결과를 mutate 해도 fixture 상수가 오염되지 않게 한다. */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

// =============================================================================
// 변경 가능한 in-memory 스토어
// =============================================================================
//
// 목업 세션 내에서 "status 토글" 같은 사용자 조작이 즉시 반영돼야 페이지 이동 시 일관되게 보인다.
// MOCK_PIPELINES 상수를 직접 mutate 하지 않고, 복사본을 세션 스토어로 두고 업데이트는 여기에만 반영한다.
// 새로고침하면 원본 상수로 초기화된다 (의도된 동작 — 실 API 전환 시 사라짐).

let sessionPipelines: Pipeline[] = clone(MOCK_PIPELINES)

// =============================================================================
// 조회 — Pipeline
// =============================================================================

export async function listPipelines(): Promise<Pipeline[]> {
  await simulatedDelay()
  return clone(sessionPipelines)
}

export async function getPipeline(pipelineId: string): Promise<Pipeline | null> {
  await simulatedDelay()
  const found = sessionPipelines.find((pipeline) => pipeline.id === pipelineId)
  return found ? clone(found) : null
}

// =============================================================================
// 조회 — Chaining DAG
// =============================================================================

export async function getChainingGraph(): Promise<ChainingGraph> {
  await simulatedDelay()
  // nodes 는 세션 스토어의 최신 상태를 반영해야 상태 토글이 DAG 색상에도 즉시 반영된다.
  return {
    nodes: clone(sessionPipelines),
    edges: clone(MOCK_CHAINING_GRAPH.edges),
    cycles: clone(MOCK_CHAINING_GRAPH.cycles),
  }
}

// =============================================================================
// 조회 — PipelineExecution
// =============================================================================

export interface ExecutionListFilters {
  /** 복수 선택 가능 — 비어있거나 undefined 면 전체. */
  trigger_kind?: TriggerKind[]
  automation_trigger_source?: AutomationTriggerSource[]
  pipeline_id?: string
  status?: PipelineExecutionSummary['status'][]
}

export async function listExecutions(
  filters?: ExecutionListFilters,
): Promise<PipelineExecutionSummary[]> {
  await simulatedDelay()
  const items = MOCK_EXECUTIONS.filter((execution) => {
    if (filters?.trigger_kind?.length && !filters.trigger_kind.includes(execution.trigger_kind)) {
      return false
    }
    if (
      filters?.automation_trigger_source?.length &&
      (execution.automation_trigger_source === null ||
        !filters.automation_trigger_source.includes(execution.automation_trigger_source))
    ) {
      return false
    }
    if (filters?.pipeline_id && execution.pipeline_id !== filters.pipeline_id) return false
    if (filters?.status?.length && !filters.status.includes(execution.status)) return false
    return true
  })
  return clone(items)
}

export async function listExecutionBatches(): Promise<ExecutionBatch[]> {
  await simulatedDelay()
  return clone(MOCK_EXECUTION_BATCHES)
}

// =============================================================================
// 조회 — 상류 DatasetGroup delta
// =============================================================================

export async function getUpstreamDeltas(pipelineId: string): Promise<UpstreamGroupDelta[]> {
  await simulatedDelay()
  return clone(MOCK_UPSTREAM_DELTAS[pipelineId] ?? [])
}

// =============================================================================
// 변이 — Pipeline automation 설정 업데이트
// =============================================================================

/**
 * status / mode / poll_interval 변경을 세션 스토어에 반영하고 업데이트된 Pipeline 을 반환.
 * error 상태에서 stopped / active 로 되돌리는 경우 error_reason 은 초기화한다 (목업 정책).
 */
export async function updatePipelineAutomation(
  pipelineId: string,
  update: PipelineAutomationUpdate,
): Promise<Pipeline> {
  await simulatedDelay()
  const index = sessionPipelines.findIndex((pipeline) => pipeline.id === pipelineId)
  if (index < 0) {
    throw new Error(`Pipeline not found: ${pipelineId}`)
  }
  const current = sessionPipelines[index]
  const next: Pipeline = {
    ...current,
    automation_status: update.status ?? current.automation_status,
    automation_mode: update.mode !== undefined ? update.mode : current.automation_mode,
    automation_poll_interval:
      update.poll_interval !== undefined ? update.poll_interval : current.automation_poll_interval,
    updated_at: new Date().toISOString(),
  }
  // stopped 로 내려가거나 active 로 복귀하면 error_reason 제거.
  if (next.automation_status !== 'error') {
    next.automation_error_reason = null
  }
  // stopped 면 mode / interval 도 의미 없으므로 null 로 정리.
  if (next.automation_status === 'stopped') {
    next.automation_mode = null
    next.automation_poll_interval = null
    next.next_scheduled_at = null
  }
  sessionPipelines[index] = next
  return clone(next)
}

// =============================================================================
// 변이 — Pipeline description 편집
// =============================================================================

/**
 * Description 업데이트 mock. 실제 백엔드에서는 `PATCH /pipelines/{id}` 로 매핑 예정.
 * 세션 스토어에 반영해 페이지 이동 시에도 유지.
 */
export async function updatePipelineDescription(
  pipelineId: string,
  description: string,
): Promise<Pipeline> {
  await simulatedDelay()
  const index = sessionPipelines.findIndex((pipeline) => pipeline.id === pipelineId)
  if (index < 0) {
    throw new Error(`Pipeline not found: ${pipelineId}`)
  }
  const next: Pipeline = {
    ...sessionPipelines[index],
    description: description.trim() === '' ? null : description,
    updated_at: new Date().toISOString(),
  }
  sessionPipelines[index] = next
  return clone(next)
}

// =============================================================================
// 변이 — 수동 재실행 (목업)
// =============================================================================

export type ManualRerunMode = 'if_delta' | 'force_latest'

export interface ManualRerunResult {
  /** true 면 "실행 dispatch 됨" — 토스트 문구 분기에 사용 */
  dispatched: boolean
  /** 사용자에게 보여줄 메시지 */
  message: string
}

/**
 * 수동 재실행 mock. 실제 Celery dispatch 는 일어나지 않는다.
 *   - if_delta: 상류 delta 가 있으면 dispatched=true, 없으면 false (no-delta skip)
 *   - force_latest: 항상 dispatched=true
 *
 * Mock fixture 에서 delta 여부는 MOCK_UPSTREAM_DELTAS 를 참조해 판정한다.
 */
export async function rerunPipelineManually(
  pipelineId: string,
  mode: ManualRerunMode,
): Promise<ManualRerunResult> {
  await simulatedDelay()
  if (mode === 'force_latest') {
    return {
      dispatched: true,
      message: '강제 최신 재실행이 dispatch 됐습니다. 실행 이력에서 확인하세요.',
    }
  }
  // if_delta — 상류 delta 존재 여부로 판단
  const deltas = MOCK_UPSTREAM_DELTAS[pipelineId] ?? []
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
