/**
 * SaveDefinition — 파이프라인 출력 설정 싱크 노드.
 *
 * 정확히 1개만 존재해야 한다. name / output 설정이 PipelineConfig 루트로 병합된다.
 */
import { memo } from 'react'
import type { NodeProps } from '@xyflow/react'
import { Input, Select, Tag, Typography, Divider } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { useNodeData, useSetNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import type { NodeDefinition } from '../types'
import type { SaveNodeData, PipelineValidationIssue } from '@/types/pipeline'

const { Text } = Typography

const SAVE_COLOR = '#fa541c'
const SAVE_EMOJI = '💾'

const DATASET_TYPE_OPTIONS = [
  { value: 'SOURCE', label: 'SOURCE' },
  { value: 'PROCESSED', label: 'PROCESSED' },
  { value: 'FUSION', label: 'FUSION' },
]
const SPLIT_OPTIONS = [
  { value: 'TRAIN', label: 'TRAIN' },
  { value: 'VAL', label: 'VAL' },
  { value: 'TEST', label: 'TEST' },
  { value: 'NONE', label: 'NONE' },
]

// 현재 에디터의 taskType 에 따라 annotation_format 선택지가 달라진다.
// DETECTION  : COCO / YOLO  (기존 그대로)
// CLASSIFICATION: CLS_MANIFEST 만 허용 (manifest.jsonl + head_schema.json 규약)
const DETECTION_FORMAT_OPTIONS = [
  { value: 'COCO', label: 'COCO' },
  { value: 'YOLO', label: 'YOLO' },
]
const CLASSIFICATION_FORMAT_OPTIONS = [
  { value: 'CLS_MANIFEST', label: 'CLS_MANIFEST' },
]

function getFormatOptionsForTaskType(taskType: string) {
  if (taskType === 'CLASSIFICATION') return CLASSIFICATION_FORMAT_OPTIONS
  return DETECTION_FORMAT_OPTIONS
}

function getDefaultFormatForTaskType(taskType: string): string {
  if (taskType === 'CLASSIFICATION') return 'CLS_MANIFEST'
  return 'COCO'
}

const SaveNodeComponent = memo(function SaveNodeInner({ id }: NodeProps) {
  const nodeData = useNodeData<'save'>(id)
  const setNodeData = useSetNodeData()
  const [searchParams] = useSearchParams()
  const taskType = searchParams.get('taskType') ?? 'DETECTION'
  const formatOptions = getFormatOptionsForTaskType(taskType)
  if (!nodeData) return null

  const updateField = <K extends keyof SaveNodeData>(key: K, value: SaveNodeData[K]) => {
    setNodeData(id, { ...nodeData, [key]: value })
  }

  return (
    <NodeShell
      color={SAVE_COLOR}
      emoji={SAVE_EMOJI}
      headerLabel="Save (출력 설정)"
      inputs={{ count: 1 }}
      outputs="none"
      issues={nodeData.validationIssues ?? []}
      minWidth={240}
    >
      <div className="nopan nodrag" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>출력 이름 *</Text>
          <Input
            size="small"
            placeholder="출력 DatasetGroup 이름"
            value={nodeData.name}
            onChange={(e) => updateField('name', e.target.value)}
          />
        </div>
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>데이터셋 타입</Text>
          <Select
            size="small"
            value={nodeData.datasetType}
            options={DATASET_TYPE_OPTIONS}
            style={{ width: '100%' }}
            onChange={(val) => updateField('datasetType', val)}
          />
        </div>
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>Split</Text>
          <Select
            size="small"
            value={nodeData.split}
            options={SPLIT_OPTIONS}
            style={{ width: '100%' }}
            onChange={(val) => updateField('split', val)}
          />
        </div>
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>어노테이션 포맷</Text>
          <Select
            size="small"
            value={nodeData.annotationFormat ?? getDefaultFormatForTaskType(taskType)}
            options={formatOptions}
            style={{ width: '100%' }}
            onChange={(val) => updateField('annotationFormat', val)}
          />
        </div>
      </div>
    </NodeShell>
  )
})

function SavePropertiesComponent() {
  return (
    <>
      <Tag color="orange">Save</Tag>
      <Divider style={{ margin: '8px 0' }} />
      <Text type="secondary" style={{ fontSize: 12 }}>
        출력 설정은 노드에서 직접 편집합니다.
      </Text>
    </>
  )
}

export const saveDefinition: NodeDefinition<'save'> = {
  kind: 'save',
  palette: {
    section: 'basic',
    label: 'Save (출력 설정)',
    color: SAVE_COLOR,
    emoji: SAVE_EMOJI,
    order: 30,
    createDefaultData: (ctx) => ({
      type: 'save',
      name: '',
      description: '',
      datasetType: 'PROCESSED',
      // taskType 에 따라 기본 포맷이 달라진다 — classification 은 CLS_MANIFEST 고정.
      annotationFormat: getDefaultFormatForTaskType(ctx.taskType),
      split: 'NONE',
    }),
  },
  NodeComponent: SaveNodeComponent,
  PropertiesComponent: SavePropertiesComponent,

  validate(data, ctx) {
    const errors = []
    if (!data.name.trim()) {
      errors.push({ nodeId: ctx.nodeId, message: 'Save 노드에 출력 이름을 입력해 주세요.' })
    }
    const incoming = ctx.edges.filter((e) => e.target === ctx.nodeId)
    if (incoming.length === 0) {
      errors.push({ nodeId: ctx.nodeId, message: 'Save 노드에 입력 연결이 없습니다.' })
    }
    return errors
  },

  // SaveNode는 task를 발생시키지 않고 PipelineConfig 루트(name/output)만 기여.
  // Load→Save 직결(incoming edge source 가 dataLoad) 이면 passthrough_source_dataset_id 도 추가한다.
  toConfigContribution(data, ctx) {
    let passthroughSourceId: string | undefined
    if (ctx.incomingEdges.length === 1) {
      const sourceData = ctx.getNodeData(ctx.incomingEdges[0].source)
      if (sourceData?.type === 'dataLoad' && sourceData.datasetId) {
        passthroughSourceId = sourceData.datasetId
      }
    }
    return {
      root: {
        name: data.name.trim(),
        description: data.description?.trim() || undefined,
        output: {
          dataset_type: data.datasetType,
          annotation_format: data.annotationFormat || null,
          split: data.split,
        },
        ...(passthroughSourceId ? { passthrough_source_dataset_id: passthroughSourceId } : {}),
      },
    }
  },

  // Config → Graph 복원. name/output으로부터 단일 SaveNode 생성.
  matchFromConfig(ctx) {
    const { config } = ctx
    const nodeId = `save_${Date.now()}`
    const data: SaveNodeData = {
      type: 'save',
      name: config.name,
      description: config.description ?? '',
      datasetType: config.output.dataset_type as SaveNodeData['datasetType'],
      annotationFormat: config.output.annotation_format,
      split: config.output.split as SaveNodeData['split'],
    }
    return [{ nodeId, data, ownedTaskKeys: [] }]
  },

  matchIssueField(issue: PipelineValidationIssue) {
    return issue.field.startsWith('output.') || issue.field === 'name'
  },
}
