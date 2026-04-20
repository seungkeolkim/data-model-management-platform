/**
 * TypeScript 타입 정의 - Dataset 관련
 */

// =============================================================================
// Enums / Union Types
// =============================================================================

// DatasetGroup의 dataset_type: 데이터 가공 단계 표현
export type DatasetType = 'RAW' | 'SOURCE' | 'PROCESSED' | 'FUSION'
export type AnnotationFormat = 'COCO' | 'YOLO' | 'ATTR_JSON' | 'CLS_MANIFEST' | 'CUSTOM' | 'NONE'
// CLASSIFICATION은 단일 라벨/다중 head 이미지 분류를 모두 포함 (구 ATTR_CLASSIFICATION 통합).
export type TaskType = 'DETECTION' | 'SEGMENTATION' | 'CLASSIFICATION' | 'ZERO_SHOT'
export type Modality = 'RGB' | 'THERMAL' | 'DEPTH' | 'MULTISPECTRAL'
export type Split = 'TRAIN' | 'VAL' | 'TEST' | 'NONE'
export type DatasetStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'ERROR'

// =============================================================================
// Dataset Group
// =============================================================================

// head_schema: classification 그룹 전용 SSOT. detection 그룹은 null.
// {"heads":[{"name":"...","multi_label":false,"classes":["c0","c1",...]}]}
export interface HeadSchemaHead {
  name: string
  multi_label: boolean
  classes: string[]
}
export interface HeadSchema {
  heads: HeadSchemaHead[]
}

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
  head_schema: HeadSchema | null
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

/**
 * Dataset.metadata.class_info — detection / classification 저장 구조가 달라 union으로 표현.
 * detection: register_tasks / validate에서 {class_count, class_mapping} 저장
 * classification: register_classification_tasks에서 {heads:[...], skipped_*, intra_class_*} 저장
 */
export interface DetectionClassInfo {
  class_count: number
  class_mapping: Record<string, string>  // "0": "person", "1": "car"
}

export interface ClassificationHeadInfo {
  name: string
  multi_label: boolean
  class_mapping: Record<string, string>              // "0": "no_helmet", "1": "helmet"
  per_class_image_count: Record<string, number>      // class_name → 이미지 수
}

export interface ClassificationClassInfo {
  heads: ClassificationHeadInfo[]
  // single-label head 에서 동일 파일명이 2개 이상 class 에 등장하여 ingest 에서 skip 된 이미지 상세.
  skipped_collision_count?: number
  skipped_collisions?: unknown[]
}

export type ClassInfo = DetectionClassInfo | ClassificationClassInfo

/** 레거시 별칭 — 기존 import 호환. 새 코드는 ClassInfo 또는 구체 타입을 사용. */
export type ClassInfoLegacy = DetectionClassInfo

// 런타임 narrowing용 타입 가드. JSONB라서 컴파일러가 자동으로 좁히지 못함.
export function isClassificationClassInfo(
  classInfo: ClassInfo | null | undefined,
): classInfo is ClassificationClassInfo {
  return !!classInfo && 'heads' in classInfo && Array.isArray((classInfo as ClassificationClassInfo).heads)
}

export function isDetectionClassInfo(
  classInfo: ClassInfo | null | undefined,
): classInfo is DetectionClassInfo {
  return !!classInfo && 'class_mapping' in classInfo && !('heads' in classInfo)
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
  // detection: COCO/YOLO 메타 파일명(예: data.yaml), classification: head_schema.json
  annotation_meta_file: string | null
  metadata: DatasetMetadata | null
  pipeline_execution_id: string | null
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
// Classification 등록 요청/응답
// =============================================================================
// 이미지 identity 는 filename 기반 (§2-8). single-label head 에서 동일 파일명이
// 2개 이상 class 에 등장하면 ingest 단계에서 warning + skip 되므로 별도 사용자
// 정책(duplicate_image_policy) 선택지는 없다.

export interface ClassificationHeadSpec {
  name: string                       // head 표시 이름 (편집 가능)
  multi_label: boolean               // true면 한 이미지가 여러 class에 속할 수 있음
  classes: string[]                  // 순서 = 출력 index (SSOT)
  source_class_paths: string[]       // classes와 같은 순서의 원본 폴더 절대경로
}

export interface DatasetRegisterClassificationRequest {
  group_id?: string
  group_name?: string
  modality?: Modality
  source_origin?: string
  description?: string
  split: Split
  source_root_dir: string
  heads: ClassificationHeadSpec[]
}

export interface ClassificationHeadWarning {
  head_name: string
  kind: 'NEW_HEAD' | 'NEW_CLASS'
  detail: string
}

export interface DatasetRegisterClassificationResponse {
  group_id: string
  dataset_id: string
  celery_task_id: string | null
  warnings: ClassificationHeadWarning[]
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
// Classification 폴더 스캔 (2레벨 <head>/<class>/ 구조)
// =============================================================================

export interface ClassificationClassEntry {
  name: string           // class 폴더명 원본
  path: string           // 절대경로
  image_count: number    // 해당 폴더 바로 아래 이미지 파일 수
  has_subdirs: boolean   // 서브디렉토리 존재 여부 (true면 2레벨 초과 의심)
}

export interface ClassificationHeadEntry {
  name: string           // head 폴더명 원본
  path: string           // 절대경로
  classes: ClassificationClassEntry[]
}

export interface ClassificationScanResponse {
  root_path: string
  heads: ClassificationHeadEntry[]
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
// Classification 전용 뷰어/EDA 응답 타입
// =============================================================================
// 백엔드가 annotation_format === 'CLS_MANIFEST' 일 때 다른 shape을 반환한다.
// 프론트는 group.annotation_format 으로 분기해 Detection / Classification 컴포넌트를 선택.

export interface ClassificationSampleImageItem {
  /** 현재 storage pool 상의 파일명 (basename). merge rename 이 적용된 경우 prefix 가 포함된 이름이다. */
  file_name: string
  /** merge rename 등으로 원본과 달라진 경우에만 원본 basename. 동일하면 null 로 내려온다. */
  original_file_name: string | null
  image_url: string
  width: number | null
  height: number | null
  labels: Record<string, string[]>        // head_name → [class_name, ...]
}

export interface ClassificationSampleHeadInfo {
  name: string
  multi_label: boolean
  classes: string[]
}

export interface ClassificationSampleListResponse {
  items: ClassificationSampleImageItem[]
  total: number
  page: number
  page_size: number
  heads: ClassificationSampleHeadInfo[]
}

export interface ClassificationHeadClassCount {
  class_name: string
  image_count: number
}

export interface ClassificationHeadDistribution {
  head_name: string
  multi_label: boolean
  labeled_image_count: number
  unlabeled_image_count: number
  classes: ClassificationHeadClassCount[]
}

export interface ClassificationCooccurrencePair {
  head_a: string
  head_b: string
  classes_a: string[]
  classes_b: string[]
  a_counts: number[]
  b_counts: number[]
  joint_counts: number[][]
}

export interface ClassificationPositiveRatioItem {
  head_name: string
  class_name: string
  positive_count: number
  negative_count: number
  positive_ratio: number
}

export interface ClassificationEdaResponse {
  total_images: number
  image_width_min: number | null
  image_width_max: number | null
  image_height_min: number | null
  image_height_max: number | null
  per_head_distribution: ClassificationHeadDistribution[]
  head_cooccurrence: ClassificationCooccurrencePair[]
  multi_label_positive_ratio: ClassificationPositiveRatioItem[]
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
