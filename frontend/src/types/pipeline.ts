/**
 * 파이프라인 노드 에디터 — 타입 정의
 *
 * React Flow 노드/엣지 데이터 구조, PipelineConfig 스키마,
 * API 응답 타입, 검증 결과 타입을 정의한다.
 */

import type { Node, Edge } from '@xyflow/react'

// =============================================================================
// PipelineConfig — 백엔드 lib/pipeline/config.py 와 1:1 대응
// =============================================================================

export interface TaskConfig {
  operator: string
  /** v3 포맷:
   *   - "source:dataset_split:<split_id>"   (Pipeline.config / 사용자 spec)
   *   - "source:dataset_version:<id>"       (PipelineRun.transform_config / resolved)
   *   - "task_<node_id>"                    (task 간 참조)
   */
  inputs: string[]
  params: Record<string, unknown>
}

export interface OutputConfig {
  dataset_type: 'SOURCE' | 'PROCESSED' | 'FUSION'
  annotation_format: string | null  // "COCO" | "YOLO" | null (자동 유지)
  split: 'TRAIN' | 'VAL' | 'TEST' | 'NONE'
}

export interface PipelineConfig {
  name: string
  description?: string
  output: OutputConfig
  tasks: Record<string, TaskConfig>
  /**
   * Load→Save 직결 모드의 소스 DatasetSplit.id (v7.10 / 027 §4-1).
   * version 은 실행 시점 Version Resolver Modal 에서 확정된다.
   */
  passthrough_source_split_id?: string | null
  /** DAG 스키마 버전. 현재 SDK 는 항상 3 을 생성. */
  schema_version?: number
  /** PipelineRun.transform_config 측에서 채워지는 resolved 버전. FE spec 단계에선 항상 null. */
  passthrough_source_dataset_id?: string | null
}

/**
 * Save 노드가 없어도 생성 가능한 부분 설정.
 *
 * JSON 프리뷰와 schema preview 에서 사용. output 이 없으면
 * 백엔드 실행은 불가하지만 프리뷰 계산은 가능하다.
 */
export interface PartialPipelineConfig {
  name: string
  description?: string
  output: OutputConfig | null
  tasks: Record<string, TaskConfig>
  passthrough_source_split_id?: string | null
  schema_version?: number
}

// =============================================================================
// API 응답 타입
// =============================================================================

export interface PipelineValidationIssue {
  severity: 'error' | 'warning'
  code: string
  message: string
  field: string
}

export interface PipelineValidationResponse {
  is_valid: boolean
  error_count: number
  warning_count: number
  issues: PipelineValidationIssue[]
}

export interface PipelineSubmitResponse {
  execution_id: string
  celery_task_id: string | null
  message: string
}

/** DAG 태스크별 진행 상태 */
export interface TaskProgressItem {
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  operator: string
  started_at?: string
  finished_at?: string
  input_images?: number
  output_images?: number
  /** 이미지 실체화 단계 전용 필드 */
  total_images?: number
  materialized?: number
  skipped?: number
}

