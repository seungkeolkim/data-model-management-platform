/**
 * Automation 목업 fixture — v7.13 baseline (PipelineVersion 단위) 위에서 재작성.
 *
 * 이전 026 fixture 는 "Pipeline 단일 엔티티에 automation 필드 임베드" 모델이었으나, 본 fixture 는
 * 실 baseline 의 5엔티티 (`PipelineFamily` / `Pipeline` (concept) / `PipelineVersion` /
 * `PipelineAutomation` / `PipelineRun`) 분리를 그대로 반영한다.
 *
 * 시나리오 (의도적으로 7번 항목까지 다 다른 케이스):
 *   ① version 진화 + automation 정착   — C1 helmet_merge: v1.0(초기 manual) + v2.0(automation triggering ✅)
 *   ② 정상 chaining                    — C2 helmet_visible_update: v1.0(automation polling 1h ✅, 상류=C1.v2.0 출력)
 *   ③ Reassign hint 시연               — C3 vehicle_augment: v1.0(automation polling 6h ✅) + v2.0(automation 미등록 → hint)
 *   ④ 사이클 감지                      — C4 cycle_demo_a_to_b v1.0 ↔ C5 cycle_demo_b_to_a v1.0 (CYCLE_DETECTED)
 *   ⑤ Automation 미등록 (concept 만)   — C6 person_detection_raw_to_coco v1.0 (manual run 만 존재)
 *   ⑥ 수동 재실행 no-delta skip        — C3 v1.0 의 SKIPPED_NO_DELTA run 으로 시연
 *   ⑦ Family 분류 + 미분류             — F1(C1, C2) / F2(C3) / F3(C4, C5) / 미분류(C6)
 *
 * 모든 ID 는 `f-*` (family) / `c-*` (concept) / `v-*` (version) / `a-*` (automation) / `r-*` (run) /
 * `b-*` (batch) / `s-*` (split) 접두어로 mock 임을 시각화. UUID 는 사용하지 않는다.
 *
 * 시간선:
 *   - 2026-04-10 ~ 2026-04-30 사이로 구성. last_run / last_dispatched 가 자연스럽게 누적되도록 배치.
 */
import type {
  ChainingEdge,
  ChainingGraph,
  ChainingNode,
  ExecutionBatch,
  PipelineAutomation,
  PipelineConcept,
  PipelineFamily,
  PipelineRun,
  PipelineTaskSummary,
  PipelineVersion,
  UpstreamSplitDelta,
} from '@/types/automation'

// =============================================================================
// DatasetSplit 참조 상수 — fixture 내부에서 이름 오타 방지용
// =============================================================================

const SPLIT_HEADCROP_RAW_VAL = {
  split_id: 's-headcrop-raw-val',
  group_id: 'g-hardhat-headcrop-raw',
  group_name: 'hardhat_headcrop_raw',
  split: 'VAL' as const,
}
const SPLIT_HEADCROP_ORIGINAL_MERGED_VAL = {
  split_id: 's-headcrop-original-merged-val',
  group_id: 'g-hardhat-headcrop-original-merged',
  group_name: 'hardhat_headcrop_original_merged',
  split: 'VAL' as const,
}
const SPLIT_HEADCROP_VISIBLE_ADDED_VAL = {
  split_id: 's-headcrop-visible-added-val',
  group_id: 'g-hardhat-headcrop-visible-added',
  group_name: 'hardhat_headcrop_visible_added',
  split: 'VAL' as const,
}

const SPLIT_VEHICLE_SOURCE_VAL = {
  split_id: 's-vehicle-source-val',
  group_id: 'g-vehicle-detection-source',
  group_name: 'vehicle_detection_source',
  split: 'VAL' as const,
}
const SPLIT_VEHICLE_PROCESSED_VAL = {
  split_id: 's-vehicle-processed-val',
  group_id: 'g-vehicle-detection-processed',
  group_name: 'vehicle_detection_processed',
  split: 'VAL' as const,
}

const SPLIT_CYCLE_A_TRAIN = {
  split_id: 's-cycle-a-train',
  group_id: 'g-cycle-demo-a',
  group_name: 'cycle_demo_group_a',
  split: 'TRAIN' as const,
}
const SPLIT_CYCLE_B_TRAIN = {
  split_id: 's-cycle-b-train',
  group_id: 'g-cycle-demo-b',
  group_name: 'cycle_demo_group_b',
  split: 'TRAIN' as const,
}

const SPLIT_PERSON_RAW_TRAIN = {
  split_id: 's-person-raw-train',
  group_id: 'g-person-detection-raw',
  group_name: 'person_detection_raw',
  split: 'TRAIN' as const,
}
const SPLIT_PERSON_COCO_TRAIN = {
  split_id: 's-person-coco-train',
  group_id: 'g-person-detection-coco',
  group_name: 'person_detection_coco',
  split: 'TRAIN' as const,
}

