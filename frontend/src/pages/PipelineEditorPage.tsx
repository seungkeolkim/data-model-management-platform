/**
 * PipelineEditorPage — 전체화면 ComfyUI 스타일 노드 에디터
 *
 * AppLayout 밖에 렌더링되어 사이드바 없이 전체 화면을 사용한다.
 * 좌측: NodePalette, 중앙: React Flow 캔버스, 우측: PropertiesPanel
 * 상단: EditorToolbar
 */

import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  type OnConnect,
  type NodeTypes,
  ReactFlowProvider,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { message, ConfigProvider, theme } from 'antd'
import koKR from 'antd/locale/ko_KR'

import DataLoadNode from '@/components/pipeline/nodes/DataLoadNode'
import OperatorNode from '@/components/pipeline/nodes/OperatorNode'
import MergeNode from '@/components/pipeline/nodes/MergeNode'
import SaveNode from '@/components/pipeline/nodes/SaveNode'
import NodePalette from '@/components/pipeline/NodePalette'
import EditorToolbar from '@/components/pipeline/EditorToolbar'
import PropertiesPanel from '@/components/pipeline/PropertiesPanel'
import ExecutionSubmittedModal from '@/components/pipeline/ExecutionStatusModal'
import PipelineJsonPreview from '@/components/pipeline/PipelineJsonPreview'

import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import { validateGraphStructure, graphToPipelineConfig } from '@/utils/pipelineConverter'
import { pipelinesApi } from '@/api/pipeline'
import type { PipelineNodeData, PipelineNode, PipelineEdge } from '@/types/pipeline'

// React Flow 커스텀 노드 타입 등록
const nodeTypes: NodeTypes = {
  dataLoad: DataLoadNode,
  operator: OperatorNode,
  merge: MergeNode,
  save: SaveNode,
}

/** 노드 ID 생성용 카운터 */
let nodeIdCounter = 0
function generateNodeId(): string {
  nodeIdCounter += 1
  return `node_${Date.now()}_${nodeIdCounter}`
}

