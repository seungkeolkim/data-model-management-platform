/**
 * 파이프라인 API 함수
 *
 * 파이프라인 검증, 실행, 상태 조회, 이력 목록 엔드포인트를 래핑한다.
 * Manipulator 목록 조회도 여기서 re-export (에디터에서 직접 사용).
 */

import api from './index'
import type {
  PipelineConfig,
  PipelineValidationResponse,
  PipelineSubmitResponse,
  PipelineExecutionResponse,
  PipelineListResponse,
} from '../types/pipeline'
import type { Manipulator, Dataset } from '../types/dataset'

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
    api.get<Dataset[]>('/datasets', { params: { status: 'READY' } }),
}
