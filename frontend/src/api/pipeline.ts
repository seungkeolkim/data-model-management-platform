/**
 * 파이프라인 API 함수 (v7.11 — feature/pipeline-family-and-version).
 *
 * 라우트 그룹:
 *   pipelinesApi          — validate / execute / preview-schema (FE 호환 진입점)
 *   pipelineRunsApi       — 실행 이력 / 단건 상태
 *   pipelineConceptsApi   — Pipeline (concept) CRUD + family 이동 + runs 목록
 *   pipelineVersionsApi   — PipelineVersion 상세 + version 단위 run 제출
 *   pipelineFamiliesApi   — PipelineFamily CRUD
 *   pipelineAutomationsApi — version 단위 automation
 *   manipulatorsApi       — 노드 팔레트
 *   datasetsForPipelineApi — DataLoad 노드용
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
  PipelineFamilyCreateRequest,
  PipelineFamilyResponse,
  PipelineFamilyUpdateRequest,
  PipelineListPageResponse,
  PipelineUpdateRequest,
  PipelineRunSubmitRequest,
  PipelineVersionResponse,
  PipelineVersionUpdateRequest,
  PipelineAutomationRealResponse,
  PipelineAutomationUpsertRequest,
  PipelineAutomationRerunRequest,
} from '../types/pipeline'
import type {
  Manipulator,
  DatasetVersion,
  DatasetGroup,
  DatasetGroupListResponse,
} from '../types/dataset'

// =============================================================================
// Validate / Execute / Preview (FE 호환 진입점)
// =============================================================================

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

export const pipelinesApi = {
  validate: (config: PipelineConfig) =>
    api.post<PipelineValidationResponse>('/pipelines/validate', config),

  /** 에디터 "실행" — auto concept+version+run 생성 */
  execute: (config: PipelineConfig) =>
    api.post<PipelineSubmitResponse>('/pipelines/execute', config),

  previewSchema: (config: PartialPipelineConfig, targetRef: string) =>
    api.post<SchemaPreviewResponse>('/pipelines/preview-schema', {
      config,
      target_ref: targetRef,
    }),

  /** @deprecated v7.11 — pipelineRunsApi.get 사용 */
  getStatus: (runId: string) =>
    api.get<PipelineExecutionResponse>(`/pipelines/runs/${runId}`),

  /** @deprecated v7.11 — pipelineRunsApi.list 사용 */
  list: (params?: { page?: number; page_size?: number }) =>
    api.get<PipelineListResponse>('/pipelines/runs', { params }),
}

// =============================================================================
// PipelineRun (실행 이력)
// =============================================================================

export const pipelineRunsApi = {
  list: (params?: { page?: number; page_size?: number }) =>
    api.get<PipelineListResponse>('/pipelines/runs', { params }),

  get: (runId: string) =>
    api.get<PipelineExecutionResponse>(`/pipelines/runs/${runId}`),
}

// =============================================================================
// PipelineFamily
// =============================================================================

export const pipelineFamiliesApi = {
  list: () => api.get<PipelineFamilyResponse[]>('/pipelines/families'),

  get: (familyId: string) =>
    api.get<PipelineFamilyResponse>(`/pipelines/families/${familyId}`),

  create: (body: PipelineFamilyCreateRequest) =>
    api.post<PipelineFamilyResponse>('/pipelines/families', body),

  update: (familyId: string, body: PipelineFamilyUpdateRequest) =>
    api.patch<PipelineFamilyResponse>(`/pipelines/families/${familyId}`, body),

  delete: (familyId: string) =>
    api.delete<void>(`/pipelines/families/${familyId}`),
}

// =============================================================================
// Pipeline (concept) — 목록 / 상세 / 편집 / runs
// =============================================================================

