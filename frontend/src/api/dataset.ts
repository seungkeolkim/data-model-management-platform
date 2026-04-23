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
  DatasetRegisterClassificationRequest,
  DatasetRegisterClassificationResponse,
  DatasetValidateRequest,
  FormatValidateRequest,
  FormatValidateResponse,
  DatasetVersion,
  FileBrowserListResponse,
  FileBrowserRootsResponse,
  ClassificationScanResponse,
  SampleListResponse,
  EdaStatsResponse,
  LineageGraphResponse,
  ClassificationSampleListResponse,
  ClassificationEdaResponse,
} from '../types/dataset'

// Dataset Groups
export const datasetGroupsApi = {
  list: (params?: {
    page?: number
    page_size?: number
    // 필터는 다중 선택. 미선택 시 undefined 로 넘기고, 값이 있으면 Axios 가
    // params-serializer 기본 설정으로 ?key=a&key=b 형태로 반복 직렬화한다.
    dataset_type?: string[]
    task_type?: string[]
    annotation_format?: string[]
    search?: string
    // 정렬 기준 컬럼. 백엔드 라우터의 pattern 과 반드시 일치해야 한다.
    sort_by?:
      | 'name'
      | 'dataset_type'
      | 'task_types'
      | 'annotation_format'
      | 'created_at'
      | 'updated_at'
      | 'dataset_count'
      | 'total_image_count'
    sort_order?: 'asc' | 'desc'
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

  registerClassification: (data: DatasetRegisterClassificationRequest) =>
    api.post<DatasetRegisterClassificationResponse>(
      '/dataset-groups/register-classification',
      data,
    ),

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
    api.get<DatasetVersion[]>('/datasets', { params }),

  get: (datasetId: string) =>
    api.get<DatasetVersion>(`/datasets/${datasetId}`),

  delete: (datasetId: string) =>
    api.delete<{ message: string }>(`/datasets/${datasetId}`),

  update: (datasetId: string, data: { annotation_format?: string }) =>
    api.patch<DatasetVersion>(`/datasets/${datasetId}`, data),

  validate: (datasetId: string, data: DatasetValidateRequest) =>
    api.post<FormatValidateResponse>(`/datasets/${datasetId}/validate`, data),

  replaceMetaFile: (datasetId: string, sourceMetaFilePath: string) =>
    api.put<DatasetVersion>(`/datasets/${datasetId}/meta-file`, {
      source_annotation_meta_file: sourceMetaFilePath,
    }),

  samples: (datasetId: string, params?: { page?: number; page_size?: number }) =>
    api.get<SampleListResponse>(`/datasets/${datasetId}/samples`, { params }),

  eda: (datasetId: string) =>
    api.get<EdaStatsResponse>(`/datasets/${datasetId}/eda`),

  // Classification 전용 응답. 동일 엔드포인트지만 annotation_format=CLS_MANIFEST일 때
  // 백엔드가 다른 shape을 반환하므로 호출자가 타입을 알고 나눠 쓴다.
  classificationSamples: (
    datasetId: string,
    params?: {
      page?: number
      page_size?: number
      // "head:class" 문자열 목록. 같은 head 내 OR, 서로 다른 head 간 AND.
      head_filter?: string[]
    },
  ) =>
    api.get<ClassificationSampleListResponse>(`/datasets/${datasetId}/samples`, {
      params,
      // axios 기본 serializer는 array를 ?head_filter[]=... 로 직렬화하므로
      // FastAPI의 list[str] Query와 맞도록 반복 key 형식으로 바꾼다.
      paramsSerializer: {
        indexes: null,
      },
    }),

  classificationEda: (datasetId: string) =>
    api.get<ClassificationEdaResponse>(`/datasets/${datasetId}/eda`),

  lineage: (datasetId: string) =>
    api.get<LineageGraphResponse>(`/datasets/${datasetId}/lineage`),
}

// File Browser
export const fileBrowserApi = {
  roots: () =>
    api.get<FileBrowserRootsResponse>('/filebrowser/roots'),

  list: (params?: { path?: string; mode?: 'directory' | 'file' | 'all' }) =>
    api.get<FileBrowserListResponse>('/filebrowser/list', { params }),

  // Classification 데이터셋 루트를 2레벨(<head>/<class>/)로 단순 스캔
  classificationScan: (path: string) =>
    api.get<ClassificationScanResponse>('/filebrowser/classification-scan', {
      params: { path },
    }),
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
