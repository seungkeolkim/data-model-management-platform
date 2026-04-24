/**
 * Automation (파이프라인 자동화) — 타입 정의
 *
 * 배경: 목업 단계. 백엔드 실장 없음.
 * 원본 결정 기록: docs_for_claude/023-automation-mockup-tech-note.md §1-1 / §6 / §9
 *
 * 계층 구조:
 *   Pipeline (정적 엔티티)                           — config + automation_* 상태
 *     └─ PipelineExecution (동적 실행 이력, 확장) — trigger_kind / batch_id 필드 추가
 *
 * Pipeline 은 현재 백엔드에 엔티티로 존재하지 않는다.
 * 023 §9-2 에서 신규 테이블 도입(옵션 1) 이 확정됐으며, 목업은 이 모델을 프론트에서 선가정해 그린다.
 */
import type { Split, TaskType } from './dataset'

// =============================================================================
// 열거형 / 리터럴
// =============================================================================

/** 파이프라인의 자동화 활성 상태 */
export type AutomationStatus = 'stopped' | 'active' | 'error'

/** 자동화 모드 — stopped 일 때는 null */
export type AutomationMode = 'polling' | 'triggering'

/** polling 모드 전용 주기 프리셋 */
export type PollInterval = '10m' | '1h' | '6h' | '24h'

/**
 * error 상태 전환 사유.
 * CYCLE_DETECTED 는 chaining 분석기가 순환을 감지한 경우.
 * INPUT_GROUP_NOT_FOUND 는 Pipeline.input_group_id 가 삭제된 경우 (확장 여지).
 */
export type AutomationErrorReason = 'CYCLE_DETECTED' | 'INPUT_GROUP_NOT_FOUND'

/**
 * PipelineExecution.trigger_kind — 023 §9-7 의 3종 필터 카테고리.
 *  - manual_from_editor      : 데이터 변형 탭에서 수동 실행
 *  - automation_auto         : polling / triggering 자동 실행
 *  - automation_manual_rerun : Automation 페이지에서 수동 재실행 버튼 클릭
 */
export type TriggerKind =
  | 'manual_from_editor'
  | 'automation_auto'
  | 'automation_manual_rerun'

/**
 * automation 경로 실행의 세부 source — trigger_kind 가 automation_* 일 때만 값을 가진다.
 * 필터 UX 에서 automation 내부 세분화에 사용.
 */
export type AutomationTriggerSource = 'polling' | 'triggering' | 'manual_rerun'

// =============================================================================
// Pipeline (정적 엔티티)
// =============================================================================

/**
 * Pipeline 이 참조하는 dataset slot (input/output 공통).
 * "특정 group 의 특정 split" 단위. 실제 데이터 버전은 실행 시점에 resolve 된다.
 */
export interface PipelineDatasetSlot {
  group_id: string
  group_name: string
  split: Split
}

/**
 * Pipeline 의 manipulator task 한 건 요약. 목록 / DAG 노드에서 "어떤 변형이 있는지" 만 표시하면 되므로
 * 전체 params 는 담지 않는다. 에디터 재진입 시 Pipeline.config (전체) 를 별도로 조회하는 것을 가정.
 */
export interface PipelineTaskSummary {
  task_id: string
  operator: string
  display_name: string
}

/**
 * Pipeline 엔티티 (023 §9-2 옵션 1).
 *
 * `automation_last_seen_input_versions` 는 자동 실행이 "마지막으로 소비한" 입력 버전들의 맵이다.
 * delta 판정은 "현재 최신 버전 vs 이 맵" 으로 이루어진다. 수동 실행만 된 파이프라인은 빈 객체.
 */
export interface Pipeline {
  id: string
  /**
   * Automation 엔트리의 이름. 실 구현(027)에서는 `PipelineAutomation.name`. 목록 · 상세 헤더 · DAG 노드
   * 라벨에 노출. 템플릿 파이프라인의 이름과 같을 수도, 다를 수도 있다.
   */
  name: string
  description: string | null
  task_type: TaskType
  /**
   * 이 Automation 이 실행하는 **템플릿 파이프라인** 의 식별자 요약 (name + version).
   * 027 에서는 `Pipeline` 엔티티 FK 로 분리될 부분. 목업에서는 임베드 필드로 대체한다.
   */
  pipeline_template: {
    name: string
    /** "major.minor" — 예: "1.0". Dataset 버전 정책과 동일 형식 */
    version: string
  }
  input: PipelineDatasetSlot
  output: PipelineDatasetSlot
  tasks: PipelineTaskSummary[]
  automation_status: AutomationStatus
  automation_mode: AutomationMode | null
  automation_poll_interval: PollInterval | null
  automation_error_reason: AutomationErrorReason | null
  automation_last_seen_input_versions: Record<string, string>
  last_execution_at: string | null
  /** polling 모드에서만 값. 다음 예상 tick (표시 전용, 실제 스케줄러는 목업 스코프 밖) */
  next_scheduled_at: string | null
  created_at: string
  updated_at: string
}