// =============================================================================
// PipelineFamily fixture (3건 + 미분류)
// =============================================================================

export const MOCK_FAMILIES: PipelineFamily[] = [
  {
    id: 'f-hardhat-cls',
    name: 'hardhat_classification',
    description: '안전모 착용 / 가시성 classification 계열',
    color: '#ec407a',
    pipeline_count: 2,
    created_at: '2026-04-10T08:30:00Z',
    updated_at: '2026-04-25T11:00:00Z',
  },
  {
    id: 'f-vehicle-det',
    name: 'safety_detection',
    description: '차량 / 사람 detection 계열',
    color: '#42a5f5',
    pipeline_count: 1,
    created_at: '2026-04-12T09:00:00Z',
    updated_at: '2026-04-29T18:20:00Z',
  },
  {
    id: 'f-cycle-demo',
    name: 'cycle_demo',
    description: '사이클 감지 시연용 — 의도적 순환',
    color: '#ffb74d',
    pipeline_count: 2,
    created_at: '2026-04-18T11:50:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },
]

// =============================================================================
// Pipeline (concept) fixture — 6건
// =============================================================================

const TASKS_HELMET_MERGE_V1: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'cls_reorder_heads', display_name: 'head 순서 정렬' },
  { task_id: 't2', operator: 'cls_merge_datasets', display_name: 'datasets merge' },
]
const TASKS_HELMET_MERGE_V2: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'cls_reorder_heads', display_name: 'head 순서 정렬' },
  { task_id: 't2', operator: 'cls_filter_by_class', display_name: 'unknown 라벨 제거' },
  { task_id: 't3', operator: 'cls_merge_datasets', display_name: 'datasets merge' },
]
const TASKS_VISIBLE_UPDATE: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'cls_add_head', display_name: 'visibility head 추가' },
  {
    task_id: 't2',
    operator: 'cls_set_head_labels_for_all_images',
    display_name: 'visibility=1_seen 일괄 세팅',
  },
]
const TASKS_VEHICLE_AUGMENT_V1: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'det_rotate_image', display_name: 'rotate 180°' },
  { task_id: 't2', operator: 'det_mask_region_by_class', display_name: 'mask class region' },
]
const TASKS_VEHICLE_AUGMENT_V2: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'det_rotate_image', display_name: 'rotate 90°' },
  { task_id: 't2', operator: 'det_mask_region_by_class', display_name: 'mask class region' },
  { task_id: 't3', operator: 'det_sample_n_images', display_name: 'sample N=2000' },
]
const TASKS_CYCLE_AB: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'det_remap_class_name', display_name: 'class remap' },
]
const TASKS_CYCLE_BA: PipelineTaskSummary[] = [
  { task_id: 't1', operator: 'det_sample_n_images', display_name: 'sample N=500' },
]
const TASKS_PERSON_CONVERT: PipelineTaskSummary[] = [
  {
    task_id: 't1',
    operator: 'det_format_convert_to_coco',
    display_name: 'format convert to COCO',
  },
]

