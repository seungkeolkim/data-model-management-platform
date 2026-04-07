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
  FormatValidateRequest,
  FormatValidateResponse,
  Dataset,
  FileBrowserListResponse,
  FileBrowserRootsResponse,
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

  register: (data: DatasetRegisterRequest) =>
    api.post<DatasetGroup>('/dataset-groups/register', data),

  validateFormat: (data: FormatValidateRequest) =>
    api.post<FormatValidateResponse>('/dataset-groups/validate-format', data),

  nextVersion: (groupId: string, split: string) =>
    api.get<{ version: string }>('/dataset-groups/next-version', {
      params: { group_id: groupId, split },
    }),
}

// Individual Datasets
export const datasetsApi = {
  list: (params?: { group_id?: string; split?: string; status?: string }) =>
    api.get<Dataset[]>('/datasets', { params }),

  get: (datasetId: string) =>
    api.get<Dataset>(`/datasets/${datasetId}`),

  delete: (datasetId: string) =>
    api.delete<{ message: string }>(`/datasets/${datasetId}`),

  update: (datasetId: string, data: { annotation_format?: string }) =>
    api.patch<Dataset>(`/datasets/${datasetId}`, data),

  validate: (datasetId: string, data: DatasetValidateRequest) =>
    api.post<FormatValidateResponse>(`/datasets/${datasetId}/validate`, data),

  replaceMetaFile: (datasetId: string, sourceMetaFilePath: string) =>
    api.put<Dataset>(`/datasets/${datasetId}/meta-file`, {
      source_annotation_meta_file: sourceMetaFilePath,
    }),
}

// File Browser
export const fileBrowserApi = {
  roots: () =>
    api.get<FileBrowserRootsResponse>('/filebrowser/roots'),

  list: (params?: { path?: string; mode?: 'directory' | 'file' | 'all' }) =>
    api.get<FileBrowserListResponse>('/filebrowser/list', { params }),
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
    api.get('/manipulators', { params }),

  get: (manipulatorId: string) =>
    api.get(`/manipulators/${manipulatorId}`),
}