/**
 * Pipeline automation 설정 패치용 payload. 상세 탭 폼에서 사용.
 * mode / interval 이 null 이면 해당 필드 미변경을 의미한다 (부분 업데이트).
 */
export interface PipelineAutomationUpdate {
  status?: AutomationStatus
  mode?: AutomationMode | null
  poll_interval?: PollInterval | null
}

// =============================================================================
// Chaining DAG — 자동 분석된 파이프라인 간 의존 그래프
// =============================================================================

/**
 * Chaining 엣지. 두 파이프라인이 같은 DatasetGroup 을 output / input 으로 공유하면 자동 생성.
 * group_id 를 함께 기록해 UI 에서 "어떤 그룹을 매개로 연결됐는지" 를 표시할 수 있다.
 */
export interface ChainingEdge {
  source_pipeline_id: string
  target_pipeline_id: string
  via_group_id: string
  via_group_name: string
  /** 이 엣지가 사이클에 포함돼 있으면 true. 우측 DAG 에서 빨강으로 강조. */
  in_cycle: boolean
}

/**
 * 자동 분석된 chaining 그래프 전체.
 *
 * nodes 는 "automation_status !== stopped" 이거나 "실행 이력이 있는" 파이프라인만 포함.
 * 023 §9-6 결정에 따라 "stopped + 이력 0 건" 인 파이프라인은 그리지 않는다.
 *
 * cycles 는 순환 노드 집합. 각 원소가 한 사이클에 포함된 pipeline_id 들이다.
 */
export interface ChainingGraph {
  nodes: Pipeline[]
  edges: ChainingEdge[]
  cycles: string[][]
}

// =============================================================================
// PipelineExecution (확장 — 기존 PipelineExecutionResponse 위에 automation 필드 추가)
// =============================================================================

/**
 * 실행 이력 페이지에서 사용하는 Pipeline Execution 요약.
 * 기존 types/pipeline.ts 의 PipelineExecutionResponse 와 유사하지만, automation 필드를 포함하고
 * 표시용 필드(pipeline_name 등) 가 서버에서 이미 조인되어 내려온다고 가정한다.
 */
export interface PipelineExecutionSummary {
  id: string
  pipeline_id: string
  pipeline_name: string
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED' | 'SKIPPED_NO_DELTA' | 'SKIPPED_UPSTREAM_FAILED'
  trigger_kind: TriggerKind
  /** automation 경로일 때만 값. manual_from_editor 면 null. */
  automation_trigger_source: AutomationTriggerSource | null
  /** 같은 검사 사이클에서 토폴로지 순서로 함께 실행된 그룹 ID. 단발 실행은 null. */
  automation_batch_id: string | null
  /** 트리거된 입력 버전 — (group_name → version) 맵. UI 가독성용. */
  triggered_input_versions: Record<string, string>
  output_dataset_version_id: string | null
  output_dataset_version: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  duration_seconds: number | null
  error_message: string | null
}

/**
 * 같은 automation_batch_id 로 묶이는 실행 그룹. 실행 이력 페이지에서 트리/그룹 접힘의 단위.
 * 단발(batch 없음) 실행은 별도로 표시.
 */
export interface ExecutionBatch {
  batch_id: string
  /** batch 시작 트리거 source. 같은 batch 내 모든 execution 에서 동일. */
  trigger_source: AutomationTriggerSource
  created_at: string
  /** 토폴로지 순서로 정렬된 실행 목록 */
  executions: PipelineExecutionSummary[]
}

// =============================================================================
// 상세 탭 — 상류 DatasetGroup delta 표시
// =============================================================================

/**
 * 파이프라인 상세 Automation 탭의 "상류 DatasetGroup 목록" 한 행.
 * 현재 최신 vs automation_last_seen_input_versions 를 UI 에서 비교 표시.
 */
export interface UpstreamGroupDelta {
  group_id: string
  group_name: string
  split: Split
  latest_version: string
  last_seen_version: string | null
  /** latest_version !== last_seen_version 이면 true */
  has_delta: boolean
}
