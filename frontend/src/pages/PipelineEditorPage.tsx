/**
 * PipelineEditorPage — 전체화면 ComfyUI 스타일 노드 에디터.
 *
 * 노드 타입별 분기는 SDK(pipeline-sdk)가 전담.
 * 이 파일은 React Flow 배선, 툴바 이벤트, JSON 불러오기/저장 오케스트레이션만 담당.
 */

import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
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
import { message, ConfigProvider, theme, Modal, Input, Spin, Radio, Select, Alert } from 'antd'
import koKR from 'antd/locale/ko_KR'
import { useQuery } from '@tanstack/react-query'

import NodePalette from '@/components/pipeline/NodePalette'
import EditorToolbar from '@/components/pipeline/EditorToolbar'
import PropertiesPanel from '@/components/pipeline/PropertiesPanel'
import PipelineJsonPreview from '@/components/pipeline/PipelineJsonPreview'

import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import {
  validateGraphStructure,
  graphToPipelineConfig,
  graphToPartialPipelineConfig,
  pipelineConfigToGraph,
  unresolveVersionRefsToSplitRefs,
  parseSourceRef,
  buildNodeTypesFromRegistry,
} from '@/pipeline-sdk'
import type { DatasetDisplayInfo } from '@/pipeline-sdk'
import {
  pipelineConceptsApi,
  pipelinesApi,
  manipulatorsApi,
  datasetsForPipelineApi,
} from '@/api/pipeline'
import { MERGE_OPERATORS } from '@/pipeline-sdk/definitions/mergeDefinition'
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
  const navigate = useNavigate()

  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<PipelineEdge>([])
  const [isValidating, setIsValidating] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [jsonPreviewContent, setJsonPreviewContent] = useState('')
  const [jsonPreviewError, setJsonPreviewError] = useState<string | null>(null)
  const [isJsonLoadModalOpen, setIsJsonLoadModalOpen] = useState(false)
  const [jsonLoadInput, setJsonLoadInput] = useState('')
  const [isJsonLoading, setIsJsonLoading] = useState(false)
  const [jsonLoadError, setJsonLoadError] = useState<string | null>(null)
  // 저장 모달 — 사용자가 파이프라인명을 확정/변경하는 단계 (§12-2 #1).
  // 두 모드:
  //   'manual' (기본) — 텍스트 입력. 기본값 = `${config.name}_${split.lower()}`.
  //                     동일 이름 + 다른 출력은 backend 가 400 으로 차단.
  //   'select' — 같은 task_type + 같은 output_split_id 인 Pipeline 후보를 dropdown
  //              으로 노출. 선택 시 그 이름이 concept_name 으로 전달돼 새 version
  //              이 추가됨. 출력이 같음이 보장돼 회색지대 없음.
  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false)
  const [pendingConfig, setPendingConfig] = useState<PipelineConfig | null>(null)
  const [pendingOutputSplitId, setPendingOutputSplitId] = useState<string | null>(null)
  const [saveMode, setSaveMode] = useState<'manual' | 'select'>('manual')
  const [conceptNameInput, setConceptNameInput] = useState('')
  const [selectedExistingPipelineId, setSelectedExistingPipelineId] = useState<string | null>(null)

  const {
    nodeDataMap,
    setNodeData,
    removeNodeData,
    setSelectedNode,
    isJsonPreviewOpen,
    setValidationResult,
    applyValidationToNodes,
    clearValidation,
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

  // JSON 프리뷰 업데이트 — Save 없이도 DataLoad 기반 partial config 표시
  useMemo(() => {
    if (!isJsonPreviewOpen) return
    try {
      const config = graphToPartialPipelineConfig(nodes, edges, nodeDataMap)
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
        message.success('검증 통과! 저장할 수 있습니다.')
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

  // 출력 split_id 산출용 — 데이터셋 그룹 캐시 (DataLoad 노드와 같은 캐시).
  // config.name (= group name) + dataset_type + split 으로 split_id 매핑.
  const groupsForSplitLookupQuery = useQuery({
    queryKey: ['dataset-groups-for-pipeline-save'],
    queryFn: () => datasetsForPipelineApi.listGroups({ page_size: 200 }).then((r) => r.data),
    staleTime: 30_000,
  })

  // 후보 Pipeline (concept) 목록 — 같은 task_type + 같은 output_split_id.
  // pendingOutputSplitId 가 있을 때만 fetch.
  const existingPipelinesQuery = useQuery({
    queryKey: ['save-modal-existing-pipelines', taskType, pendingOutputSplitId],
    queryFn: () =>
      pendingOutputSplitId
        ? pipelineConceptsApi
            .list({
              task_type: [taskType],
              output_split_id: [pendingOutputSplitId],
              include_inactive: true,
              limit: 100,
            })
            .then((r) => r.data)
        : null,
    enabled: !!pendingOutputSplitId && isSaveModalOpen,
  })

  // 저장 버튼 클릭 → 클라이언트/서버 검증 → 검증 통과 시 저장 모달 오픈.
  // 모달 안에서 사용자가 파이프라인명을 확정한 뒤에야 실제 API 호출 (handleConfirmSave).
  const handleSave = useCallback(async () => {
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
    setIsSaving(true)
    try {
      const validateResponse = await pipelinesApi.validate(config)
      const validateResult = validateResponse.data
      setValidationResult(validateResult)
      applyValidationToNodes(validateResult.issues)
      if (!validateResult.is_valid) {
        message.error(`검증 실패 (오류 ${validateResult.error_count}개). 저장할 수 없습니다.`)
        return
      }
      // 검증 통과 → 모달 오픈 + 기본 이름 prefill (backend 자동 규칙과 동일).
      setPendingConfig(config)
      const splitLower = (config.output?.split ?? 'NONE').toLowerCase()
      const splitUpper = (config.output?.split ?? 'NONE').toUpperCase()
      const datasetType = (config.output?.dataset_type ?? '').toUpperCase()
      setConceptNameInput(`${config.name}_${splitLower}`)
      // 출력 split_id 매핑 — 그룹 캐시에서 (group_name + dataset_type) 매칭 후
      // datasets[] 에서 split 매칭. 신규 그룹/Split 케이스는 미리 만들어진 게
      // 없을 수 있어 null 그대로 두고 select 모드 비활성.
      const groups = groupsForSplitLookupQuery.data?.items ?? []
      const targetGroup = groups.find(
        (g) => g.name === config.name && g.dataset_type === datasetType,
      )
      const targetSplitId =
        targetGroup?.datasets?.find((d) => d.split === splitUpper)?.split_id ?? null
      setPendingOutputSplitId(targetSplitId)
      setSaveMode('manual')
      setSelectedExistingPipelineId(null)
      setIsSaveModalOpen(true)
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `검증 실패: ${detail}` : '검증 API 호출 실패')
      console.error('Validate API error:', err)
    } finally {
      setIsSaving(false)
    }
  }, [
    nodes, edges, nodeDataMap, clearValidation,
    setValidationResult, applyValidationToNodes,
    groupsForSplitLookupQuery.data,
  ])

  const handleConfirmSave = useCallback(async () => {
    if (!pendingConfig) return
    let conceptName: string
    if (saveMode === 'select') {
      const candidates = existingPipelinesQuery.data?.items ?? []
      const chosen = candidates.find((p) => p.id === selectedExistingPipelineId)
      if (!chosen) {
        message.error('기존 Pipeline 을 선택해 주세요.')
        return
      }
      conceptName = chosen.name
    } else {
      const trimmed = conceptNameInput.trim()
      if (!trimmed) {
        message.error('파이프라인명을 입력해 주세요.')
        return
      }
      conceptName = trimmed
    }
    setIsSaving(true)
    try {
      const saveResponse = await pipelineConceptsApi.save(pendingConfig, conceptName)
      const saveResult = saveResponse.data
      message.success(saveResult.message)
      setIsSaveModalOpen(false)
      setPendingConfig(null)
      setPendingOutputSplitId(null)
      // 저장 후 파이프라인 목록으로 — 행 우측 "실행" 버튼으로 Version Resolver 진입.
      navigate('/pipelines')
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `저장 실패: ${detail}` : '저장 API 호출 실패')
      console.error('Save API error:', err)
    } finally {
      setIsSaving(false)
    }
  }, [
    pendingConfig, saveMode, conceptNameInput,
    selectedExistingPipelineId, existingPipelinesQuery.data, navigate,
  ])

  const handleCancelSave = useCallback(() => {
    setIsSaveModalOpen(false)
    setPendingConfig(null)
    setPendingOutputSplitId(null)
    setSelectedExistingPipelineId(null)
  }, [])

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
    let parsedConfig: PipelineConfig
    try {
      parsedConfig = JSON.parse(jsonLoadInput)
    } catch {
      setJsonLoadError('유효하지 않은 JSON 형식입니다.')
      return
    }
    if (!parsedConfig.name || !parsedConfig.output || !parsedConfig.tasks) {
      setJsonLoadError('PipelineConfig 형식이 아닙니다. name, output, tasks 필드가 필요합니다.')
      return
    }

    setIsJsonLoading(true)
    setJsonLoadError(null)

    try {
      // manipulator 메타 + 데이터셋 그룹(+ datasets[]) 일괄 조회.
      // listGroups 응답의 group.datasets[] 가 split_id / version 을 모두 들고 있어,
      // dataset_split / dataset_version 두 토큰 모두 한 번의 호출로 해석할 수 있다.
      const [manipulatorResponse, groupsResponse] = await Promise.all([
        manipulatorsApi.list({ status: 'ACTIVE' }),
        datasetsForPipelineApi.listGroups({ page_size: 200 }),
      ])
      const manipulatorMap: Record<string, Manipulator> = {}
      for (const manipulator of manipulatorResponse.data.items) {
        manipulatorMap[manipulator.name] = manipulator
      }

      // 그룹 datasets 를 한 번 훑어 split_id → 표시정보 / version_id → split_id 두 인덱스 구축.
      const splitIdToDisplay: Record<string, DatasetDisplayInfo> = {}
      const versionIdToSplitId: Record<string, string> = {}
      for (const group of groupsResponse.data.items) {
        for (const ds of group.datasets ?? []) {
          // 같은 split 의 어느 version 이든 group/split 표시는 동일 — 첫 발견만 기록.
          if (!splitIdToDisplay[ds.split_id]) {
            splitIdToDisplay[ds.split_id] = {
              datasetId: ds.id,
              groupId: group.id,
              groupName: group.name,
              split: ds.split,
              version: ds.version,
            }
          }
          versionIdToSplitId[ds.id] = ds.split_id
        }
      }

      // schema_version 체크 — 상위 버전이면 경고만 (best-effort 복원).
      if (typeof parsedConfig.schema_version === 'number' && parsedConfig.schema_version > 3) {
        message.warning(
          `이 config 는 더 최신 버전 (v${parsedConfig.schema_version}) 에서 만들어졌습니다. 일부 항목이 누락될 수 있습니다.`,
        )
      }

      // PipelineRun.transform_config 케이스: source:dataset_version:<id> → source:dataset_split:<id>
      // 환원. Pipeline.config 케이스는 이미 dataset_split 만 들고 있어 토큰 변경 없음.
      const { config: rewrittenConfig, missingVersionIds } = unresolveVersionRefsToSplitRefs(
        parsedConfig,
        versionIdToSplitId,
      )

      // 등록되지 않은 operator (placeholder 복원).
      const unknownOperators: string[] = []
      for (const task of Object.values(rewrittenConfig.tasks)) {
        if (!MERGE_OPERATORS.has(task.operator) && !manipulatorMap[task.operator]) {
          unknownOperators.push(task.operator)
        }
      }

      // 환원 후 inputs 의 split_id 들이 현재 DB 에 있는지 확인.
      // matchFromConfig 가 datasetDisplayMap[splitId] 로 그룹/Split 라벨을 채우므로
      // 누락된 split_id 는 노드 라벨이 source:... 로 표시되고 저장 검증에서 차단된다.
      const referencedSplitIds = new Set<string>()
      for (const task of Object.values(rewrittenConfig.tasks)) {
        for (const input of task.inputs) {
          const refParsed = parseSourceRef(input)
          if (refParsed) referencedSplitIds.add(refParsed.id)
        }
      }
      if (rewrittenConfig.passthrough_source_split_id) {
        referencedSplitIds.add(rewrittenConfig.passthrough_source_split_id)
      }
      const missingSplitIds: string[] = []
      const datasetDisplayMap: Record<string, DatasetDisplayInfo> = {}
      for (const splitId of referencedSplitIds) {
        const display = splitIdToDisplay[splitId]
        if (display) {
          datasetDisplayMap[splitId] = display
        } else {
          missingSplitIds.push(splitId)
        }
      }

      const { nodes: restoredNodes, edges: restoredEdges, nodeDataMap: restoredNodeDataMap } =
        pipelineConfigToGraph(rewrittenConfig, manipulatorMap, datasetDisplayMap)

      reset()
      setNodes(restoredNodes)
      setEdges(restoredEdges)
      for (const [nodeId, data] of Object.entries(restoredNodeDataMap)) {
        setNodeData(nodeId, data)
      }

      setIsJsonLoadModalOpen(false)

      // 안내 메시지 — missing 이 있으면 모달, 없으면 unknown / success 메시지.
      const hasMissing =
        missingVersionIds.length > 0 || missingSplitIds.length > 0
      if (hasMissing) {
        const summarize = (ids: string[]) =>
          ids.slice(0, 3).map((id) => id.slice(0, 8)).join(', ')
            + (ids.length > 3 ? ` 외 ${ids.length - 3}건` : '')
        const fragments: string[] = []
        if (missingVersionIds.length > 0) {
          fragments.push(
            `dataset_version ${missingVersionIds.length}건 (${summarize(missingVersionIds)}) 의 부모 split 을 현재 DB 에서 찾지 못했습니다.`,
          )
        }
        if (missingSplitIds.length > 0) {
          fragments.push(
            `dataset_split ${missingSplitIds.length}건 (${summarize(missingSplitIds)}) 이 현재 DB 에 없습니다.`,
          )
        }
        Modal.warning({
          title: '소스 데이터셋 일부를 해석하지 못했습니다',
          content: (
            <div>
              <div style={{ marginBottom: 8 }}>
                데이터셋이 삭제되었거나 다른 DB 환경의 export 일 수 있습니다.
                해당 노드는 source ID 그대로 표시되며 저장 검증에서 차단됩니다.
              </div>
              {fragments.map((line, idx) => (
                <div key={idx} style={{ fontSize: 12 }}>• {line}</div>
              ))}
            </div>
          ),
        })
      } else if (unknownOperators.length > 0) {
        message.warning(
          `등록되지 않은 operator ${unknownOperators.length}개는 Placeholder 노드로 복원되었습니다. 저장하려면 해당 노드를 교체하세요.`,
        )
      } else {
        message.success(
          `파이프라인 복원 완료 (노드 ${restoredNodes.length}개, 엣지 ${restoredEdges.length}개)`,
        )
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
        onSave={handleSave}
        onClearCanvas={handleClearCanvas}
        onLoadJson={handleOpenJsonLoadModal}
        isValidating={isValidating}
        isSaving={isSaving}
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

      <Modal
        title="파이프라인 저장"
        open={isSaveModalOpen}
        onCancel={handleCancelSave}
        onOk={handleConfirmSave}
        okText="저장"
        cancelText="취소"
        confirmLoading={isSaving}
        okButtonProps={{
          disabled:
            saveMode === 'manual'
              ? !conceptNameInput.trim()
              : !selectedExistingPipelineId,
        }}
        destroyOnClose
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Radio.Group
            value={saveMode}
            onChange={(e) => setSaveMode(e.target.value)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="manual">직접 입력</Radio.Button>
            <Radio.Button value="select" disabled={!pendingOutputSplitId}>
              기존 Pipeline 선택
            </Radio.Button>
          </Radio.Group>

          {saveMode === 'manual' && (
            <>
              <div style={{ color: '#8c8c8c', fontSize: 13 }}>
                파이프라인명을 확인 또는 변경하세요. 같은 이름이 이미 있고
                출력 (group/split) 도 같으면 그 Pipeline 의 새 버전으로
                추가됩니다. 출력이 다르면 저장이 차단됩니다.
              </div>
              <Input
                placeholder="파이프라인명"
                value={conceptNameInput}
                onChange={(e) => setConceptNameInput(e.target.value)}
                onPressEnter={handleConfirmSave}
                autoFocus
              />
            </>
          )}

          {saveMode === 'select' && (
            <>
              <div style={{ color: '#8c8c8c', fontSize: 13 }}>
                같은 task type ({taskType}) + 같은 출력 (group/split) 의
                기존 Pipeline 만 후보로 표시됩니다. 선택 시 그 Pipeline 의
                새 버전으로 추가됩니다.
              </div>
              {existingPipelinesQuery.isLoading ? (
                <Spin size="small" />
              ) : (existingPipelinesQuery.data?.items ?? []).length === 0 ? (
                <Alert
                  type="info"
                  showIcon
                  message="후보 Pipeline 이 없습니다."
                  description="이 출력 (group/split) 으로 저장된 Pipeline 이 아직 없어요. '직접 입력' 모드로 새로 만들어 주세요."
                />
              ) : (
                <Select
                  placeholder="기존 Pipeline 선택"
                  value={selectedExistingPipelineId ?? undefined}
                  onChange={(val) => setSelectedExistingPipelineId(val)}
                  style={{ width: '100%' }}
                  options={(existingPipelinesQuery.data?.items ?? []).map((p) => ({
                    value: p.id,
                    label: (
                      <span>
                        {p.name}
                        {p.latest_version && (
                          <span style={{ color: '#8c8c8c', marginLeft: 6, fontSize: 12 }}>
                            (최신 v{p.latest_version})
                          </span>
                        )}
                        {!p.is_active && (
                          <span style={{ color: '#bfbfbf', marginLeft: 6, fontSize: 11 }}>
                            · 비활성
                          </span>
                        )}
                      </span>
                    ),
                  }))}
                />
              )}
            </>
          )}
        </div>
      </Modal>

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
