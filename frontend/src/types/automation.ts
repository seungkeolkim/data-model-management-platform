/**
 * Automation (파이프라인 자동화) — 타입 정의
 *
 * 본 파일은 v7.13 baseline 의 실 자료구조를 그대로 mock 위에 투영한 신규 목업이다.
 * 이전 (026) 단일 `Pipeline` 임베드 모델은 폐기됐다 — Pipeline 자체가 더 이상 automation
 * 엔티티가 아니며, automation 은 **PipelineVersion 단위**에 1:0..1 로 붙는다.
 *
 * 계층 구조 (실 백엔드와 동일):
 *
 *   PipelineFamily            (느슨한 폴더, 강제력 없음, NULL 허용)
 *     └─ Pipeline (concept)   (전역 UNIQUE name, output_split / task_type 고정)
 *          └─ PipelineVersion (config immutable, 시간축 인스턴스)
 *               ├─ PipelineRun           (immutable 실행 이력)
 *               └─ PipelineAutomation    (1:0..1, partial unique active)
 *
 * 핵심 규약:
 *  - Automation 은 특정 version 을 가리킨다. v1.0 에 등록된 automation 은 v2.0 을 만들어도
 *    자동 추종하지 않고 v1.0 에 그대로 붙어있다 (027 §3-3 / §6-4 / §12-6).
 *  - 사용자는 명시적으로 reassign 해야 v2.0 으로 옮겨지며, 그 전까지는 reassign hint 노티
 *    (`AutomationReassignHint`) 를 표시한다.
 *  - input slot 들은 `Pipeline.config.tasks[*].inputs` 의 `source:dataset_split:<id>` 토큰에서
 *    추출되며 별도 FK 가 없다 (027 §12-9 비대칭 — output 만 단일 FK).
 *
 * 참조 문서:
 *  - 설계서 §2-2 Pipeline 측 3계층 / §4-2 source format v3
 *  - 027 §13 (Family + concept + version 분리) / §14 (UI + Family.color)
 *  - 028 §1 (저장/실행 분리, 모달 두 모드, JSON import 통합 등)
 */
import type { Split, TaskType } from './dataset'

// =============================================================================
// 열거형 / 리터럴
// =============================================================================

/** Automation 활성 상태 */
export type AutomationStatus = 'stopped' | 'active' | 'error'

/** 활성 모드 — stopped 일 때는 null */
export type AutomationMode = 'polling' | 'triggering'

/** polling 모드 전용 주기 프리셋 */
export type PollInterval = '10m' | '1h' | '6h' | '24h'

/**
 * error 상태 전환 사유.
 *  - CYCLE_DETECTED        : chaining 분석기가 순환을 감지한 경우
 *  - INPUT_GROUP_NOT_FOUND : 상류 split 이 삭제된 경우 (확장 여지)
 *  - PIPELINE_DELETED      : automation 이 가리키던 PipelineVersion 이 비활성화된 경우 (027 §6-4)
 */
export type AutomationErrorReason =
  | 'CYCLE_DETECTED'
  | 'INPUT_GROUP_NOT_FOUND'
  | 'PIPELINE_DELETED'

/**
 * PipelineRun.trigger_kind — 027 §9-7 의 3종 필터 카테고리.
 *  - manual_from_editor      : 데이터 변형 탭 / 목록 행 "실행" 버튼 (수동 dispatch)
 *  - automation_auto         : polling / triggering 자동 실행
 *  - automation_manual_rerun : Automation 페이지의 수동 재실행 버튼
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
// DatasetSplit 참조 — Pipeline 의 input/output 슬롯
// =============================================================================

/**
 * `(group, split)` 정적 슬롯 한 건 (v7.9 DatasetSplit 엔티티 단위).
 *
 * 백엔드 응답이 `split_id` FK 만 내려준다고 가정하지 않고, group_name / split 까지 join 된
 * 형태로 내려온다고 가정한다 — 페이지가 매번 별도 그룹 조회를 안 해도 되도록 하는 mock 표시
 * 편의. 실 API 가 같은 shape 를 보장하지 않으면 어댑터 layer 가 reshape 한다.
 */
export interface DatasetSplitRef {
  split_id: string
  group_id: string
  group_name: string
  split: Split
}

// =============================================================================
// PipelineFamily — 느슨한 폴더
// =============================================================================

/**
 * Family 는 "함께 보고 싶은 Pipeline 들의 묶음" 일 뿐 강제력이 없다 (DatasetGroup 과 다른 점).
 * Pipeline 은 자유롭게 family 간 이동 가능하며, family_id NULL = "미분류" 그룹.
 *
 * `color` 는 #RRGGBB 7자. v7.12 에서 도입돼 family heading / 행 swatch / 다중 체크박스 필터에서
 * 시각 구분에 쓰인다.
 */
export interface PipelineFamily {
  id: string
  name: string
  description: string | null
  color: string
  /** 이 family 에 속한 Pipeline (concept) 수 — 헤딩 표시용 */
  pipeline_count: number
  created_at: string
  updated_at: string
}