export const MOCK_CONCEPTS: PipelineConcept[] = [
  // ─ C1: helmet_merge — version 진화 시연 (v1.0 manual + v2.0 automation triggering)
  {
    id: 'c-helmet-merge',
    family_id: 'f-hardhat-cls',
    family_name: 'hardhat_classification',
    family_color: '#ec407a',
    name: 'helmet_merge',
    description: 'RAW head crop 이미지들을 정렬·merge 해 SOURCE 그룹으로 승격',
    task_type: 'CLASSIFICATION',
    output: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL,
    is_active: true,
    latest_active_version_id: 'v-helmet-merge-2',
    latest_active_version: '2.0',
    version_count: 2,
    created_at: '2026-04-10T09:00:00Z',
    updated_at: '2026-04-25T11:00:00Z',
  },
  // ─ C2: helmet_visible_update — 정상 chaining (C1.v2.0 출력 → 상류)
  {
    id: 'c-helmet-visible',
    family_id: 'f-hardhat-cls',
    family_name: 'hardhat_classification',
    family_color: '#ec407a',
    name: 'helmet_visible_update',
    description: 'original_merged 에 visibility head 를 주입해 visible_added 파생',
    task_type: 'CLASSIFICATION',
    output: SPLIT_HEADCROP_VISIBLE_ADDED_VAL,
    is_active: true,
    latest_active_version_id: 'v-helmet-visible-1',
    latest_active_version: '1.0',
    version_count: 1,
    created_at: '2026-04-11T11:20:00Z',
    updated_at: '2026-04-25T15:10:00Z',
  },
  // ─ C3: vehicle_augment — Reassign hint 시연 (v1 automation, v2 미등록)
  {
    id: 'c-vehicle-augment',
    family_id: 'f-vehicle-det',
    family_name: 'safety_detection',
    family_color: '#42a5f5',
    name: 'vehicle_augment',
    description: 'SOURCE 에 rotate + mask augmentation 적용. v2.0 부터 sample 추가',
    task_type: 'DETECTION',
    output: SPLIT_VEHICLE_PROCESSED_VAL,
    is_active: true,
    latest_active_version_id: 'v-vehicle-augment-2',
    latest_active_version: '2.0',
    version_count: 2,
    created_at: '2026-04-12T09:00:00Z',
    updated_at: '2026-04-29T18:20:00Z',
  },
  // ─ C4 / C5: 사이클 데모
  {
    id: 'c-cycle-a-to-b',
    family_id: 'f-cycle-demo',
    family_name: 'cycle_demo',
    family_color: '#ffb74d',
    name: 'cycle_demo_a_to_b',
    description: '(사이클 데모) A → B',
    task_type: 'DETECTION',
    output: SPLIT_CYCLE_B_TRAIN,
    is_active: true,
    latest_active_version_id: 'v-cycle-a-to-b-1',
    latest_active_version: '1.0',
    version_count: 1,
    created_at: '2026-04-18T12:00:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },
  {
    id: 'c-cycle-b-to-a',
    family_id: 'f-cycle-demo',
    family_name: 'cycle_demo',
    family_color: '#ffb74d',
    name: 'cycle_demo_b_to_a',
    description: '(사이클 데모) B → A',
    task_type: 'DETECTION',
    output: SPLIT_CYCLE_A_TRAIN,
    is_active: true,
    latest_active_version_id: 'v-cycle-b-to-a-1',
    latest_active_version: '1.0',
    version_count: 1,
    created_at: '2026-04-18T12:05:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },
  // ─ C6: person_detection_raw_to_coco — Family 미배정 + automation 미등록
  {
    id: 'c-person-convert',
    family_id: null,
    family_name: null,
    family_color: null,
    name: 'person_detection_raw_to_coco',
    description: 'person detection RAW 를 COCO 로 포맷 변환',
    task_type: 'DETECTION',
    output: SPLIT_PERSON_COCO_TRAIN,
    is_active: true,
    latest_active_version_id: 'v-person-convert-1',
    latest_active_version: '1.0',
    version_count: 1,
    created_at: '2026-04-05T09:00:00Z',
    updated_at: '2026-04-15T10:22:18Z',
  },
]

// =============================================================================
// PipelineAutomation fixture — 4건 (v2 만 active, v1 은 미등록 / 사이클은 error)
// =============================================================================

/** C1.v2.0 — triggering, active */
const AUTOMATION_HELMET_MERGE_V2: PipelineAutomation = {
  id: 'a-helmet-merge-v2',
  pipeline_version_id: 'v-helmet-merge-2',
  status: 'active',
  mode: 'triggering',
  poll_interval: null,
  error_reason: null,
  last_seen_input_versions: { [SPLIT_HEADCROP_RAW_VAL.split_id]: '2.0' },
  is_active: true,
  deleted_at: null,
  next_scheduled_at: null,
  last_dispatched_at: '2026-04-22T14:30:02Z',
  created_at: '2026-04-25T10:30:00Z',
  updated_at: '2026-04-25T10:30:00Z',
}

/** C2.v1.0 — polling 1h, active */
const AUTOMATION_HELMET_VISIBLE_V1: PipelineAutomation = {
  id: 'a-helmet-visible-v1',
  pipeline_version_id: 'v-helmet-visible-1',
  status: 'active',
  mode: 'polling',
  poll_interval: '1h',
  error_reason: null,
  last_seen_input_versions: { [SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.split_id]: '3.0' },
  is_active: true,
  deleted_at: null,
  next_scheduled_at: '2026-04-30T17:00:00Z',
  last_dispatched_at: '2026-04-22T14:48:10Z',
  created_at: '2026-04-15T11:30:00Z',
  updated_at: '2026-04-22T15:00:04Z',
}

/** C3.v1.0 — polling 6h, active. v2.0 가 새로 만들어졌지만 automation 은 v1.0 에 그대로 (§12-6 hint 대상) */
const AUTOMATION_VEHICLE_AUGMENT_V1: PipelineAutomation = {
  id: 'a-vehicle-augment-v1',
  pipeline_version_id: 'v-vehicle-augment-1',
  status: 'active',
  mode: 'polling',
  poll_interval: '6h',
  error_reason: null,
  last_seen_input_versions: { [SPLIT_VEHICLE_SOURCE_VAL.split_id]: '1.2' },
  is_active: true,
  deleted_at: null,
  next_scheduled_at: '2026-04-30T22:00:00Z',
  last_dispatched_at: '2026-04-23T06:15:00Z',
  created_at: '2026-04-12T09:30:00Z',
  updated_at: '2026-04-23T06:15:00Z',
}

/** C4.v1.0 — polling 10m, error: CYCLE_DETECTED */
const AUTOMATION_CYCLE_AB_V1: PipelineAutomation = {
  id: 'a-cycle-a-to-b-v1',
  pipeline_version_id: 'v-cycle-a-to-b-1',
  status: 'error',
  mode: 'polling',
  poll_interval: '10m',
  error_reason: 'CYCLE_DETECTED',
  last_seen_input_versions: { [SPLIT_CYCLE_A_TRAIN.split_id]: '1.0' },
  is_active: true,
  deleted_at: null,
  next_scheduled_at: null,
  last_dispatched_at: '2026-04-20T08:00:00Z',
  created_at: '2026-04-18T12:00:00Z',
  updated_at: '2026-04-21T09:00:00Z',
}

/** C5.v1.0 — triggering, error: CYCLE_DETECTED */
const AUTOMATION_CYCLE_BA_V1: PipelineAutomation = {
  id: 'a-cycle-b-to-a-v1',
  pipeline_version_id: 'v-cycle-b-to-a-1',
  status: 'error',
  mode: 'triggering',
  poll_interval: null,
  error_reason: 'CYCLE_DETECTED',
  last_seen_input_versions: { [SPLIT_CYCLE_B_TRAIN.split_id]: '1.0' },
  is_active: true,
  deleted_at: null,
  next_scheduled_at: null,
  last_dispatched_at: '2026-04-20T08:05:00Z',
  created_at: '2026-04-18T12:05:00Z',
  updated_at: '2026-04-21T09:00:00Z',
}

export const MOCK_AUTOMATIONS: PipelineAutomation[] = [
  AUTOMATION_HELMET_MERGE_V2,
  AUTOMATION_HELMET_VISIBLE_V1,
  AUTOMATION_VEHICLE_AUGMENT_V1,
  AUTOMATION_CYCLE_AB_V1,
  AUTOMATION_CYCLE_BA_V1,
]

// =============================================================================
// PipelineVersion fixture — 8건 (concept 6 + version 진화 2)
// =============================================================================

export const MOCK_VERSIONS: PipelineVersion[] = [
  // ─ C1.v1.0 — 초기 manual run, automation 없음 (자연스럽게 "구버전")
  {
    id: 'v-helmet-merge-1',
    pipeline_id: 'c-helmet-merge',
    pipeline_name: 'helmet_merge',
    version: '1.0',
    description: '최초 등록 — 단순 merge',
    is_active: true,
    task_summaries: TASKS_HELMET_MERGE_V1,
    input_splits: [SPLIT_HEADCROP_RAW_VAL],
    automation: null,
    last_run_at: '2026-04-10T09:51:20Z',
    run_count: 1,
    created_at: '2026-04-10T09:00:00Z',
    updated_at: '2026-04-10T09:51:20Z',
  },
  // ─ C1.v2.0 — automation triggering ✅
  {
    id: 'v-helmet-merge-2',
    pipeline_id: 'c-helmet-merge',
    pipeline_name: 'helmet_merge',
    version: '2.0',
    description: 'unknown 라벨 제거 단계 추가. automation 도 v2.0 으로 이동',
    is_active: true,
    task_summaries: TASKS_HELMET_MERGE_V2,
    input_splits: [SPLIT_HEADCROP_RAW_VAL],
    automation: AUTOMATION_HELMET_MERGE_V2,
    last_run_at: '2026-04-22T14:47:55Z',
    run_count: 2,
    created_at: '2026-04-25T10:00:00Z',
    updated_at: '2026-04-25T11:00:00Z',
  },
  // ─ C2.v1.0 — automation polling 1h ✅
  {
    id: 'v-helmet-visible-1',
    pipeline_id: 'c-helmet-visible',
    pipeline_name: 'helmet_visible_update',
    version: '1.0',
    description: null,
    is_active: true,
    task_summaries: TASKS_VISIBLE_UPDATE,
    input_splits: [SPLIT_HEADCROP_ORIGINAL_MERGED_VAL],
    automation: AUTOMATION_HELMET_VISIBLE_V1,
    last_run_at: '2026-04-22T15:00:04Z',
    run_count: 1,
    created_at: '2026-04-11T11:20:00Z',
    updated_at: '2026-04-22T15:00:04Z',
  },
  // ─ C3.v1.0 — automation polling 6h ✅ (v2.0 가 별도 존재 → §12-6 hint 발급 대상)
  {
    id: 'v-vehicle-augment-1',
    pipeline_id: 'c-vehicle-augment',
    pipeline_name: 'vehicle_augment',
    version: '1.0',
    description: 'rotate + mask 만 적용',
    is_active: true,
    task_summaries: TASKS_VEHICLE_AUGMENT_V1,
    input_splits: [SPLIT_VEHICLE_SOURCE_VAL],
    automation: AUTOMATION_VEHICLE_AUGMENT_V1,
    last_run_at: '2026-04-23T06:15:00Z',
    run_count: 3,
    created_at: '2026-04-12T09:00:00Z',
    updated_at: '2026-04-23T06:15:00Z',
  },
  // ─ C3.v2.0 — automation 미등록 (사용자가 reassign 결정 대기 중)
  {
    id: 'v-vehicle-augment-2',
    pipeline_id: 'c-vehicle-augment',
    pipeline_name: 'vehicle_augment',
    version: '2.0',
    description: 'sample 단계 추가 — 학습 부담 절감 목적',
    is_active: true,
    task_summaries: TASKS_VEHICLE_AUGMENT_V2,
    input_splits: [SPLIT_VEHICLE_SOURCE_VAL],
    automation: null,
    last_run_at: null,
    run_count: 0,
    created_at: '2026-04-29T18:20:00Z',
    updated_at: '2026-04-29T18:20:00Z',
  },
  // ─ C4.v1.0 — 사이클 (CYCLE_DETECTED)
  {
    id: 'v-cycle-a-to-b-1',
    pipeline_id: 'c-cycle-a-to-b',
    pipeline_name: 'cycle_demo_a_to_b',
    version: '1.0',
    description: null,
    is_active: true,
    task_summaries: TASKS_CYCLE_AB,
    input_splits: [SPLIT_CYCLE_A_TRAIN],
    automation: AUTOMATION_CYCLE_AB_V1,
    last_run_at: '2026-04-20T08:04:00Z',
    run_count: 1,
    created_at: '2026-04-18T12:00:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },
  // ─ C5.v1.0 — 사이클
  {
    id: 'v-cycle-b-to-a-1',
    pipeline_id: 'c-cycle-b-to-a',
    pipeline_name: 'cycle_demo_b_to_a',
    version: '1.0',
    description: null,
    is_active: true,
    task_summaries: TASKS_CYCLE_BA,
    input_splits: [SPLIT_CYCLE_B_TRAIN],
    automation: AUTOMATION_CYCLE_BA_V1,
    last_run_at: '2026-04-20T08:08:30Z',
    run_count: 1,
    created_at: '2026-04-18T12:05:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },
  // ─ C6.v1.0 — automation 미등록, manual run 1건만
  {
    id: 'v-person-convert-1',
    pipeline_id: 'c-person-convert',
    pipeline_name: 'person_detection_raw_to_coco',
    version: '1.0',
    description: null,
    is_active: true,
    task_summaries: TASKS_PERSON_CONVERT,
    input_splits: [SPLIT_PERSON_RAW_TRAIN],
    automation: null,
    last_run_at: '2026-04-15T10:22:18Z',
    run_count: 1,
    created_at: '2026-04-05T09:00:00Z',
    updated_at: '2026-04-15T10:22:18Z',
  },
]

// =============================================================================
// PipelineRun fixture — 9건
// =============================================================================

export const MOCK_RUNS: PipelineRun[] = [
  // ─ C3.v1.0 수동 재실행 — 변경사항 없어 SKIPPED_NO_DELTA (가장 최근)
  {
    id: 'r-vehicle-augment-v1-rerun',
    pipeline_version_id: 'v-vehicle-augment-1',
    pipeline_name: 'vehicle_augment',
    pipeline_version: '1.0',
    automation_id: 'a-vehicle-augment-v1',
    status: 'SKIPPED_NO_DELTA',
    trigger_kind: 'automation_manual_rerun',
    automation_trigger_source: 'manual_rerun',
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_VEHICLE_SOURCE_VAL.split_id]: '1.2' },
    triggered_input_versions_display: { 'vehicle_detection_source (VAL)': '1.2' },
    output_dataset_version_id: null,
    output_dataset_version: null,
    output_dataset_group_name: null,
    output_dataset_split: null,
    started_at: '2026-04-23T06:15:00Z',
    finished_at: '2026-04-23T06:15:01Z',
    created_at: '2026-04-23T06:15:00Z',
    duration_seconds: 1,
    error_message: null,
  },

  // ─ C1.v2.0 → C2.v1.0 자동 chaining batch (triggering)
  {
    id: 'r-helmet-visible-v1-batch',
    pipeline_version_id: 'v-helmet-visible-1',
    pipeline_name: 'helmet_visible_update',
    pipeline_version: '1.0',
    automation_id: 'a-helmet-visible-v1',
    status: 'DONE',
    trigger_kind: 'automation_auto',
    automation_trigger_source: 'triggering',
    automation_batch_id: 'b-20260422-1430',
    resolved_input_versions: { [SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.split_id]: '3.0' },
    triggered_input_versions_display: { 'hardhat_headcrop_original_merged (VAL)': '3.0' },
    output_dataset_version_id: 'dv-headcrop-visible-2.1',
    output_dataset_version: '2.1',
    output_dataset_group_name: 'hardhat_headcrop_visible_added',
    output_dataset_split: 'VAL',
    started_at: '2026-04-22T14:48:10Z',
    finished_at: '2026-04-22T15:00:04Z',
    created_at: '2026-04-22T14:48:10Z',
    duration_seconds: 714,
    error_message: null,
  },
  {
    id: 'r-helmet-merge-v2-batch',
    pipeline_version_id: 'v-helmet-merge-2',
    pipeline_name: 'helmet_merge',
    pipeline_version: '2.0',
    automation_id: 'a-helmet-merge-v2',
    status: 'DONE',
    trigger_kind: 'automation_auto',
    automation_trigger_source: 'triggering',
    automation_batch_id: 'b-20260422-1430',
    resolved_input_versions: { [SPLIT_HEADCROP_RAW_VAL.split_id]: '2.0' },
    triggered_input_versions_display: { 'hardhat_headcrop_raw (VAL)': '2.0' },
    output_dataset_version_id: 'dv-headcrop-original-merged-3.0',
    output_dataset_version: '3.0',
    output_dataset_group_name: 'hardhat_headcrop_original_merged',
    output_dataset_split: 'VAL',
    started_at: '2026-04-22T14:30:02Z',
    finished_at: '2026-04-22T14:47:55Z',
    created_at: '2026-04-22T14:30:02Z',
    duration_seconds: 1073,
    error_message: null,
  },

  // ─ C3.v1.0 polling 자동 실행 (직전 정상)
  {
    id: 'r-vehicle-augment-v1-polling',
    pipeline_version_id: 'v-vehicle-augment-1',
    pipeline_name: 'vehicle_augment',
    pipeline_version: '1.0',
    automation_id: 'a-vehicle-augment-v1',
    status: 'DONE',
    trigger_kind: 'automation_auto',
    automation_trigger_source: 'polling',
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_VEHICLE_SOURCE_VAL.split_id]: '1.2' },
    triggered_input_versions_display: { 'vehicle_detection_source (VAL)': '1.2' },
    output_dataset_version_id: 'dv-vehicle-processed-1.3',
    output_dataset_version: '1.3',
    output_dataset_group_name: 'vehicle_detection_processed',
    output_dataset_split: 'VAL',
    started_at: '2026-04-22T20:00:00Z',
    finished_at: '2026-04-22T20:12:40Z',
    created_at: '2026-04-22T20:00:00Z',
    duration_seconds: 760,
    error_message: null,
  },
  // ─ C3.v1.0 초기 manual_from_editor (automation 등록 전 검증 실행)
  {
    id: 'r-vehicle-augment-v1-initial',
    pipeline_version_id: 'v-vehicle-augment-1',
    pipeline_name: 'vehicle_augment',
    pipeline_version: '1.0',
    automation_id: null,
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_VEHICLE_SOURCE_VAL.split_id]: '1.0' },
    triggered_input_versions_display: { 'vehicle_detection_source (VAL)': '1.0' },
    output_dataset_version_id: 'dv-vehicle-processed-1.0',
    output_dataset_version: '1.0',
    output_dataset_group_name: 'vehicle_detection_processed',
    output_dataset_split: 'VAL',
    started_at: '2026-04-12T10:00:00Z',
    finished_at: '2026-04-12T10:12:30Z',
    created_at: '2026-04-12T10:00:00Z',
    duration_seconds: 750,
    error_message: null,
  },

  // ─ C4.v1.0 사이클 감지 전 manual run
  {
    id: 'r-cycle-a-to-b-pre',
    pipeline_version_id: 'v-cycle-a-to-b-1',
    pipeline_name: 'cycle_demo_a_to_b',
    pipeline_version: '1.0',
    automation_id: null,
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_CYCLE_A_TRAIN.split_id]: '1.0' },
    triggered_input_versions_display: { 'cycle_demo_group_a (TRAIN)': '1.0' },
    output_dataset_version_id: 'dv-cycle-b-1.0',
    output_dataset_version: '1.0',
    output_dataset_group_name: 'cycle_demo_group_b',
    output_dataset_split: 'TRAIN',
    started_at: '2026-04-20T08:00:00Z',
    finished_at: '2026-04-20T08:04:00Z',
    created_at: '2026-04-20T08:00:00Z',
    duration_seconds: 240,
    error_message: null,
  },
  // ─ C5.v1.0 사이클 감지 전 manual run
  {
    id: 'r-cycle-b-to-a-pre',
    pipeline_version_id: 'v-cycle-b-to-a-1',
    pipeline_name: 'cycle_demo_b_to_a',
    pipeline_version: '1.0',
    automation_id: null,
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_CYCLE_B_TRAIN.split_id]: '1.0' },
    triggered_input_versions_display: { 'cycle_demo_group_b (TRAIN)': '1.0' },
    output_dataset_version_id: 'dv-cycle-a-2.0',
    output_dataset_version: '2.0',
    output_dataset_group_name: 'cycle_demo_group_a',
    output_dataset_split: 'TRAIN',
    started_at: '2026-04-20T08:05:00Z',
    finished_at: '2026-04-20T08:08:30Z',
    created_at: '2026-04-20T08:05:00Z',
    duration_seconds: 210,
    error_message: null,
  },

  // ─ C6.v1.0 manual_from_editor (automation 미등록)
  {
    id: 'r-person-convert-v1',
    pipeline_version_id: 'v-person-convert-1',
    pipeline_name: 'person_detection_raw_to_coco',
    pipeline_version: '1.0',
    automation_id: null,
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_PERSON_RAW_TRAIN.split_id]: '1.0' },
    triggered_input_versions_display: { 'person_detection_raw (TRAIN)': '1.0' },
    output_dataset_version_id: 'dv-person-coco-1.0',
    output_dataset_version: '1.0',
    output_dataset_group_name: 'person_detection_coco',
    output_dataset_split: 'TRAIN',
    started_at: '2026-04-15T10:00:00Z',
    finished_at: '2026-04-15T10:22:18Z',
    created_at: '2026-04-15T10:00:00Z',
    duration_seconds: 1338,
    error_message: null,
  },

  // ─ C1.v1.0 초기 manual run (automation 활성 이전, 별 concept 의 다른 version)
  {
    id: 'r-helmet-merge-v1-initial',
    pipeline_version_id: 'v-helmet-merge-1',
    pipeline_name: 'helmet_merge',
    pipeline_version: '1.0',
    automation_id: null,
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    resolved_input_versions: { [SPLIT_HEADCROP_RAW_VAL.split_id]: '1.0' },
    triggered_input_versions_display: { 'hardhat_headcrop_raw (VAL)': '1.0' },
    output_dataset_version_id: 'dv-headcrop-merge-1.0',
    output_dataset_version: '1.0',
    output_dataset_group_name: 'hardhat_headcrop_original_merged',
    output_dataset_split: 'VAL',
    started_at: '2026-04-10T09:30:00Z',
    finished_at: '2026-04-10T09:51:20Z',
    created_at: '2026-04-10T09:30:00Z',
    duration_seconds: 1280,
    error_message: null,
  },
]

