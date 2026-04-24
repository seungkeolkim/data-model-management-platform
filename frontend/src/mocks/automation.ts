/**
 * Automation 목업 fixture (023 §9-1 — 프론트 상수 하드코딩 A 안).
 *
 * 백엔드를 전혀 건드리지 않는다. Automation 페이지 / 상세 탭 / 실행 이력 개편이 이 상수를 직접 import 하며,
 * `api/automation.ts` 의 비동기 wrapper 함수들이 Promise 로 감싸 반환한다 — 추후 실 API 로 전환할 때
 * api 레이어만 교체하면 된다.
 *
 * 시나리오 구성:
 *   ① P1 → P2 정상 체인 (hardhat_headcrop 가계열) — 연쇄 trigger 시연
 *      P1: RAW → hardhat_headcrop_original_merged      (triggering, active)
 *      P2: hardhat_headcrop_original_merged → visible_added (polling 1h, active)
 *   ② P3 ↔ P4 사이클 (group_a ↔ group_b) — CYCLE_DETECTED / error 상태
 *   ③ P5 stopped — 한 번도 활성된 적 없음
 *   ④ P6 수동 재실행 no-delta skip 시연
 *
 * 테스트용 참고 DatasetVersion ID (사용자 제공, 023 §9-10 / 025 §7-2-8 계보):
 *   - hardhat_headcrop_visible_added    : 83f76037-df56-4575-a343-2ade37299225
 *   - hardhat_headcrop_original_merged  : 4d2afb95-f7e6-4297-afff-6c435b9af9cf
 */
import type {
  Pipeline,
  ChainingGraph,
  PipelineExecutionSummary,
  ExecutionBatch,
  UpstreamGroupDelta,
} from '@/types/automation'

// =============================================================================
// DatasetGroup 참조 상수 — fixture 내부에서 이름 오타 방지용
// =============================================================================

const GROUP_HEADCROP_RAW = {
  group_id: 'grp-hardhat-headcrop-raw-0001',
  group_name: 'hardhat_headcrop_raw',
}
const GROUP_HEADCROP_ORIGINAL_MERGED = {
  group_id: 'grp-hardhat-headcrop-original-merged',
  group_name: 'hardhat_headcrop_original_merged',
}
const GROUP_HEADCROP_VISIBLE_ADDED = {
  group_id: 'grp-hardhat-headcrop-visible-added',
  group_name: 'hardhat_headcrop_visible_added',
}

// 사이클 시연용
const GROUP_A = { group_id: 'grp-cycle-a-0001', group_name: 'cycle_demo_group_a' }
const GROUP_B = { group_id: 'grp-cycle-b-0002', group_name: 'cycle_demo_group_b' }

// stopped / 단발 시연용
const GROUP_PERSON_RAW = {
  group_id: 'grp-person-detection-raw',
  group_name: 'person_detection_raw',
}
const GROUP_PERSON_COCO = {
  group_id: 'grp-person-detection-coco',
  group_name: 'person_detection_coco',
}
const GROUP_VEHICLE_SOURCE = {
  group_id: 'grp-vehicle-source',
  group_name: 'vehicle_detection_source',
}
const GROUP_VEHICLE_PROCESSED = {
  group_id: 'grp-vehicle-processed',
  group_name: 'vehicle_detection_processed',
}

// =============================================================================
// Pipeline fixture
// =============================================================================

/**
 * 목업 파이프라인 6건.
 * ID 는 `pl-*` 접두어로 구분 (실 UUID 와 혼동 방지 — 목업 전용임을 시각적으로 드러냄).
 */