// =============================================================================
// Pipeline (concept)
// =============================================================================

/**
 * Pipeline = "정적 개념 정체성" (v7.11 격하).
 *
 * - name 은 전역 UNIQUE
 * - output_split / task_type 은 개념 레벨 고정 — 변경 불가, 변경하려면 다른 Pipeline 으로 분기
 * - config / version 컬럼은 PipelineVersion 으로 분리됐으므로 여기엔 없다
 * - is_active 는 concept 단위 soft delete
 *
 * `latest_active_version_id` / `latest_active_version` 은 백엔드 응답에 join 되어 내려오는 표시용
 * 필드 (027 §14-2 의 "최신 활성 버전" 노출 패턴). version_count 는 inactive 포함 누적.
 */
export interface PipelineConcept {
  id: string
  family_id: string | null
  /** Family 미배정이면 null. */
  family_name: string | null
  family_color: string | null
  name: string
  description: string | null
  task_type: TaskType
  output: DatasetSplitRef
  is_active: boolean
  latest_active_version_id: string | null
  latest_active_version: string | null
  version_count: number
  created_at: string
  updated_at: string
}

// =============================================================================
// PipelineVersion — 시간축 인스턴스
// =============================================================================

/**
 * 변형 task 한 건 요약. 전체 params 는 담지 않고, 목록·DAG 노드 라벨에 필요한 정도만.
 */
export interface PipelineTaskSummary {
  task_id: string
  operator: string
  display_name: string
}

/**
 * PipelineVersion = "이 시점의 config 인스턴스".
 *
 * - config 는 immutable 이며, 같은 concept 안에서만 누적 (다른 Pipeline 으로 이동 불가)
 * - description 은 v7.13 신설 — "이 버전에서 무엇을 바꿨는가" 사용자 메모
 * - automation 은 1:0..1 — 이 version 에 active automation 이 있으면 임베드, 없으면 null
 * - input_splits 는 `config.tasks[*].inputs` 에서 추출된 dataset_split 슬롯 목록
 * - is_active 는 version 단위 soft delete (별도)
 */
export interface PipelineVersion {
  id: string
  pipeline_id: string
  /** concept 의 name — 표시 join 편의용 (실 API 응답에 포함 가정). */
  pipeline_name: string
  /** "major.minor" — 예 "1.0", "2.0". 사용자 명시로만 증가, hash 판정 없음. */
  version: string
  description: string | null
  is_active: boolean
  /** config 요약 — 전체 config 는 별도 조회. 목록·DAG 노드 라벨에 사용. */
  task_summaries: PipelineTaskSummary[]
  /** input slot 들 — config.tasks[*].inputs 의 source:dataset_split:<id> 추출 결과. */
  input_splits: DatasetSplitRef[]
  /** 이 version 에 등록된 active automation. 없으면 null (1:0..1). */
  automation: PipelineAutomation | null
  /** 마지막 PipelineRun 시각 — 목록 정렬 / 가시성용. */
  last_run_at: string | null
  run_count: number
  created_at: string
  updated_at: string
}

// =============================================================================
// PipelineAutomation — version 단위 1:0..1 runner
// =============================================================================

/**
 * Automation runner 등록. 한 PipelineVersion 에 active 한 automation 은 최대 1건
 * (partial unique index `(pipeline_version_id) WHERE is_active=TRUE`).
 *
 * - status / mode / poll_interval 은 사용자가 상세 탭에서 조정
 * - error_reason 은 시스템 자동 전환 (사이클 감지, 상류 그룹 삭제 등)
 * - last_seen_input_versions 는 자동 실행이 마지막으로 소비한 입력 버전들
 *   ({split_id: version} 매핑) — delta 판정의 기준점
 * - is_active=false / deleted_at 은 soft delete (027 §12-3) — 과거 PipelineRun.automation_id
 *   참조를 깨뜨리지 않기 위해 row 는 보존
 */
export interface PipelineAutomation {
  id: string
  pipeline_version_id: string
  status: AutomationStatus
  mode: AutomationMode | null
  poll_interval: PollInterval | null
  error_reason: AutomationErrorReason | null
  last_seen_input_versions: Record<string, string>
  is_active: boolean
  deleted_at: string | null
  /** polling 모드에서만 값. 다음 예상 tick (목업 표시 전용). */
  next_scheduled_at: string | null
  /** 실제로 마지막으로 dispatch 한 시각 (성공 / 실패 / no-delta skip 무관). */
  last_dispatched_at: string | null
  created_at: string
  updated_at: string
}

/** Automation 설정 부분 업데이트 payload. 상세 탭 폼 / status 토글에서 사용. */
export interface AutomationUpdate {
  status?: AutomationStatus
  mode?: AutomationMode | null
  poll_interval?: PollInterval | null
}

// =============================================================================
// PipelineRun — 실행 이력 (immutable)
// =============================================================================

/** PipelineRun.status 6종 (목업 / 실 baseline 동일). */
export type PipelineRunStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'DONE'
  | 'FAILED'
  | 'SKIPPED_NO_DELTA'
  | 'SKIPPED_UPSTREAM_FAILED'

