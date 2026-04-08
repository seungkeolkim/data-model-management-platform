/**
 * SaveNode — 파이프라인 출력 설정 싱크 노드
 *
 * 파이프라인의 최종 출력을 정의한다.
 * 입력 핸들만 존재하며, PipelineConfig의 name + output에 매핑된다.
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Input, Select, Tag, Typography } from 'antd'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import type { SaveNodeData } from '@/types/pipeline'
import { SPECIAL_NODE_STYLE } from '../nodeStyles'

const { Text } = Typography

const SV = SPECIAL_NODE_STYLE.SAVE
const SAVE_COLOR = SV.color

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

const FORMAT_OPTIONS = [
  { value: '', label: '자동 (입력 포맷 유지)' },
  { value: 'COCO', label: 'COCO' },
  { value: 'YOLO', label: 'YOLO' },
]

function SaveNodeComponent({ id }: NodeProps) {
  // Zustand store에서 직접 구독 — store 변경 시 즉시 re-render
  const nodeData = usePipelineEditorStore(
    (s) => (s.nodeDataMap[id] as SaveNodeData) ?? null,
  )
  const setNodeData = usePipelineEditorStore((s) => s.setNodeData)

  if (!nodeData) return null

  const hasErrors = (nodeData.validationIssues ?? []).some((i) => i.severity === 'error')
  const hasWarnings = (nodeData.validationIssues ?? []).some((i) => i.severity === 'warning')
  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : SAVE_COLOR

  const updateField = <K extends keyof SaveNodeData>(key: K, value: SaveNodeData[K]) => {
    setNodeData(id, { ...nodeData, [key]: value })
  }

  return (
    <div
      style={{
        background: '#fff',
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        minWidth: 240,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      {/* 입력 핸들 */}
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 10,
          height: 10,
          background: SAVE_COLOR,
          border: '2px solid #fff',
        }}
      />

      {/* 헤더 */}
      <div
        style={{
          background: SAVE_COLOR,
          color: '#fff',
          padding: '6px 12px',
          borderRadius: '6px 6px 0 0',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        <span>{SV.emoji}</span>
        Save (출력 설정)
      </div>

      {/* 본문 — 인라인 폼
           nopan nodrag: React Flow 이벤트 방지하여 폼 조작이 정상 동작하도록 */}
      <div className="nopan nodrag" style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
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
            value={nodeData.annotationFormat ?? ''}
            options={FORMAT_OPTIONS}
            style={{ width: '100%' }}
            onChange={(val) => updateField('annotationFormat', val || null)}
          />
        </div>

        {/* 검증 이슈 */}
        {(nodeData.validationIssues ?? []).length > 0 && (
          <div style={{ marginTop: 2 }}>
            {nodeData.validationIssues!.map((issue, idx) => (
              <Tag
                key={idx}
                color={issue.severity === 'error' ? 'error' : 'warning'}
                style={{ fontSize: 10, marginTop: 2 }}
              >
                {issue.message}
              </Tag>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default memo(SaveNodeComponent)