export const MOCK_PIPELINES: Pipeline[] = [
  // ── ① 정상 체인 ───────────────────────────────────────────────────────────
  {
    id: 'pl-headcrop-merge-0001',
    name: 'helmet_merge_nightly',
    description: 'RAW head crop 이미지들을 정렬·merge 해 SOURCE 그룹으로 승격',
    task_type: 'CLASSIFICATION',
    pipeline_template: { name: 'hardhat_headcrop_original_merge', version: '1.0' },
    input: { ...GROUP_HEADCROP_RAW, split: 'VAL' },
    output: { ...GROUP_HEADCROP_ORIGINAL_MERGED, split: 'VAL' },
    tasks: [
      { task_id: 't1', operator: 'cls_reorder_heads', display_name: 'head 순서 정렬' },
      { task_id: 't2', operator: 'cls_merge_datasets', display_name: 'datasets merge' },
    ],
    automation_status: 'active',
    automation_mode: 'triggering',
    automation_poll_interval: null,
    automation_error_reason: null,
    automation_last_seen_input_versions: { [GROUP_HEADCROP_RAW.group_id]: '2.0' },
    last_execution_at: '2026-04-22T14:32:11Z',
    next_scheduled_at: null,
    created_at: '2026-04-10T09:00:00Z',
    updated_at: '2026-04-22T14:32:11Z',
  },
  {
    id: 'pl-headcrop-visible-0002',
    name: 'helmet_visible_update',
    description: 'original_merged 에 visibility head 를 주입해 visible_added 파생',
    task_type: 'CLASSIFICATION',
    pipeline_template: { name: 'hardhat_headcrop_visible_add', version: '1.0' },
    input: { ...GROUP_HEADCROP_ORIGINAL_MERGED, split: 'VAL' },
    output: { ...GROUP_HEADCROP_VISIBLE_ADDED, split: 'VAL' },
    tasks: [
      { task_id: 't1', operator: 'cls_add_head', display_name: 'visibility head 추가' },
      {
        task_id: 't2',
        operator: 'cls_set_head_labels_for_all_images',
        display_name: 'visibility=1_seen 일괄 세팅',
      },
    ],
    automation_status: 'active',
    automation_mode: 'polling',
    automation_poll_interval: '1h',
    automation_error_reason: null,
    automation_last_seen_input_versions: { [GROUP_HEADCROP_ORIGINAL_MERGED.group_id]: '3.0' },
    last_execution_at: '2026-04-22T15:00:04Z',
    next_scheduled_at: '2026-04-23T10:00:00Z',
    created_at: '2026-04-11T11:20:00Z',
    updated_at: '2026-04-22T15:00:04Z',
  },

  // ── ② 사이클 ─────────────────────────────────────────────────────────────
  {
    id: 'pl-cycle-a-to-b-0003',
    name: 'cycle_demo_a_to_b',
    description: '(사이클 데모) A → B',
    task_type: 'DETECTION',
    pipeline_template: { name: 'cycle_demo_a_to_b', version: '1.0' },
    input: { ...GROUP_A, split: 'TRAIN' },
    output: { ...GROUP_B, split: 'TRAIN' },
    tasks: [{ task_id: 't1', operator: 'det_remap_class_name', display_name: 'class remap' }],
    automation_status: 'error',
    automation_mode: 'polling',
    automation_poll_interval: '10m',
    automation_error_reason: 'CYCLE_DETECTED',
    automation_last_seen_input_versions: { [GROUP_A.group_id]: '1.0' },
    last_execution_at: '2026-04-20T08:00:00Z',
    next_scheduled_at: null,
    created_at: '2026-04-18T12:00:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },
  {
    id: 'pl-cycle-b-to-a-0004',
    name: 'cycle_demo_b_to_a',
    description: '(사이클 데모) B → A',
    task_type: 'DETECTION',
    pipeline_template: { name: 'cycle_demo_b_to_a', version: '1.0' },
    input: { ...GROUP_B, split: 'TRAIN' },
    output: { ...GROUP_A, split: 'TRAIN' },
    tasks: [{ task_id: 't1', operator: 'det_sample_n_images', display_name: 'sample N' }],
    automation_status: 'error',
    automation_mode: 'triggering',
    automation_poll_interval: null,
    automation_error_reason: 'CYCLE_DETECTED',
    automation_last_seen_input_versions: { [GROUP_B.group_id]: '1.0' },
    last_execution_at: '2026-04-20T08:05:00Z',
    next_scheduled_at: null,
    created_at: '2026-04-18T12:05:00Z',
    updated_at: '2026-04-21T09:00:00Z',
  },

  // ── ③ stopped ────────────────────────────────────────────────────────────
  {
    id: 'pl-person-convert-0005',
    name: 'person_detection_raw_to_coco',
    description: 'person detection RAW 를 COCO 로 포맷 변환',
    task_type: 'DETECTION',
    pipeline_template: { name: 'person_detection_raw_to_coco', version: '1.0' },
    input: { ...GROUP_PERSON_RAW, split: 'TRAIN' },
    output: { ...GROUP_PERSON_COCO, split: 'TRAIN' },
    tasks: [
      {
        task_id: 't1',
        operator: 'det_format_convert_to_coco',
        display_name: 'format convert to COCO',
      },
    ],
    automation_status: 'stopped',
    automation_mode: null,
    automation_poll_interval: null,
    automation_error_reason: null,
    automation_last_seen_input_versions: {},
    last_execution_at: '2026-04-15T10:00:00Z',
    next_scheduled_at: null,
    created_at: '2026-04-05T09:00:00Z',
    updated_at: '2026-04-15T10:00:00Z',
  },

  // ── ④ 수동 재실행 no-delta skip 시연 ──────────────────────────────────────
  {
    id: 'pl-vehicle-augment-0006',
    name: 'vehicle_augment_v2_nightly',
    description: 'SOURCE 에 rotate + mask augmentation 적용',
    task_type: 'DETECTION',
    pipeline_template: { name: 'vehicle_detection_augment', version: '2.0' },
    input: { ...GROUP_VEHICLE_SOURCE, split: 'VAL' },
    output: { ...GROUP_VEHICLE_PROCESSED, split: 'VAL' },
    tasks: [
      { task_id: 't1', operator: 'det_rotate_image', display_name: 'rotate 180°' },
      { task_id: 't2', operator: 'det_mask_region_by_class', display_name: 'mask class region' },
    ],
    automation_status: 'active',
    automation_mode: 'polling',
    automation_poll_interval: '6h',
    automation_error_reason: null,
    automation_last_seen_input_versions: { [GROUP_VEHICLE_SOURCE.group_id]: '1.2' },
    last_execution_at: '2026-04-22T20:00:00Z',
    next_scheduled_at: '2026-04-23T14:00:00Z',
    created_at: '2026-04-12T09:00:00Z',
    updated_at: '2026-04-22T20:00:00Z',
  },
]

// =============================================================================
// Chaining 그래프 fixture
// =============================================================================

/**
 * stopped + 이력 0 건인 파이프라인은 DAG 에 그리지 않는다 (023 §9-6).
 * P5 (person_convert) 는 stopped 지만 이력이 있어 포함시킨다 — "이력 있으면 표시" 규칙 시연.
 * 현 fixture 기준 모든 6건이 이력을 갖도록 아래 MOCK_EXECUTIONS 를 설계했다.
 *
 * 엣지는 P1 → P2 정상 체인 1건 + P3 ↔ P4 사이클 2건 (양방향).
 */
export const MOCK_CHAINING_GRAPH: ChainingGraph = {
  nodes: MOCK_PIPELINES,
  edges: [
    {
      source_pipeline_id: 'pl-headcrop-merge-0001',
      target_pipeline_id: 'pl-headcrop-visible-0002',
      via_group_id: GROUP_HEADCROP_ORIGINAL_MERGED.group_id,
      via_group_name: GROUP_HEADCROP_ORIGINAL_MERGED.group_name,
      in_cycle: false,
    },
    {
      source_pipeline_id: 'pl-cycle-a-to-b-0003',
      target_pipeline_id: 'pl-cycle-b-to-a-0004',
      via_group_id: GROUP_B.group_id,
      via_group_name: GROUP_B.group_name,
      in_cycle: true,
    },
    {
      source_pipeline_id: 'pl-cycle-b-to-a-0004',
      target_pipeline_id: 'pl-cycle-a-to-b-0003',
      via_group_id: GROUP_A.group_id,
      via_group_name: GROUP_A.group_name,
      in_cycle: true,
    },
  ],
  cycles: [['pl-cycle-a-to-b-0003', 'pl-cycle-b-to-a-0004']],
}

// =============================================================================
// PipelineExecution fixture
// =============================================================================

/**
 * 실행 이력. batch_id 로 묶인 연쇄 실행 체인 1건 + 단발 실행 여러 건 + no-delta skip 1건.
 * 시간은 최신이 앞 — UI 에서 started_at desc 로 내려받는다고 가정.
 */
export const MOCK_EXECUTIONS: PipelineExecutionSummary[] = [
  // ④ P6 수동 재실행 — 변경사항 없어 skip
  {
    id: 'exec-p6-rerun-nodelta',
    pipeline_id: 'pl-vehicle-augment-0006',
    pipeline_name: 'vehicle_augment_v2_nightly',
    status: 'SKIPPED_NO_DELTA',
    trigger_kind: 'automation_manual_rerun',
    automation_trigger_source: 'manual_rerun',
    automation_batch_id: null,
    triggered_input_versions: { vehicle_detection_source: '1.2' },
    output_dataset_version_id: null,
    output_dataset_version: null,
    started_at: '2026-04-23T06:15:00Z',
    finished_at: '2026-04-23T06:15:01Z',
    created_at: '2026-04-23T06:15:00Z',
    duration_seconds: 1,
    error_message: null,
  },

  // ① P1 → P2 연쇄 실행 batch (triggering 으로 시작)
  {
    id: 'exec-p2-batch-auto',
    pipeline_id: 'pl-headcrop-visible-0002',
    pipeline_name: 'helmet_visible_update',
    status: 'DONE',
    trigger_kind: 'automation_auto',
    automation_trigger_source: 'triggering',
    automation_batch_id: 'batch-20260422-1430',
    triggered_input_versions: { hardhat_headcrop_original_merged: '3.0' },
    output_dataset_version_id: '83f76037-df56-4575-a343-2ade37299225',
    output_dataset_version: '2.1',
    started_at: '2026-04-22T14:48:10Z',
    finished_at: '2026-04-22T15:00:04Z',
    created_at: '2026-04-22T14:48:10Z',
    duration_seconds: 714,
    error_message: null,
  },
  {
    id: 'exec-p1-batch-auto',
    pipeline_id: 'pl-headcrop-merge-0001',
    pipeline_name: 'helmet_merge_nightly',
    status: 'DONE',
    trigger_kind: 'automation_auto',
    automation_trigger_source: 'triggering',
    automation_batch_id: 'batch-20260422-1430',
    triggered_input_versions: { hardhat_headcrop_raw: '2.0' },
    output_dataset_version_id: '4d2afb95-f7e6-4297-afff-6c435b9af9cf',
    output_dataset_version: '3.0',
    started_at: '2026-04-22T14:30:02Z',
    finished_at: '2026-04-22T14:47:55Z',
    created_at: '2026-04-22T14:30:02Z',
    duration_seconds: 1073,
    error_message: null,
  },

  // ④ P6 polling 자동 실행 (직전 정상 실행)
  {
    id: 'exec-p6-polling-20260422',
    pipeline_id: 'pl-vehicle-augment-0006',
    pipeline_name: 'vehicle_augment_v2_nightly',
    status: 'DONE',
    trigger_kind: 'automation_auto',
    automation_trigger_source: 'polling',
    automation_batch_id: null,
    triggered_input_versions: { vehicle_detection_source: '1.2' },
    output_dataset_version_id: 'dv-vehicle-processed-1.3',
    output_dataset_version: '1.3',
    started_at: '2026-04-22T20:00:00Z',
    finished_at: '2026-04-22T20:12:40Z',
    created_at: '2026-04-22T20:00:00Z',
    duration_seconds: 760,
    error_message: null,
  },

  // ② 사이클 감지 전 P3 정상 실행 1건 (이력 存在 → DAG 에 표시되는 이유)
  {
    id: 'exec-p3-pre-cycle',
    pipeline_id: 'pl-cycle-a-to-b-0003',
    pipeline_name: 'cycle_demo_a_to_b',
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    triggered_input_versions: { cycle_demo_group_a: '1.0' },
    output_dataset_version_id: 'dv-cycle-b-1.0',
    output_dataset_version: '1.0',
    started_at: '2026-04-20T08:00:00Z',
    finished_at: '2026-04-20T08:04:00Z',
    created_at: '2026-04-20T08:00:00Z',
    duration_seconds: 240,
    error_message: null,
  },
  {
    id: 'exec-p4-pre-cycle',
    pipeline_id: 'pl-cycle-b-to-a-0004',
    pipeline_name: 'cycle_demo_b_to_a',
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    triggered_input_versions: { cycle_demo_group_b: '1.0' },
    output_dataset_version_id: 'dv-cycle-a-2.0',
    output_dataset_version: '2.0',
    started_at: '2026-04-20T08:05:00Z',
    finished_at: '2026-04-20T08:08:30Z',
    created_at: '2026-04-20T08:05:00Z',
    duration_seconds: 210,
    error_message: null,
  },

  // ③ P5 stopped — 이전 manual 실행
  {
    id: 'exec-p5-manual',
    pipeline_id: 'pl-person-convert-0005',
    pipeline_name: 'person_detection_raw_to_coco',
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    triggered_input_versions: { person_detection_raw: '1.0' },
    output_dataset_version_id: 'dv-person-coco-1.0',
    output_dataset_version: '1.0',
    started_at: '2026-04-15T10:00:00Z',
    finished_at: '2026-04-15T10:22:18Z',
    created_at: '2026-04-15T10:00:00Z',
    duration_seconds: 1338,
    error_message: null,
  },

  // ① 초기 P1 수동 실행 (automation 활성 이전)
  {
    id: 'exec-p1-initial-manual',
    pipeline_id: 'pl-headcrop-merge-0001',
    pipeline_name: 'helmet_merge_nightly',
    status: 'DONE',
    trigger_kind: 'manual_from_editor',
    automation_trigger_source: null,
    automation_batch_id: null,
    triggered_input_versions: { hardhat_headcrop_raw: '1.0' },
    output_dataset_version_id: 'dv-headcrop-merge-1.0',
    output_dataset_version: '1.0',
    started_at: '2026-04-10T09:30:00Z',
    finished_at: '2026-04-10T09:51:20Z',
    created_at: '2026-04-10T09:30:00Z',
    duration_seconds: 1280,
    error_message: null,
  },
]

/**
 * batch_id 기준으로 그룹화한 실행 이력.
 * 실행 이력 페이지 §6-3 의 "토폴로지 순서 펼침" UI 에서 사용.
 */
export const MOCK_EXECUTION_BATCHES: ExecutionBatch[] = [
  {
    batch_id: 'batch-20260422-1430',
    trigger_source: 'triggering',
    created_at: '2026-04-22T14:30:02Z',
    executions: [
      // 토폴로지 순서: P1 먼저, 이어서 P2
      MOCK_EXECUTIONS.find((e) => e.id === 'exec-p1-batch-auto')!,
      MOCK_EXECUTIONS.find((e) => e.id === 'exec-p2-batch-auto')!,
    ],
  },
]

// =============================================================================
// 상세 탭 — 상류 DatasetGroup delta fixture
// =============================================================================

/**
 * 파이프라인별 "상류 그룹의 최신 vs 마지막 자동 처리 버전" 표 데이터.
 * 목업은 Pipeline 의 input 만 상류로 가정 (실 구현에서는 input + DAG 상류 체인 전체).
 */
export const MOCK_UPSTREAM_DELTAS: Record<string, UpstreamGroupDelta[]> = {
  'pl-headcrop-merge-0001': [
    {
      group_id: GROUP_HEADCROP_RAW.group_id,
      group_name: GROUP_HEADCROP_RAW.group_name,
      split: 'VAL',
      latest_version: '2.1',
      last_seen_version: '2.0',
      has_delta: true,
    },
  ],
  'pl-headcrop-visible-0002': [
    {
      group_id: GROUP_HEADCROP_ORIGINAL_MERGED.group_id,
      group_name: GROUP_HEADCROP_ORIGINAL_MERGED.group_name,
      split: 'VAL',
      latest_version: '3.0',
      last_seen_version: '3.0',
      has_delta: false,
    },
  ],
  'pl-cycle-a-to-b-0003': [
    {
      group_id: GROUP_A.group_id,
      group_name: GROUP_A.group_name,
      split: 'TRAIN',
      latest_version: '1.0',
      last_seen_version: '1.0',
      has_delta: false,
    },
  ],
  'pl-cycle-b-to-a-0004': [
    {
      group_id: GROUP_B.group_id,
      group_name: GROUP_B.group_name,
      split: 'TRAIN',
      latest_version: '1.0',
      last_seen_version: '1.0',
      has_delta: false,
    },
  ],
  'pl-person-convert-0005': [
    {
      group_id: GROUP_PERSON_RAW.group_id,
      group_name: GROUP_PERSON_RAW.group_name,
      split: 'TRAIN',
      latest_version: '1.1',
      last_seen_version: null,
      has_delta: true,
    },
  ],
  'pl-vehicle-augment-0006': [
    {
      group_id: GROUP_VEHICLE_SOURCE.group_id,
      group_name: GROUP_VEHICLE_SOURCE.group_name,
      split: 'VAL',
      latest_version: '1.2',
      last_seen_version: '1.2',
      has_delta: false,
    },
  ],
}