/**
 * PipelineRun 1건. v7.13 의 평탄화 필드 (`pipeline_name`, `pipeline_version`,
 * `output_dataset_group_name`, `output_dataset_split`) 를 포함해 실행 이력 페이지의
 * 5컬럼 표시를 별도 join 없이 가능하게 한다.
 *
 * - automation_id 는 자동 실행 / 수동 재실행 경로일 때만 값
 * - automation_batch_id 는 같은 검사 사이클(트리거 1회)에서 함께 실행된 그룹 ID — 단발 실행은 null
 * - resolved_input_versions 는 {split_id: version} (실 백엔드 형태)
 * - triggered_input_versions_display 는 {group_name (split): version} (UI 가독성용)
 */
export interface PipelineRun {
  id: string
  pipeline_version_id: string
  pipeline_name: string
  pipeline_version: string
  automation_id: string | null
  status: PipelineRunStatus
  trigger_kind: TriggerKind
  automation_trigger_source: AutomationTriggerSource | null
  automation_batch_id: string | null
  resolved_input_versions: Record<string, string>
  triggered_input_versions_display: Record<string, string>
  output_dataset_version_id: string | null
  output_dataset_version: string | null
  output_dataset_group_name: string | null
  output_dataset_split: Split | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  duration_seconds: number | null
  error_message: string | null
}

/**
 * 같은 automation_batch_id 로 묶이는 실행 그룹. 실행 이력 페이지의 트리/그룹 접힘 단위.
 * 단발(batch_id=null) 실행은 별도로 표시.
 */
export interface ExecutionBatch {
  batch_id: string
  trigger_source: AutomationTriggerSource
  created_at: string
  /** 토폴로지 순서로 정렬된 실행 목록. */
  runs: PipelineRun[]
}

// =============================================================================
// Chaining DAG — PipelineVersion 단위
// =============================================================================

/**
 * Chaining DAG 의 노드 = PipelineVersion 1건.
 *
 * 노드 라벨에는 concept name + version 이 함께 보이며, family 색상으로 시각 구분한다.
 * automation 이 미등록이거나 stopped 인 version 은 이 그래프에 포함될 수도, 안 될 수도 있다
 * (정책: "automation_status !== stopped" 또는 "이력이 있는" version 만 — 027 §9-6 승계).
 */
export interface ChainingNode {
  pipeline_version_id: string
  pipeline_id: string
  pipeline_name: string
  pipeline_version: string
  task_type: TaskType
  family_id: string | null
  family_name: string | null
  family_color: string | null
  automation_status: AutomationStatus
  automation_error_reason: AutomationErrorReason | null
  /** 사이클에 포함된 노드면 true — 우측 DAG 에서 빨강 강조. */
  in_cycle: boolean
}

/**
 * Chaining 엣지. 두 PipelineVersion 이 같은 DatasetSplit 을 output / input 으로 공유하면 자동 생성.
 * via_split_id 외에 group_name / split 까지 함께 노출해 UI 에서 "어떤 그룹·split 을 매개로 연결됐는지"
 * 를 표시한다.
 */
export interface ChainingEdge {
  source_version_id: string
  target_version_id: string
  via_split_id: string
  via_group_id: string
  via_group_name: string
  via_split: Split
  in_cycle: boolean
}

/**
 * 자동 분석된 chaining 그래프 전체. cycles 는 순환 노드(version_id) 집합 목록.
 */
export interface ChainingGraph {
  nodes: ChainingNode[]
  edges: ChainingEdge[]
  cycles: string[][]
}

// =============================================================================
// 상세 탭 — 상류 DatasetSplit delta
// =============================================================================

/**
 * 파이프라인 상세 탭의 "상류 DatasetSplit 목록" 한 행.
 * 현재 최신 vs automation.last_seen_input_versions 를 UI 에서 비교 표시.
 */
export interface UpstreamSplitDelta {
  split_id: string
  group_id: string
  group_name: string
  split: Split
  latest_version: string
  last_seen_version: string | null
  /** latest_version !== last_seen_version 이면 true */
  has_delta: boolean
}

// =============================================================================
// Reassign hint (§12-6) — 같은 concept 의 다른 version 에 automation 이 있을 때
// =============================================================================

/**
 * 새 version 을 만들었을 때, 같은 concept 의 이전 version 에 active automation 이 그대로 붙어있다는
 * 사실을 사용자에게 알리는 hint 정보. 027 §12-6 의 "자동 reassign 안 함, 노티만" 정책에 따라
 * 새 version 상세 진입 시 1회 표시 후 사용자 판단으로 reassign / 유지.
 *
 * automation 이 없거나 같은 version 에 이미 붙어 있으면 hint 자체가 발급되지 않는다.
 */
export interface AutomationReassignHint {
  pipeline_id: string
  current_version_id: string
  current_version: string
  active_on_version_id: string
  active_on_version: string
  automation_id: string
}

