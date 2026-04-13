/**
 * PipelineEditorPage — 전체화면 ComfyUI 스타일 노드 에디터.
 *
 * 노드 타입별 분기는 SDK(pipeline-sdk)가 전담.
 * 이 파일은 React Flow 배선, 툴바 이벤트, JSON 불러오기/저장 오케스트레이션만 담당.
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
  ReactFlowProvider,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { message, ConfigProvider, theme, Modal, Input, Spin } from 'antd'
import koKR from 'antd/locale/ko_KR'

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
  buildNodeTypesFromRegistry,
} from '@/pipeline-sdk'
import type { DatasetDisplayInfo } from '@/pipeline-sdk'
import { pipelinesApi, manipulatorsApi } from '@/api/pipeline'
import { datasetsApi, datasetGroupsApi } from '@/api/dataset'
import type {
  PipelineConfig,
  PipelineNodeData,
  PipelineNode,
  PipelineEdge,
} from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'

// React Flow 커스텀 노드 타입 — SDK registry에서 자동 생성
const nodeTypes = buildNodeTypesFromRegistry()

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
    isJsonPreviewOpen,
    setValidationResult,
    applyValidationToNodes,
    clearValidation,
    setExecutionId,
    reset,
  } = usePipelineEditorStore()

  // Merge 노드 외에는 입력 엣지 1개만 허용
  const onConnect: OnConnect = useCallback(
    (connection) => {
      const targetNodeId = connection.target
      if (!targetNodeId) return
      const targetData = nodeDataMap[targetNodeId]
      const isMergeNode = targetData?.type === 'merge'
      if (!isMergeNode) {
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

  // 노드 삭제 시 store 동기화
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

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: PipelineNode) => setSelectedNode(node.id),
    [setSelectedNode],
  )
  const handlePaneClick = useCallback(() => setSelectedNode(null), [setSelectedNode])

  // 팔레트에서 노드 추가 — data.type이 곧 React Flow의 node.type
  const handleAddNode = useCallback(
    (data: PipelineNodeData) => {
      const newId = generateNodeId()
      const offsetX = 300 + Math.random() * 200
      const offsetY = 100 + Math.random() * 200

      const newNode: PipelineNode = {
        id: newId,
        type: data.type,
        position: { x: offsetX, y: offsetY },
        data: data as PipelineNode['data'],
      }
      setNodes((nds) => [...nds, newNode])
      setNodeData(newId, data)
      setSelectedNode(newId)
    },
    [setNodes, setNodeData, setSelectedNode],
  )

  // JSON 프리뷰 업데이트
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

  const handleValidate = useCallback(async () => {
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

  const handleExecute = useCallback(async () => {
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

  const handleClearCanvas = useCallback(() => {
    setNodes([])
    setEdges([])
    reset()
  }, [setNodes, setEdges, reset])

  const handleOpenJsonLoadModal = useCallback(() => {
    setJsonLoadInput('')
    setJsonLoadError(null)
    setIsJsonLoadModalOpen(true)
  }, [])

  const handleLoadJson = useCallback(async () => {
    let config: PipelineConfig
    try {
      config = JSON.parse(jsonLoadInput)
    } catch {
      setJsonLoadError('유효하지 않은 JSON 형식입니다.')
      return
    }
    if (!config.name || !config.output || !config.tasks) {
      setJsonLoadError('PipelineConfig 형식이 아닙니다. name, output, tasks 필드가 필요합니다.')
      return
    }

    setIsJsonLoading(true)
    setJsonLoadError(null)

    try {
      // manipulator 메타 조회
      const manipulatorResponse = await manipulatorsApi.list({ status: 'ACTIVE' })
      const manipulatorMap: Record<string, Manipulator> = {}
      for (const manipulator of manipulatorResponse.data.items) {
        manipulatorMap[manipulator.name] = manipulator
      }

      // 등록되지 않은 operator가 있어도 placeholder 노드로 복원되므로 에러로 막지 않음.
      // 사용자에게 경고만 표시.
      const unknownOperators: string[] = []
      for (const task of Object.values(config.tasks)) {
        if (task.operator !== 'merge_datasets' && !manipulatorMap[task.operator]) {
          unknownOperators.push(task.operator)
        }
      }

      // 소스 dataset 표시 정보 조회
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
          console.warn(`데이터셋 조회 실패 (삭제되었을 수 있음): ${datasetId}`)
        }
      }

      // schema_version 체크 — 상위 버전이면 경고만 (best-effort 복원)
      if (typeof config.schema_version === 'number' && config.schema_version > 1) {
        message.warning(
          `이 config는 더 최신 버전(v${config.schema_version})에서 만들어졌습니다. 일부 항목이 누락될 수 있습니다.`,
        )
      }

      const { nodes: restoredNodes, edges: restoredEdges, nodeDataMap: restoredNodeDataMap } =
        pipelineConfigToGraph(config, manipulatorMap, datasetDisplayMap)

      reset()
      setNodes(restoredNodes)
      setEdges(restoredEdges)
      for (const [nodeId, data] of Object.entries(restoredNodeDataMap)) {
        setNodeData(nodeId, data)
      }

      setIsJsonLoadModalOpen(false)
      if (unknownOperators.length > 0) {
        message.warning(
          `등록되지 않은 operator ${unknownOperators.length}개는 Placeholder 노드로 복원되었습니다. 실행하려면 해당 노드를 교체하세요.`,
        )
      } else {
        message.success(`파이프라인 복원 완료 (노드 ${restoredNodes.length}개, 엣지 ${restoredEdges.length}개)`)
      }
    } catch (err) {
      setJsonLoadError(`복원 중 오류 발생: ${(err as Error).message}`)
    } finally {
      setIsJsonLoading(false)
    }
  }, [jsonLoadInput, reset, setNodes, setEdges, setNodeData])

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <EditorToolbar
        onValidate={handleValidate}
        onExecute={handleExecute}
        onClearCanvas={handleClearCanvas}
        onLoadJson={handleOpenJsonLoadModal}
        isValidating={isValidating}
        isExecuting={isExecuting}
        taskType={taskType}
      />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <NodePalette onAddNode={handleAddNode} taskType={taskType} />

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

        {isJsonPreviewOpen && (
          <PipelineJsonPreview jsonString={jsonPreviewContent} error={jsonPreviewError} />
        )}

        <PropertiesPanel />
      </div>

      <ExecutionSubmittedModal />

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
          PipelineConfig JSON을 붙여넣으면 노드와 연결을 복원합니다. 기존 캔버스 내용은 교체됩니다.
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