export interface PipelineExecutionResponse {
  id: string
  output_dataset_id: string
  config: Record<string, unknown> | null
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  current_stage: string | null
  processed_count: number
  total_count: number
  error_message: string | null
  celery_task_id: string | null
  task_progress: Record<string, TaskProgressItem> | null
  pipeline_image_url: string | null
  output_dataset_version: string | null
  output_dataset_group_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface PipelineListResponse {
  items: PipelineExecutionResponse[]
  total: number
}

// =============================================================================
// PipelineFamily / Pipeline (concept) / PipelineVersion (v7.11)
// =============================================================================

export interface PipelineFamilyResponse {
  id: string
  name: string
  description: string | null
  /** Family 시각 구분 색 (`#RRGGBB`). */
  color: string
  pipeline_count: number
  created_at: string
  updated_at: string
}

export interface PipelineFamilyCreateRequest {
  name: string
  description?: string | null
  /** `#RRGGBB`. 미지정 시 backend 가 랜덤 할당. */
  color?: string | null
}

export interface PipelineFamilyUpdateRequest {
  name?: string | null
  description?: string | null
  color?: string | null
}

export interface PipelineVersionSummary {
  id: string
  version: string
  is_active: boolean
  has_automation: boolean
  created_at: string
  updated_at: string
}

export interface PipelineEntityResponse {
  id: string
  family_id: string | null
  family_name: string | null
  name: string
  description: string | null
  output_split_id: string
  output_group_id: string | null
  output_group_name: string | null
  output_split: string | null
  task_type: string
  is_active: boolean
  versions: PipelineVersionSummary[]
  latest_version: PipelineVersionSummary | null
  created_at: string
  updated_at: string
}

export interface PipelineListItem {
  id: string
  family_id: string | null
  family_name: string | null
  name: string
  description: string | null
  output_split_id: string
  output_group_id: string | null
  output_group_name: string | null
  output_split: string | null
  task_type: string
  is_active: boolean
  version_count: number
  latest_version: string | null
  has_automation: boolean
  run_count: number
  last_run_at: string | null
  created_at: string
  updated_at: string
}

export interface PipelineListPageResponse {
  items: PipelineListItem[]
  total: number
  limit: number
  offset: number
}

export interface PipelineUpdateRequest {
  name?: string | null
  description?: string | null
  family_id?: string | null
  unset_family?: boolean
  is_active?: boolean | null
}

export interface PipelineVersionResponse {
  id: string
  pipeline_id: string
  pipeline_name: string
  family_id: string | null
  family_name: string | null
  version: string
  config: Record<string, unknown>
  task_type: string
  output_split_id: string
  output_group_id: string | null
  output_group_name: string | null
  output_split: string | null
  is_active: boolean
  has_automation: boolean
  created_at: string
  updated_at: string
}

export interface PipelineVersionUpdateRequest {
  is_active?: boolean | null
}

/** POST /pipelines/versions/{id}/runs 요청 바디 */
export interface PipelineRunSubmitRequest {
  resolved_input_versions: Record<string, string>  // {split_id: version}
}

// =============================================================================
// PipelineAutomation (v7.11 — version 단위)
// =============================================================================

export interface PipelineAutomationRealResponse {
  id: string
  pipeline_version_id: string
  pipeline_id: string | null
  pipeline_name: string | null
  pipeline_version: string | null
  status: 'stopped' | 'active' | 'error'
  mode: 'polling' | 'triggering' | null
  poll_interval: '10m' | '1h' | '6h' | '24h' | null
  error_reason: string | null
  last_seen_input_versions: Record<string, unknown> | null
  is_active: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface PipelineAutomationUpsertRequest {
  status?: 'stopped' | 'active' | 'error'
  mode?: 'polling' | 'triggering' | null
  poll_interval?: '10m' | '1h' | '6h' | '24h' | null
}

export interface PipelineAutomationRerunRequest {
  mode: 'if_delta' | 'force_latest'
}

// =============================================================================
// 노드 데이터 타입 — React Flow node.data에 저장되는 도메인 데이터
// =============================================================================

/**
 * DataLoad 노드: 데이터셋 그룹 → Split 2단계 선택 → `source:<split_id>` 참조 생성.
 *
 * v7.10 (핸드오프 027 §4-1, §12-1) — schema_version=2 전환으로 version 입력은 제거.
 * 버전은 실행 시점에 Version Resolver Modal 에서 선택. Pipeline 저장은 `(group, split)`
 * 까지만 고정.
 */
export interface DataLoadNodeData {
  type: 'dataLoad'
  /** 1단계: 선택된 DatasetGroup ID */
  groupId: string | null
  /** 1단계: 그룹명 (표시용) */
  groupName: string
  /** 2단계: 선택된 Split 문자열 (TRAIN / VAL / TEST / NONE) */
  split: string | null
  /** 2단계: 선택된 DatasetSplit (정적 슬롯) ID — v7.10 `source:<split_id>` 참조용 */
  splitId: string | null
  /** 표시용 라벨 */
  datasetLabel: string
  /** 검증 이슈 (validate 후 매핑) */
  validationIssues?: PipelineValidationIssue[]
  [key: string]: unknown
}

/** Operator 노드: 범용 단일입력/단일출력 manipulator (convert, filter, sample, remap, augment) */
export interface OperatorNodeData {
  type: 'operator'
  operator: string               // MANIPULATOR_REGISTRY 키 (예: "det_format_convert_to_coco")
  category: string               // 예: "FORMAT_CONVERT"
  label: string                  // 표시용 이름
  params: Record<string, unknown>
  paramsSchema: Record<string, unknown> | null  // API에서 가져온 동적 폼 스키마
  /** 검증 이슈 */
  validationIssues?: PipelineValidationIssue[]
  [key: string]: unknown
}

/** Merge 노드: det_/cls_merge_datasets, 다중 입력 필수. 에디터 taskType 에 따라 operator 결정 */
export interface MergeNodeData {
  type: 'merge'
  operator: 'det_merge_datasets' | 'cls_merge_datasets'
  params: Record<string, unknown>
  /** 현재 연결된 입력 수 (동적 핸들 관리용) */
  inputCount: number
  /** 검증 이슈 */
  validationIssues?: PipelineValidationIssue[]
  [key: string]: unknown
}

/** Save 노드: 파이프라인 출력 설정 (싱크 노드) */
export interface SaveNodeData {
  type: 'save'
  name: string
  description: string
  datasetType: 'SOURCE' | 'PROCESSED' | 'FUSION'
  annotationFormat: string | null
  split: 'TRAIN' | 'VAL' | 'TEST' | 'NONE'
  /** 검증 이슈 */
  validationIssues?: PipelineValidationIssue[]
  [key: string]: unknown
}

/** Placeholder 노드: registry에 없는 operator 복원 시 사용 (열람 전용, 실행 차단) */
export interface PlaceholderNodeData {
  type: 'placeholder'
  originalOperator: string
  originalParams: Record<string, unknown>
  originalInputs: string[]
  reason: string
  validationIssues?: PipelineValidationIssue[]
  [key: string]: unknown
}

/** 모든 노드 데이터의 유니온 타입 */
export type PipelineNodeData =
  | DataLoadNodeData
  | OperatorNodeData
  | MergeNodeData
  | SaveNodeData
  | PlaceholderNodeData

// =============================================================================
// React Flow 노드/엣지 타입 앨리어스
// =============================================================================

export type PipelineNode = Node<PipelineNodeData>
export type PipelineEdge = Edge

// =============================================================================
// 노드 팔레트 아이템
// =============================================================================

/** NodePalette에서 표시되는 추가 가능한 노드 종류 */
export interface PaletteItem {
  /** manipulator name 또는 특수 노드 키 ("dataLoad", "save") */
  key: string
  label: string
  category: string
  description?: string
  /** 노드 추가 시 생성할 데이터 팩토리 */
  createNodeData: () => PipelineNodeData
}

// =============================================================================
// 클라이언트 사전 검증 결과
// =============================================================================

export interface ClientValidationError {
  nodeId?: string
  message: string
}
