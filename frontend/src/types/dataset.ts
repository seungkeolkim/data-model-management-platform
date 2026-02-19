/**
 * TypeScript 타입 정의 - Dataset 관련
 */

// =============================================================================
// Enums / Union Types
// =============================================================================

export type DatasetType = 'RAW' | 'SOURCE' | 'PROCESSED' | 'FUSION'
export type AnnotationFormat = 'COCO' | 'YOLO' | 'ATTR_JSON' | 'CLS_FOLDER' | 'CUSTOM' | 'NONE'
export type TaskType = 'DETECTION' | 'SEGMENTATION' | 'ATTR_CLASSIFICATION' | 'ZERO_SHOT' | 'CLASSIFICATION'
export type Modality = 'RGB' | 'THERMAL' | 'DEPTH' | 'MULTISPECTRAL'
export type Split = 'TRAIN' | 'VAL' | 'TEST' | 'NONE'
export type DatasetStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'ERROR'

// =============================================================================
// Dataset Group
// =============================================================================

export interface DatasetGroup {
  id: string
  name: string
  dataset_type: DatasetType
  annotation_format: AnnotationFormat
  task_types: TaskType[] | null
  modality: Modality
  source_origin: string | null
  description: string | null
  extra: Record<string, unknown> | null
  created_at: string
  updated_at: string
  datasets: DatasetSummary[]
}

export interface DatasetGroupCreate {
  name: string
  dataset_type: DatasetType
  annotation_format?: AnnotationFormat
  task_types?: TaskType[]
  modality?: Modality
  source_origin?: string
  description?: string
  extra?: Record<string, unknown>
}

export interface DatasetGroupUpdate {
  name?: string
  annotation_format?: AnnotationFormat
  task_types?: TaskType[]
  modality?: Modality
  source_origin?: string
  description?: string
  extra?: Record<string, unknown>
}

export interface DatasetGroupListResponse {
  items: DatasetGroup[]
  total: number
  page: number
  page_size: number
}

// =============================================================================
// Dataset (split x version 단위)
// =============================================================================

export interface DatasetSummary {
  id: string
  split: Split
  version: string
  status: DatasetStatus
  image_count: number | null
  class_count: number | null
  storage_uri: string
  created_at: string
}

export interface Dataset extends DatasetSummary {
  group_id: string
  annotation_format: AnnotationFormat | null
  updated_at: string
}

// =============================================================================
// 등록 요청
// =============================================================================

export interface DatasetRegisterRequest {
  // 그룹
  group_id?: string
  group_name?: string
  dataset_type: DatasetType
  annotation_format?: AnnotationFormat
  task_types?: TaskType[]
  modality?: Modality
  source_origin?: string
  description?: string
  // Dataset
  split?: Split
  version?: string
  storage_uri: string
}

export interface DatasetValidateRequest {
  storage_uri: string
}

export interface DatasetValidateResponse {
  storage_uri: string
  path_exists: boolean
  images_dir_exists: boolean
  annotation_exists: boolean
  image_count: number
}

// =============================================================================
// Manipulator
// =============================================================================

export interface Manipulator {
  id: string
  name: string
  category: 'FILTER' | 'AUGMENT' | 'FORMAT_CONVERT' | 'MERGE' | 'SAMPLE' | 'REMAP'
  scope: ('PER_SOURCE' | 'POST_MERGE')[]
  compatible_task_types: TaskType[] | null
  compatible_annotation_fmts: AnnotationFormat[] | null
  output_annotation_fmt: AnnotationFormat | null
  params_schema: Record<string, unknown> | null
  description: string | null
  status: 'ACTIVE' | 'EXPERIMENTAL' | 'DEPRECATED'
  version: string | null
  created_at: string
}

// =============================================================================
// Pipeline
// =============================================================================

export interface PipelineExecution {
  id: string
  output_dataset_id: string
  config: Record<string, unknown> | null
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  current_stage: string | null
  processed_count: number
  total_count: number
  error_message: string | null
  celery_task_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}