// =============================================================================
// ExecutionBatch fixture — 토폴로지 순서 묶음
// =============================================================================

export const MOCK_EXECUTION_BATCHES: ExecutionBatch[] = [
  {
    batch_id: 'b-20260422-1430',
    trigger_source: 'triggering',
    created_at: '2026-04-22T14:30:02Z',
    runs: [
      // 토폴로지 순서: C1.v2.0 (helmet_merge) 먼저 → 그 출력이 C2.v1.0 (helmet_visible_update) 의 입력
      MOCK_RUNS.find((run) => run.id === 'r-helmet-merge-v2-batch')!,
      MOCK_RUNS.find((run) => run.id === 'r-helmet-visible-v1-batch')!,
    ],
  },
]

// =============================================================================
// Chaining DAG fixture — PipelineVersion 단위
// =============================================================================

const buildChainingNodeFromVersion = (
  version: PipelineVersion,
  inCycleVersionIds: ReadonlySet<string>,
): ChainingNode => {
  const concept = MOCK_CONCEPTS.find((c) => c.id === version.pipeline_id)
  if (!concept) {
    throw new Error(`fixture inconsistency: concept not found for ${version.pipeline_id}`)
  }
  return {
    pipeline_version_id: version.id,
    pipeline_id: concept.id,
    pipeline_name: concept.name,
    pipeline_version: version.version,
    task_type: concept.task_type,
    family_id: concept.family_id,
    family_name: concept.family_name,
    family_color: concept.family_color,
    automation_status: version.automation?.status ?? 'stopped',
    automation_error_reason: version.automation?.error_reason ?? null,
    in_cycle: inCycleVersionIds.has(version.id),
  }
}

