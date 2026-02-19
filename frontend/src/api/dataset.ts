/**
 * Dataset API 함수들
 */
import api from './index'
import type {
  DatasetGroup,
  DatasetGroupCreate,
  DatasetGroupUpdate,
  DatasetGroupListResponse,
  DatasetRegisterRequest,
  DatasetValidateRequest,
  DatasetValidateResponse,
  Dataset,
} from '../types/dataset'

// Dataset Groups
export const datasetGroupsApi = {
  list: (params?: {
    page?: number
    page_size?: number
    dataset_type?: string
    search?: string
  }) =>
    api.get<DatasetGroupListResponse>('/dataset-groups', { params }),

  get: (groupId: string) =>
    api.get<DatasetGroup>(`/dataset-groups/${groupId}`),

  create: (data: DatasetGroupCreate) =>
    api.post<DatasetGroup>('/dataset-groups', data),

  update: (groupId: string, data: DatasetGroupUpdate) =>
    api.patch<DatasetGroup>(`/dataset-groups/${groupId}`, data),

  delete: (groupId: string) =>
    api.delete<{ message: string }>(`/dataset-groups/${groupId}`),

  validatePath: (data: DatasetValidateRequest) =>
    api.post<DatasetValidateResponse>('/dataset-groups/validate-path', data),

  register: (data: DatasetRegisterRequest) =>
    api.post<DatasetGroup>('/dataset-groups/register', data),
}

// Individual Datasets
export const datasetsApi = {
  list: (params?: { group_id?: string; split?: string; status?: string }) =>
    api.get<Dataset[]>('/datasets', { params }),

  get: (datasetId: string) =>
    api.get<Dataset>(`/datasets/${datasetId}`),

  delete: (datasetId: string) =>
    api.delete<{ message: string }>(`/datasets/${datasetId}`),
}

// Health
export const systemApi = {
  health: () => api.get<{
    status: string
    services: Record<string, unknown>
    version: string
    env: string
  }>('/health'),
}

// Manipulators
export const manipulatorsApi = {
  list: (params?: { category?: string; scope?: string; status?: string }) =>
    api.get('/api/v1/manipulators', { params }),

  get: (manipulatorId: string) =>
    api.get(`/api/v1/manipulators/${manipulatorId}`),
}
