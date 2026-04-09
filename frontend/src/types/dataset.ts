/**
 * TypeScript 타입 정의 - Dataset 관련
 */

// =============================================================================
// Enums / Union Types
// =============================================================================

// DatasetGroup의 dataset_type: 데이터 가공 단계 표현
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
  dataset_type?: DatasetType          // 미지정 시 백엔드에서 RAW 기본값 사용
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

export interface ClassInfo {
  class_count: number
  class_mapping: Record<string, string>  // "0": "person", "1": "car"
}

export interface DatasetMetadata {
  class_info?: ClassInfo
}

export interface DatasetSummary {
  id: string
  split: Split
  version: string
  status: DatasetStatus
  image_count: number | null
  class_count: number | null
  annotation_format: AnnotationFormat | null
  storage_uri: string
  annotation_files: string[] | null
  metadata: DatasetMetadata | null
  created_at: string
}

export interface Dataset extends DatasetSummary {
  group_id: string
  annotation_format: AnnotationFormat | null
  updated_at: string
}

export interface DatasetValidateRequest {
  annotation_format: string
}

// =============================================================================
// 등록 요청
// =============================================================================

export interface DatasetRegisterRequest {
  // 그룹
  group_id?: string
  group_name?: string
  // 사용 목적 (드롭다운 필수 선택)
  task_types: TaskType[]
  // 어노테이션 포맷 (등록 후 선택, 미정이면 NONE)
  annotation_format: AnnotationFormat
  modality?: Modality
  source_origin?: string
  description?: string
  // Dataset
  split: Split
  // 소스 파일 경로 (파일 브라우저로 선택한 절대경로)
  source_image_dir: string
  source_annotation_files: string[]
  source_annotation_meta_file?: string
}

// =============================================================================
// 포맷 검증
// =============================================================================

export interface FormatValidateRequest {
  annotation_format: string
  annotation_files: string[]
  annotation_meta_file?: string
}

export interface FormatValidateResponse {
  valid: boolean
  errors: string[]
  summary: Record<string, unknown> | null
}

// =============================================================================
// 파일 브라우저
// =============================================================================

export interface FileBrowserEntry {
  name: string
  path: string
  is_dir: boolean
  size: number | null
  modified_at: string | null
}

export interface FileBrowserListResponse {
  current_path: string
  parent_path: string | null
  is_browse_root: boolean
  entries: FileBrowserEntry[]
}

export interface FileBrowserRootsResponse {
  roots: string[]
}

// =============================================================================
// Manipulator
// =============================================================================

export interface Manipulator {
  id: string
  name: string
  category: 'ANNOTATION_FILTER' | 'IMAGE_FILTER' | 'AUGMENT' | 'FORMAT_CONVERT' | 'MERGE' | 'SAMPLE' | 'REMAP'
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

// =============================================================================
// 데이터셋 뷰어
// =============================================================================

export interface SampleAnnotationItem {
  category_name: string
  bbox: number[] | null
  area: number | null
}

export interface SampleImageItem {
  image_id: number | string
  file_name: string
  width: number | null
  height: number | null
  image_url: string
  annotation_count: number
  annotations: SampleAnnotationItem[]
}

export interface SampleListResponse {
  items: SampleImageItem[]
  total: number
  page: number
  page_size: number
  categories: string[]
  /** bbox가 정규화 좌표(0~1)인 경우 true (YOLO + 이미지 크기 미로드 시) */
  bbox_normalized: boolean
}

// =============================================================================
// EDA 통계
// =============================================================================

export interface ClassDistributionItem {
  category_name: string
  annotation_count: number
  image_count: number
}

export interface BboxSizeDistributionItem {
  range_label: string
  count: number
}

export interface EdaStatsResponse {
  total_images: number
  total_annotations: number
  total_classes: number
  images_without_annotations: number
  class_distribution: ClassDistributionItem[]
  bbox_area_distribution: BboxSizeDistributionItem[]
  image_width_min: number | null
  image_width_max: number | null
  image_height_min: number | null
  image_height_max: number | null
}

// =============================================================================
// Lineage 그래프
// =============================================================================

export interface LineageNode {
  id: string
  dataset_id: string
  group_name: string
  split: string
  version: string
  dataset_type: DatasetType
  status: DatasetStatus
  image_count: number | null
  pipeline_image_url: string | null
}

export interface LineageEdge {
  id: string
  source: string
  target: string
  transform_config: Record<string, unknown> | null
  pipeline_summary: string | null
}

export interface LineageGraphResponse {
  nodes: LineageNode[]
  edges: LineageEdge[]
}
