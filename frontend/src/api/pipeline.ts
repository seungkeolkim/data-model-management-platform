/**
 * 파이프라인 API 함수
 *
 * 파이프라인 검증, 실행, 상태 조회, 이력 목록 엔드포인트를 래핑한다.
 * Manipulator 목록 조회도 여기서 re-export (에디터에서 직접 사용).
 */

import api from './index'
import type {
  PipelineConfig,
  PartialPipelineConfig,
  PipelineValidationResponse,
  PipelineSubmitResponse,
  PipelineExecutionResponse,
  PipelineListResponse,
  PipelineEntityResponse,
  PipelineListPageResponse,
  PipelineUpdateRequest,
  PipelineRunSubmitRequest,
  PipelineAutomationRealResponse,
  PipelineAutomationUpsertRequest,
  PipelineAutomationRerunRequest,
} from '../types/pipeline'
import type { Manipulator, DatasetVersion, DatasetGroup, DatasetGroupListResponse } from '../types/dataset'

// =============================================================================
// Pipeline 실행 관련
// =============================================================================

export const pipelinesApi = {
  /** 파이프라인 설정 검증 (정적 + DB 검증) */
  validate: (config: PipelineConfig) =>
    api.post<PipelineValidationResponse>('/pipelines/validate', config),

  /** 파이프라인 비동기 실행 제출 (202 응답) */
  execute: (config: PipelineConfig) =>
    api.post<PipelineSubmitResponse>('/pipelines/execute', config),

  /** 특정 실행의 상태 조회 (polling용) */
  getStatus: (executionId: string) =>
    api.get<PipelineExecutionResponse>(`/pipelines/${executionId}/status`),

  /** 실행 이력 목록 */
  list: (params?: { page?: number; page_size?: number }) =>
    api.get<PipelineListResponse>('/pipelines', { params }),

  /** 특정 노드 시점의 head_schema 프리뷰 (Save 없는 partial config 허용) */
  previewSchema: (config: PartialPipelineConfig, targetRef: string) =>
    api.post<SchemaPreviewResponse>('/pipelines/preview-schema', {
      config,
      target_ref: targetRef,
    }),
}

export interface SchemaPreviewHead {
  name: string
  multi_label: boolean
  classes: string[]
}

export interface SchemaPreviewResponse {
  task_kind: 'classification' | 'detection' | 'unknown'
  head_schema: SchemaPreviewHead[] | null
  error_code: string | null
  error_message: string | null
}

// =============================================================================
// Manipulator 목록 (에디터 NodePalette용)
// =============================================================================

export const manipulatorsApi = {
  /** manipulator 목록 조회 (카테고리/스코프/상태 필터) */
  list: (params?: { category?: string; scope?: string; status?: string }) =>
    api.get<{ items: Manipulator[]; total: number }>('/manipulators', { params }),

  /** 단일 manipulator 상세 조회 */
  get: (manipulatorId: string) =>
    api.get<Manipulator>(`/manipulators/${manipulatorId}`),
}

// =============================================================================
// Dataset 목록 (DataLoadNode 선택 드롭다운용)
// =============================================================================

export const datasetsForPipelineApi = {
  /** READY 상태 데이터셋만 조회 (파이프라인 입력 소스용) */
  listReady: () =>
    api.get<DatasetVersion[]>('/datasets', { params: { status: 'READY' } }),

  /** 삭제되지 않은 DatasetGroup 목록 조회 (task_types 필터 가능) */
  listGroups: (params?: { page?: number; page_size?: number; search?: string }) =>
    api.get<DatasetGroupListResponse>('/dataset-groups', { params: { ...params, page_size: params?.page_size ?? 200 } }),

  /** DatasetGroup 상세 조회 (하위 datasets 포함) */
  getGroup: (groupId: string) =>
    api.get<DatasetGroup>(`/dataset-groups/${groupId}`),
}

// =============================================================================
// Pipeline 엔티티 CRUD (v7.10, 핸드오프 027 §2-1 / §12)
//
// 기존 pipelinesApi (execute / list runs) 와 구분되는 신규 경로 — /pipelines/entities 하위.
// §9-7 페이지 재배선 시 URL 을 정식 /pipelines top-level 로 승격 검토.
// =============================================================================

export const pipelineEntitiesApi = {
  /** Pipeline 목록 (is_active=FALSE / soft-deleted 숨김 기본 ON) */
  list: (params?: {
    include_inactive?: boolean
    name_filter?: string
    task_type?: string[]
    limit?: number
    offset?: number
  }) =>
    api.get<PipelineListPageResponse>('/pipelines/entities', { params }),

  /** Pipeline 단건 상세 (config 포함) */
  get: (pipelineId: string) =>
    api.get<PipelineEntityResponse>(`/pipelines/entities/${pipelineId}`),

  /** name / description / is_active 편집. config 는 immutable (§6-1). */
  update: (pipelineId: string, body: PipelineUpdateRequest) =>
    api.patch<PipelineEntityResponse>(`/pipelines/entities/${pipelineId}`, body),

  /** 특정 Pipeline 의 실행 이력 */
  listRuns: (pipelineId: string, params?: { page?: number; page_size?: number }) =>
    api.get<PipelineListResponse>(`/pipelines/entities/${pipelineId}/runs`, { params }),

  /** Version Resolver Modal 제출 — {split_id: version} (027 §4-3) */
  submitRun: (pipelineId: string, body: PipelineRunSubmitRequest) =>
    api.post<PipelineSubmitResponse>(`/pipelines/entities/${pipelineId}/runs`, body),
}

export const pipelineAutomationsApi = {
  /** 활성 자동화 전체 */
  listActive: () =>
    api.get<PipelineAutomationRealResponse[]>('/pipelines/automations'),

  /** Pipeline 의 현재 active automation (없으면 null) */
  getByPipeline: (pipelineId: string) =>
    api.get<PipelineAutomationRealResponse | null>(
      `/pipelines/entities/${pipelineId}/automation`,
    ),

  /** 자동화 등록 또는 갱신 (idempotent PUT). Pipeline 당 active 1개 (partial unique). */
  upsert: (pipelineId: string, body: PipelineAutomationUpsertRequest) =>
    api.put<PipelineAutomationRealResponse>(
      `/pipelines/entities/${pipelineId}/automation`, body,
    ),

  /** soft delete (§12-3) — row 유지 + is_active=FALSE */
  delete: (automationId: string) =>
    api.delete<PipelineAutomationRealResponse>(
      `/pipelines/automations/${automationId}`,
    ),

  /** §6-4 (a) — 대상 Pipeline 이전 */
  reassign: (automationId: string, newPipelineId: string) =>
    api.post<PipelineAutomationRealResponse>(
      `/pipelines/automations/${automationId}/reassign`,
      null,
      { params: { new_pipeline_id: newPipelineId } },
    ),

  /** 수동 재실행 — 026 §5-2a 2-버튼 UX */
  rerun: (automationId: string, body: PipelineAutomationRerunRequest) =>
    api.post<PipelineSubmitResponse>(
      `/pipelines/automations/${automationId}/rerun`, body,
    ),
}