const CYCLE_VERSION_IDS = new Set(['v-cycle-a-to-b-1', 'v-cycle-b-to-a-1'])

/**
 * DAG 에 포함시킬 version 정책:
 *  - automation 이 stopped 가 아니거나 (active / error)
 *  - run_count > 0 (한 번이라도 실행된 적 있음)
 * 둘 중 하나라도 만족하면 포함. C3.v2.0 같은 "automation 미등록 + run 0 건" version 은 제외 — 표시할
 * chaining 정보가 없다.
 */
const VISIBLE_VERSIONS_FOR_DAG: PipelineVersion[] = MOCK_VERSIONS.filter(
  (version) =>
    (version.automation && version.automation.status !== 'stopped') || version.run_count > 0,
)

const CHAINING_NODES: ChainingNode[] = VISIBLE_VERSIONS_FOR_DAG.map((version) =>
  buildChainingNodeFromVersion(version, CYCLE_VERSION_IDS),
)

const CHAINING_EDGES: ChainingEdge[] = [
  // 정상 chaining: C1.v2.0 출력 → C2.v1.0 입력 (hardhat_headcrop_original_merged / VAL)
  {
    source_version_id: 'v-helmet-merge-2',
    target_version_id: 'v-helmet-visible-1',
    via_split_id: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.split_id,
    via_group_id: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.group_id,
    via_group_name: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.group_name,
    via_split: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.split,
    in_cycle: false,
  },
  // 사이클: C4.v1.0 → C5.v1.0
  {
    source_version_id: 'v-cycle-a-to-b-1',
    target_version_id: 'v-cycle-b-to-a-1',
    via_split_id: SPLIT_CYCLE_B_TRAIN.split_id,
    via_group_id: SPLIT_CYCLE_B_TRAIN.group_id,
    via_group_name: SPLIT_CYCLE_B_TRAIN.group_name,
    via_split: SPLIT_CYCLE_B_TRAIN.split,
    in_cycle: true,
  },
  // 사이클: C5.v1.0 → C4.v1.0
  {
    source_version_id: 'v-cycle-b-to-a-1',
    target_version_id: 'v-cycle-a-to-b-1',
    via_split_id: SPLIT_CYCLE_A_TRAIN.split_id,
    via_group_id: SPLIT_CYCLE_A_TRAIN.group_id,
    via_group_name: SPLIT_CYCLE_A_TRAIN.group_name,
    via_split: SPLIT_CYCLE_A_TRAIN.split,
    in_cycle: true,
  },
]

