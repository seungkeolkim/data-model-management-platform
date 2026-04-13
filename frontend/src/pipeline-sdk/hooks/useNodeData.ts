/**
 * Zustand store에서 노드 데이터를 직접 구독하는 훅.
 *
 * React Flow의 node.data prop은 store 변경 시 갱신되지 않으므로,
 * 노드 컴포넌트는 반드시 이 훅을 사용해 store를 직접 구독해야 한다.
 */
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import type { NodeDataByKind, NodeKind } from '../types'

export function useNodeData<K extends NodeKind>(nodeId: string): NodeDataByKind[K] | null {
  return usePipelineEditorStore(
    (state) => (state.nodeDataMap[nodeId] as NodeDataByKind[K] | undefined) ?? null,
  )
}

/** store의 setNodeData 액션을 바로 얻는 편의 훅 */
export function useSetNodeData() {
  return usePipelineEditorStore((state) => state.setNodeData)
}
