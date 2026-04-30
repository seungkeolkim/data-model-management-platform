/**
 * 파이프라인 에디터 Zustand 스토어
 *
 * React Flow의 시각적 상태(노드 위치, 줌 등)는 React Flow 자체가 관리하고,
 * 이 스토어는 도메인 데이터(노드별 설정, 검증 결과, 실행 상태)만 관리한다.
 * 노드 ID를 키로 양쪽을 연결한다.
 */

import { create } from 'zustand'
import type {
  PipelineNodeData,
  PipelineValidationResponse,
  PipelineValidationIssue,
} from '../types/pipeline'
import { distributeIssuesToNodes } from '@/pipeline-sdk'

// =============================================================================
// 스토어 인터페이스
// =============================================================================

interface PipelineEditorState {
  // ── 노드 도메인 데이터 (nodeId → data) ──
  nodeDataMap: Record<string, PipelineNodeData>

  // ── 검증 ──
  validationResult: PipelineValidationResponse | null

  // ── UI 상태 ──
  selectedNodeId: string | null
  isJsonPreviewOpen: boolean

  // ── 액션 ──
  setNodeData: (nodeId: string, data: PipelineNodeData) => void
  updateNodeParams: (nodeId: string, params: Record<string, unknown>) => void
  removeNodeData: (nodeId: string) => void
  setSelectedNode: (nodeId: string | null) => void
  setValidationResult: (result: PipelineValidationResponse | null) => void
  /** 검증 결과의 issues를 파싱하여 각 노드의 validationIssues에 매핑 */
  applyValidationToNodes: (issues: PipelineValidationIssue[]) => void
  clearValidation: () => void
  toggleJsonPreview: () => void
  /** 에디터 전체 초기화 */
  reset: () => void
}

// =============================================================================
// 초기 상태
// =============================================================================

const initialState = {
  nodeDataMap: {} as Record<string, PipelineNodeData>,
  validationResult: null as PipelineValidationResponse | null,
  selectedNodeId: null as string | null,
  isJsonPreviewOpen: false,
}

// =============================================================================
// 스토어 생성
// =============================================================================

export const usePipelineEditorStore = create<PipelineEditorState>((set) => ({
  ...initialState,

  setNodeData: (nodeId, data) =>
    set((state) => ({
      nodeDataMap: { ...state.nodeDataMap, [nodeId]: data },
    })),

  updateNodeParams: (nodeId, params) =>
    set((state) => {
      const existing = state.nodeDataMap[nodeId]
      // params를 가질 수 있는 노드 타입만 갱신 대상
      if (!existing || !('params' in existing)) {
        return state
      }
      return {
        nodeDataMap: {
          ...state.nodeDataMap,
          [nodeId]: { ...existing, params } as typeof existing,
        },
      }
    }),

  removeNodeData: (nodeId) =>
    set((state) => {
      const { [nodeId]: _, ...rest } = state.nodeDataMap
      return {
        nodeDataMap: rest,
        // 삭제된 노드가 선택 중이었으면 선택 해제
        selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      }
    }),

  setSelectedNode: (nodeId) =>
    set({ selectedNodeId: nodeId }),

  setValidationResult: (result) =>
    set({ validationResult: result }),

  applyValidationToNodes: (issues) =>
    set((state) => ({
      // SDK의 registry 순회 기반 매핑 사용 — 노드 타입별 하드코딩 제거
      nodeDataMap: distributeIssuesToNodes(state.nodeDataMap, issues) as typeof state.nodeDataMap,
    })),

  clearValidation: () =>
    set((state) => {
      const updatedMap = { ...state.nodeDataMap }
      for (const nodeId of Object.keys(updatedMap)) {
        updatedMap[nodeId] = { ...updatedMap[nodeId], validationIssues: [] }
      }
      return { nodeDataMap: updatedMap, validationResult: null }
    }),

  toggleJsonPreview: () =>
    set((state) => ({ isJsonPreviewOpen: !state.isJsonPreviewOpen })),

  reset: () => set(initialState),
}))