export const MOCK_CHAINING_GRAPH: ChainingGraph = {
  nodes: CHAINING_NODES,
  edges: CHAINING_EDGES,
  cycles: [['v-cycle-a-to-b-1', 'v-cycle-b-to-a-1']],
}

// =============================================================================
// Upstream Split delta fixture — version 단위
// =============================================================================

/** key = pipeline_version_id */
export const MOCK_UPSTREAM_DELTAS: Record<string, UpstreamSplitDelta[]> = {
  'v-helmet-merge-2': [
    {
      split_id: SPLIT_HEADCROP_RAW_VAL.split_id,
      group_id: SPLIT_HEADCROP_RAW_VAL.group_id,
      group_name: SPLIT_HEADCROP_RAW_VAL.group_name,
      split: SPLIT_HEADCROP_RAW_VAL.split,
      latest_version: '2.1',
      last_seen_version: '2.0',
      has_delta: true,
    },
  ],
  'v-helmet-visible-1': [
    {
      split_id: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.split_id,
      group_id: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.group_id,
      group_name: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.group_name,
      split: SPLIT_HEADCROP_ORIGINAL_MERGED_VAL.split,
      latest_version: '3.0',
      last_seen_version: '3.0',
      has_delta: false,
    },
  ],
  'v-vehicle-augment-1': [
    {
      split_id: SPLIT_VEHICLE_SOURCE_VAL.split_id,
      group_id: SPLIT_VEHICLE_SOURCE_VAL.group_id,
      group_name: SPLIT_VEHICLE_SOURCE_VAL.group_name,
      split: SPLIT_VEHICLE_SOURCE_VAL.split,
      latest_version: '1.2',
      last_seen_version: '1.2',
      has_delta: false,
    },
  ],
  'v-vehicle-augment-2': [
    {
      split_id: SPLIT_VEHICLE_SOURCE_VAL.split_id,
      group_id: SPLIT_VEHICLE_SOURCE_VAL.group_id,
      group_name: SPLIT_VEHICLE_SOURCE_VAL.group_name,
      split: SPLIT_VEHICLE_SOURCE_VAL.split,
      latest_version: '1.2',
      last_seen_version: null,
      has_delta: true,
    },
  ],
  'v-cycle-a-to-b-1': [
    {
      split_id: SPLIT_CYCLE_A_TRAIN.split_id,
      group_id: SPLIT_CYCLE_A_TRAIN.group_id,
      group_name: SPLIT_CYCLE_A_TRAIN.group_name,
      split: SPLIT_CYCLE_A_TRAIN.split,
      latest_version: '1.0',
      last_seen_version: '1.0',
      has_delta: false,
    },
  ],
  'v-cycle-b-to-a-1': [
    {
      split_id: SPLIT_CYCLE_B_TRAIN.split_id,
      group_id: SPLIT_CYCLE_B_TRAIN.group_id,
      group_name: SPLIT_CYCLE_B_TRAIN.group_name,
      split: SPLIT_CYCLE_B_TRAIN.split,
      latest_version: '1.0',
      last_seen_version: '1.0',
      has_delta: false,
    },
  ],
  'v-person-convert-1': [
    {
      split_id: SPLIT_PERSON_RAW_TRAIN.split_id,
      group_id: SPLIT_PERSON_RAW_TRAIN.group_id,
      group_name: SPLIT_PERSON_RAW_TRAIN.group_name,
      split: SPLIT_PERSON_RAW_TRAIN.split,
      latest_version: '1.1',
      last_seen_version: null,
      has_delta: true,
    },
  ],
}
