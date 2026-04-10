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
import { message, ConfigProvider, theme, Modal, Input, Spin } from 'antd'
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
import {
  validateGraphStructure,
  graphToPipelineConfig,
  pipelineConfigToGraph,
  extractSourceDatasetIdsFromConfig,
} from '@/utils/pipelineConverter'
import type { DatasetDisplayInfo } from '@/utils/pipelineConverter'
import { pipelinesApi, manipulatorsApi } from '@/api/pipeline'
import { datasetsApi, datasetGroupsApi } from '@/api/dataset'
import type { PipelineConfig, PipelineNodeData, PipelineNode, PipelineEdge } from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'

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
  const [isJsonLoadModalOpen, setIsJsonLoadModalOpen] = useState(false)
  const [jsonLoadInput, setJsonLoadInput] = useState('')
  const [isJsonLoading, setIsJsonLoading] = useState(false)
  const [jsonLoadError, setJsonLoadError] = useState<string | null>(null)

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
  // Merge 노드를 제외한 노드는 입력 엣지를 1개만 허용한다.
  const onConnect: OnConnect = useCallback(
    (connection) => {
      const targetNodeId = connection.target
      if (!targetNodeId) return

      const targetData = nodeDataMap[targetNodeId]
      const isMergeNode = targetData?.type === 'merge'

      if (!isMergeNode) {
        // 이미 입력 엣지가 있는지 확인
        const existingInputEdge = edges.find((edge) => edge.target === targetNodeId)
        if (existingInputEdge) {
          Modal.warning({
            title: '연결 불가',
            content: 'Merge 노드를 제외한 노드는 입력을 하나만 받을 수 있습니다. 여러 입력을 합치려면 Merge 노드를 사용하세요.',
          })
          return
        }
      }

      setEdges((eds) => addEdge({ ...connection, animated: true }, eds))
    },
    [setEdges, edges, nodeDataMap],
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

  // ── JSON 불러오기 모달 열기 ──
  const handleOpenJsonLoadModal = useCallback(() => {
    setJsonLoadInput('')
    setJsonLoadError(null)
    setIsJsonLoadModalOpen(true)
  }, [])

  // ── JSON 불러오기 실행 ──
  const handleLoadJson = useCallback(async () => {
    // 1. JSON 파싱
    let config: PipelineConfig
    try {
      config = JSON.parse(jsonLoadInput)
    } catch {
      setJsonLoadError('유효하지 않은 JSON 형식입니다.')
      return
    }

    // 기본 구조 검증
    if (!config.name || !config.output || !config.tasks) {
      setJsonLoadError('PipelineConfig 형식이 아닙니다. name, output, tasks 필드가 필요합니다.')
      return
    }

    setIsJsonLoading(true)
    setJsonLoadError(null)

    try {
      // 2. manipulator 메타 정보 조회 (operator name → Manipulator 매핑)
      const manipulatorResponse = await manipulatorsApi.list({ status: 'ACTIVE' })
      const manipulatorMap: Record<string, Manipulator> = {}
      for (const manipulator of manipulatorResponse.data.items) {
        manipulatorMap[manipulator.name] = manipulator
      }

      // config에 사용된 operator가 등록된 manipulator인지 검증
      const unknownOperators: string[] = []
      for (const task of Object.values(config.tasks)) {
        if (task.operator !== 'merge_datasets' && !manipulatorMap[task.operator]) {
          unknownOperators.push(task.operator)
        }
      }
      if (unknownOperators.length > 0) {
        setJsonLoadError(
          `등록되지 않은 operator가 포함되어 있습니다: ${unknownOperators.join(', ')}`,
        )
        setIsJsonLoading(false)
        return
      }

      // 3. 소스 dataset 표시 정보 조회
      const sourceDatasetIds = extractSourceDatasetIdsFromConfig(config)
      const datasetDisplayMap: Record<string, DatasetDisplayInfo> = {}

      for (const datasetId of sourceDatasetIds) {
        try {
          const datasetResponse = await datasetsApi.get(datasetId)
          const dataset = datasetResponse.data
          const groupResponse = await datasetGroupsApi.get(dataset.group_id)
          const group = groupResponse.data

          datasetDisplayMap[datasetId] = {
            datasetId,
            groupId: dataset.group_id,
            groupName: group.name,
            split: dataset.split,
            version: dataset.version,
          }
        } catch {
          // 삭제된 데이터셋이면 표시 정보 없이 진행 (ID만 표시)
          console.warn(`데이터셋 조회 실패 (삭제되었을 수 있음): ${datasetId}`)
        }
      }

      // 4. 역변환 실행
      const { nodes: restoredNodes, edges: restoredEdges, nodeDataMap: restoredNodeDataMap } =
        pipelineConfigToGraph(config, manipulatorMap, datasetDisplayMap)

      // 5. 캔버스에 적용 (기존 내용 교체)
      reset()
      setNodes(restoredNodes)
      setEdges(restoredEdges)
      for (const [nodeId, data] of Object.entries(restoredNodeDataMap)) {
        setNodeData(nodeId, data)
      }

      setIsJsonLoadModalOpen(false)
      message.success(`파이프라인 복원 완료 (노드 ${restoredNodes.length}개, 엣지 ${restoredEdges.length}개)`)
    } catch (err) {
      setJsonLoadError(`복원 중 오류 발생: ${(err as Error).message}`)
    } finally {
      setIsJsonLoading(false)
    }
  }, [jsonLoadInput, reset, setNodes, setEdges, setNodeData])

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 상단 툴바 */}
      <EditorToolbar
        onValidate={handleValidate}
        onExecute={handleExecute}
        onClearCanvas={handleClearCanvas}
        onLoadJson={handleOpenJsonLoadModal}
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

      {/* JSON 불러오기 모달 */}
      <Modal
        title="PipelineConfig JSON 불러오기"
        open={isJsonLoadModalOpen}
        onCancel={() => setIsJsonLoadModalOpen(false)}
        onOk={handleLoadJson}
        okText="불러오기"
        cancelText="취소"
        confirmLoading={isJsonLoading}
        okButtonProps={{ disabled: !jsonLoadInput.trim() }}
        width={640}
        destroyOnClose
      >
        <div style={{ marginBottom: 8, color: '#8c8c8c', fontSize: 13 }}>
          PipelineConfig JSON을 붙여넣으면 노드와 연결을 복원합니다.
          기존 캔버스 내용은 교체됩니다.
        </div>
        <Input.TextArea
          rows={16}
          value={jsonLoadInput}
          onChange={(e) => {
            setJsonLoadInput(e.target.value)
            setJsonLoadError(null)
          }}
          placeholder='{"name": "...", "output": {...}, "tasks": {...}}'
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
        {isJsonLoading && (
          <div style={{ marginTop: 12, textAlign: 'center' }}>
            <Spin size="small" />
            <span style={{ marginLeft: 8, color: '#8c8c8c', fontSize: 12 }}>
              manipulator / 데이터셋 정보 조회 중...
            </span>
          </div>
        )}
        {jsonLoadError && (
          <div
            style={{
              marginTop: 8,
              padding: '8px 12px',
              background: '#fff2f0',
              border: '1px solid #ffccc7',
              borderRadius: 4,
              color: '#cf1322',
              fontSize: 12,
            }}
          >
            {jsonLoadError}
          </div>
        )}
      </Modal>
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