export const pipelineConceptsApi = {
  list: (params?: {
    include_inactive?: boolean
    name_filter?: string
    task_type?: string[]
    family_id?: string
    family_unfiled?: boolean
    limit?: number
    offset?: number
  }) =>
    api.get<PipelineListPageResponse>('/pipelines', { params }),

  get: (pipelineId: string) =>
    api.get<PipelineEntityResponse>(`/pipelines/${pipelineId}`),

  update: (pipelineId: string, body: PipelineUpdateRequest) =>
    api.patch<PipelineEntityResponse>(`/pipelines/${pipelineId}`, body),

  /** 이 concept 의 모든 version 에 걸친 run 이력 */
  listRuns: (pipelineId: string, params?: { page?: number; page_size?: number }) =>
    api.get<PipelineListResponse>(`/pipelines/${pipelineId}/runs`, { params }),
}

// =============================================================================
// PipelineVersion — config + 실행
// =============================================================================

export const pipelineVersionsApi = {
  get: (versionId: string) =>
    api.get<PipelineVersionResponse>(`/pipelines/versions/${versionId}`),

  update: (versionId: string, body: PipelineVersionUpdateRequest) =>
    api.patch<PipelineVersionResponse>(`/pipelines/versions/${versionId}`, body),

  listRuns: (versionId: string, params?: { page?: number; page_size?: number }) =>
    api.get<PipelineListResponse>(`/pipelines/versions/${versionId}/runs`, { params }),

  /** Version Resolver Modal → run dispatch */
  submitRun: (versionId: string, body: PipelineRunSubmitRequest) =>
    api.post<PipelineSubmitResponse>(`/pipelines/versions/${versionId}/runs`, body),
}

// =============================================================================
// PipelineAutomation (version 단위)
// =============================================================================

export const pipelineAutomationsApi = {
  listActive: () =>
    api.get<PipelineAutomationRealResponse[]>('/pipelines/automations'),

  getByVersion: (versionId: string) =>
    api.get<PipelineAutomationRealResponse | null>(
      `/pipelines/versions/${versionId}/automation`,
    ),

  upsert: (versionId: string, body: PipelineAutomationUpsertRequest) =>
    api.put<PipelineAutomationRealResponse>(
      `/pipelines/versions/${versionId}/automation`, body,
    ),

  delete: (automationId: string) =>
    api.delete<PipelineAutomationRealResponse>(
      `/pipelines/automations/${automationId}`,
    ),

  reassign: (automationId: string, newPipelineVersionId: string) =>
    api.post<PipelineAutomationRealResponse>(
      `/pipelines/automations/${automationId}/reassign`,
      null,
      { params: { new_pipeline_version_id: newPipelineVersionId } },
    ),

  rerun: (automationId: string, body: PipelineAutomationRerunRequest) =>
    api.post<PipelineSubmitResponse>(
      `/pipelines/automations/${automationId}/rerun`, body,
    ),
}

// =============================================================================
// Manipulator + Dataset 보조 API (변경 없음)
// =============================================================================

export const manipulatorsApi = {
  list: (params?: { category?: string; scope?: string; status?: string }) =>
    api.get<{ items: Manipulator[]; total: number }>('/manipulators', { params }),

  get: (manipulatorId: string) =>
    api.get<Manipulator>(`/manipulators/${manipulatorId}`),
}

export const datasetsForPipelineApi = {
  listReady: () =>
    api.get<DatasetVersion[]>('/datasets', { params: { status: 'READY' } }),

  listGroups: (params?: { page?: number; page_size?: number; search?: string }) =>
    api.get<DatasetGroupListResponse>('/dataset-groups', {
      params: { ...params, page_size: params?.page_size ?? 200 },
    }),

  getGroup: (groupId: string) =>
    api.get<DatasetGroup>(`/dataset-groups/${groupId}`),
}

// =============================================================================
// 호환 alias — 기존 이름 사용처가 정리될 때까지 한시적 유지
// =============================================================================

/** @deprecated v7.11 — pipelineConceptsApi 사용. 호환 유지를 위한 alias. */
export const pipelineEntitiesApi = {
  list: pipelineConceptsApi.list,
  get: pipelineConceptsApi.get,
  update: pipelineConceptsApi.update,
  listRuns: pipelineConceptsApi.listRuns,
  /** @deprecated — pipelineVersionsApi.submitRun 사용 (version 단위 제출) */
  submitRun: pipelineVersionsApi.submitRun,
}
