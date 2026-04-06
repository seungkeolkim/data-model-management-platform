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
  PipelineExecutionResponse,
} from '../types/pipeline'

// =============================================================================
// 스토어 인터페이스
// =============================================================================

interface PipelineEditorState {
  // ── 노드 도메인 데이터 (nodeId → data) ──
  nodeDataMap: Record<string, PipelineNodeData>

  // ── 검증 ──
  validationResult: PipelineValidationResponse | null

  // ── 실행 ──
  executionId: string | null
  executionStatus: PipelineExecutionResponse | null

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
  setExecutionId: (id: string | null) => void
  setExecutionStatus: (status: PipelineExecutionResponse | null) => void
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
  executionId: null as string | null,
  executionStatus: null as PipelineExecutionResponse | null,
  selectedNodeId: null as string | null,
  isJsonPreviewOpen: false,
}

// =============================================================================
// 스토어 생성
// =============================================================================

export const usePipelineEditorStore = create<PipelineEditorState>((set, get) => ({
  ...initialState,

  setNodeData: (nodeId, data) =>
    set((state) => ({
      nodeDataMap: { ...state.nodeDataMap, [nodeId]: data },
    })),

  updateNodeParams: (nodeId, params) =>
    set((state) => {
      const existing = state.nodeDataMap[nodeId]
      if (!existing || (existing.type !== 'operator' && existing.type !== 'merge')) {
        return state
      }
      return {
        nodeDataMap: {
          ...state.nodeDataMap,
          [nodeId]: { ...existing, params },
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
    set((state) => {
      // 먼저 모든 노드의 검증 이슈 초기화
      const updatedMap = { ...state.nodeDataMap }
      for (const nodeId of Object.keys(updatedMap)) {
        updatedMap[nodeId] = { ...updatedMap[nodeId], validationIssues: [] }
      }

      // field 패턴에서 노드 ID 추출하여 이슈 매핑
      // 예: "tasks.task_abc123.operator" → nodeId = "abc123"
      // 예: "output.dataset_type" → SaveNode에 매핑
      for (const issue of issues) {
        const field = issue.field
        if (field.startsWith('tasks.task_')) {
          // task_<nodeId>.xxx 패턴
          const taskKey = field.split('.')[1]  // "task_abc123"
          const nodeId = taskKey.replace(/^task_/, '')
          if (updatedMap[nodeId]) {
            const node = updatedMap[nodeId]
            const existing = node.validationIssues ?? []
            updatedMap[nodeId] = { ...node, validationIssues: [...existing, issue] }
          }
        } else if (field.startsWith('output.') || field === 'name') {
          // Save 노드에 매핑 — saveNode 찾기
          const saveNodeId = Object.keys(updatedMap).find(
            (id) => updatedMap[id].type === 'save'
          )
          if (saveNodeId) {
            const node = updatedMap[saveNodeId]
            const existing = node.validationIssues ?? []
            updatedMap[saveNodeId] = { ...node, validationIssues: [...existing, issue] }
          }
        }
        // source 관련 이슈는 DataLoad 노드에 매핑
        if (issue.code?.startsWith('SOURCE_DATASET_')) {
          // field 예: "tasks.task_xxx.inputs[0]" — source:<dataset_id> 관련
          // DataLoad 노드를 dataset_id로 찾아야 하므로 field에서 추출 시도
          // 간단히: issue.message에 dataset_id가 포함된 경우 매칭
          for (const nodeId of Object.keys(updatedMap)) {
            const nodeData = updatedMap[nodeId]
            if (nodeData.type === 'dataLoad' && nodeData.datasetId) {
              if (issue.field.includes(nodeData.datasetId) || issue.message.includes(nodeData.datasetId)) {
                const existing = nodeData.validationIssues ?? []
                updatedMap[nodeId] = { ...nodeData, validationIssues: [...existing, issue] }
              }
            }
          }
        }
      }

      return { nodeDataMap: updatedMap }
    }),

  clearValidation: () =>
    set((state) => {
      const updatedMap = { ...state.nodeDataMap }
      for (const nodeId of Object.keys(updatedMap)) {
        updatedMap[nodeId] = { ...updatedMap[nodeId], validationIssues: [] }
      }
      return { nodeDataMap: updatedMap, validationResult: null }
    }),

  setExecutionId: (id) =>
    set({ executionId: id }),

  setExecutionStatus: (status) =>
    set({ executionStatus: status }),

  toggleJsonPreview: () =>
    set((state) => ({ isJsonPreviewOpen: !state.isJsonPreviewOpen })),

  reset: () => set(initialState),
}))
