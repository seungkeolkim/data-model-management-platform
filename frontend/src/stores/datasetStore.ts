/**
 * Zustand 스토어 - Dataset 상태 관리
 */
import { create } from 'zustand'
import type { DatasetGroup, DatasetGroupListResponse } from '../types/dataset'

interface DatasetStore {
  // 목록
  groups: DatasetGroup[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  error: string | null

  // 검색/필터
  search: string
  datasetType: string | null

  // 선택된 그룹
  selectedGroup: DatasetGroup | null

  // Actions
  setGroups: (data: DatasetGroupListResponse) => void
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  setSearch: (search: string) => void
  setDatasetType: (type: string | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  setSelectedGroup: (group: DatasetGroup | null) => void
  reset: () => void
}

const initialState = {
  groups: [],
  total: 0,
  page: 1,
  pageSize: 20,
  loading: false,
  error: null,
  search: '',
  datasetType: null,
  selectedGroup: null,
}

export const useDatasetStore = create<DatasetStore>((set) => ({
  ...initialState,

  setGroups: (data) =>
    set({
      groups: data.items,
      total: data.total,
      page: data.page,
      pageSize: data.page_size,
    }),

  setPage: (page) => set({ page }),
  setPageSize: (pageSize) => set({ pageSize }),
  setSearch: (search) => set({ search, page: 1 }),
  setDatasetType: (datasetType) => set({ datasetType, page: 1 }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setSelectedGroup: (selectedGroup) => set({ selectedGroup }),
  reset: () => set(initialState),
}))