function PipelineEditorContent() {
  const [searchParams] = useSearchParams()
  const taskType = searchParams.get('taskType') ?? 'DETECTION'

  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<PipelineEdge>([])
  const [isValidating, setIsValidating] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [jsonPreviewContent, setJsonPreviewContent] = useState('')
  const [jsonPreviewError, setJsonPreviewError] = useState<string | null>(null)

  const {
    nodeDataMap,
    setNodeData,
    removeNodeData,
    setSelectedNode,
    selectedNodeId,
    isJsonPreviewOpen,
    setValidationResult,
    applyValidationToNodes,
    clearValidation,
    setExecutionId,
    reset,
  } = usePipelineEditorStore()

  // ── 엣지 연결 핸들러 ──
  const onConnect: OnConnect = useCallback(
    (connection) => {
      setEdges((eds) => addEdge({ ...connection, animated: true }, eds))
    },
    [setEdges],
  )

  // ── 노드 삭제 시 스토어 동기화 ──
  const handleNodesChange: typeof onNodesChange = useCallback(
    (changes) => {
      for (const change of changes) {
        if (change.type === 'remove') {
          removeNodeData(change.id)
        }
      }
      onNodesChange(changes)
    },
    [onNodesChange, removeNodeData],
  )

  // ── 노드 선택 ──
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: PipelineNode) => {
      setSelectedNode(node.id)
    },
    [setSelectedNode],
  )

  const handlePaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [setSelectedNode])

  // ── 팔레트에서 노드 추가 ──
  const handleAddNode = useCallback(
    (data: PipelineNodeData) => {
      const newId = generateNodeId()
      // 노드를 캔버스 중앙 부근에 배치 (약간 랜덤 오프셋)
      const offsetX = 300 + Math.random() * 200
      const offsetY = 100 + Math.random() * 200

      const newNode: PipelineNode = {
        id: newId,
        type: data.type === 'dataLoad'
          ? 'dataLoad'
          : data.type === 'merge'
            ? 'merge'
            : data.type === 'save'
              ? 'save'
              : 'operator',
        position: { x: offsetX, y: offsetY },
        data: data as PipelineNode['data'],
      }

      setNodes((nds) => [...nds, newNode])
      setNodeData(newId, data)
      setSelectedNode(newId)
    },
    [setNodes, setNodeData, setSelectedNode],
  )

  // ── JSON 프리뷰 업데이트 ──
  useMemo(() => {
    if (!isJsonPreviewOpen) return
    try {
      const config = graphToPipelineConfig(nodes, edges, nodeDataMap)
      setJsonPreviewContent(JSON.stringify(config, null, 2))
      setJsonPreviewError(null)
    } catch (err) {
      setJsonPreviewContent('')
      setJsonPreviewError((err as Error).message)
    }
  }, [nodes, edges, nodeDataMap, isJsonPreviewOpen])

  // ── 검증 ──
  const handleValidate = useCallback(async () => {
    clearValidation()

    // 1. 클라이언트 사전 검증
    const clientErrors = validateGraphStructure(nodes, edges, nodeDataMap)
    if (clientErrors.length > 0) {
      message.error(clientErrors[0].message)
      return
    }

    // 2. PipelineConfig 생성
    let config
    try {
      config = graphToPipelineConfig(nodes, edges, nodeDataMap)
    } catch (err) {
      message.error((err as Error).message)
      return
    }

    // 3. API 검증
    setIsValidating(true)
    try {
      const response = await pipelinesApi.validate(config)
      const result = response.data
      setValidationResult(result)
      applyValidationToNodes(result.issues)

      if (result.is_valid) {
        message.success('검증 통과! 실행할 수 있습니다.')
      } else {
        message.warning(`오류 ${result.error_count}개, 경고 ${result.warning_count}개`)
      }
    } catch (err) {
      message.error('검증 API 호출 실패')
      console.error('Validation API error:', err)
    } finally {
      setIsValidating(false)
    }
  }, [nodes, edges, nodeDataMap, clearValidation, setValidationResult, applyValidationToNodes])

  // ── 실행 ──
  const handleExecute = useCallback(async () => {
    // 검증 먼저 수행
    clearValidation()

    const clientErrors = validateGraphStructure(nodes, edges, nodeDataMap)
    if (clientErrors.length > 0) {
      message.error(clientErrors[0].message)
      return
    }

    let config
    try {
      config = graphToPipelineConfig(nodes, edges, nodeDataMap)
    } catch (err) {
      message.error((err as Error).message)
      return
    }

    // 자동 검증
    setIsExecuting(true)
    try {
      const validateResponse = await pipelinesApi.validate(config)
      const validateResult = validateResponse.data
      setValidationResult(validateResult)
      applyValidationToNodes(validateResult.issues)

      if (!validateResult.is_valid) {
        message.error(`검증 실패 (오류 ${validateResult.error_count}개). 실행할 수 없습니다.`)
        setIsExecuting(false)
        return
      }

      // 실행 제출
      const executeResponse = await pipelinesApi.execute(config)
      const { execution_id } = executeResponse.data
      setExecutionId(execution_id)
      message.info('파이프라인 실행이 제출되었습니다.')
    } catch (err) {
      message.error('실행 API 호출 실패')
      console.error('Execute API error:', err)
    } finally {
      setIsExecuting(false)
    }
  }, [nodes, edges, nodeDataMap, clearValidation, setValidationResult, applyValidationToNodes, setExecutionId])

  // ── 캔버스 초기화 ──
  const handleClearCanvas = useCallback(() => {
    setNodes([])
    setEdges([])
    reset()
  }, [setNodes, setEdges, reset])

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 상단 툴바 */}
      <EditorToolbar
        onValidate={handleValidate}
        onExecute={handleExecute}
        onClearCanvas={handleClearCanvas}
        isValidating={isValidating}
        isExecuting={isExecuting}
        taskType={taskType}
      />

      {/* 본문: 팔레트 + 캔버스 + 속성패널 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 좌측 팔레트 — taskType에 맞는 manipulator만 표시 */}
        <NodePalette onAddNode={handleAddNode} taskType={taskType} />

        {/* 중앙 캔버스 */}
        <div style={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            nodeTypes={nodeTypes}
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
            style={{ background: '#f8f9fa' }}
          >
            <Background gap={20} size={1} color="#e0e0e0" />
            <Controls />
          </ReactFlow>
        </div>

        {/* JSON 프리뷰 (토글) */}
        {isJsonPreviewOpen && (
          <PipelineJsonPreview
            jsonString={jsonPreviewContent}
            error={jsonPreviewError}
          />
        )}

        {/* 우측 속성 패널 */}
        <PropertiesPanel />
      </div>

      {/* 실행 상태 모달 */}
      <ExecutionSubmittedModal />
    </div>
  )
}

/**
 * ReactFlowProvider로 감싸야 useReactFlow 등 내부 훅이 동작한다.
 * ConfigProvider도 별도로 감싸서 에디터 페이지에서도 Ant Design 테마를 적용한다.
 */
export default function PipelineEditorPage() {
  return (
    <ConfigProvider
      locale={koKR}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: { colorPrimary: '#1677ff', borderRadius: 6 },
      }}
    >
      <ReactFlowProvider>
        <PipelineEditorContent />
      </ReactFlowProvider>
    </ConfigProvider>
  )
}
