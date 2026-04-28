/**
 * SchemaPreviewSection — 선택된 노드 시점의 Classification head_schema 프리뷰.
 *
 * PropertiesPanel 하단에 위치. 현재 그래프를 config 로 직렬화하여
 * 백엔드 /pipelines/preview-schema 에 보내고, 그 응답을 표시한다.
 *
 * 표시 규칙:
 *   - detection / task_kind=='detection' → 섹션 자체를 숨김
 *   - dataLoad 가 splitId 없음 → "소스를 먼저 선택" 안내
 *   - graph 가 불완전(output 없음, 사이클, 미연결) → config 생성 실패 메시지
 *   - 백엔드 에러 응답 → error_message 를 그대로 표시
 *   - 정상 → head 별 name/multi_label/classes 리스트
 *
 * 300ms debounce 후 호출하여 param 입력 중 과도한 요청을 막는다.
 */
import { useEffect, useMemo, useState } from 'react'
import { useReactFlow } from '@xyflow/react'
import { Typography, Divider, Tag, Alert, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'

import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import { graphToPartialPipelineConfig } from '@/pipeline-sdk'
import { pipelinesApi, type SchemaPreviewResponse } from '@/api/pipeline'
import type { PipelineNode, PipelineEdge, PipelineNodeData, PartialPipelineConfig } from '@/types/pipeline'

const { Text } = Typography

interface Props {
  selectedNodeId: string
  nodeData: PipelineNodeData
}

/** 선택 노드로부터 백엔드에 보낼 target_ref 를 계산. 지원 불가한 노드면 null. */
function resolveTargetRef(
  selectedNodeId: string,
  nodeData: PipelineNodeData,
): { ref: string } | { ref: null; reason: string } {
  if (nodeData.type === 'dataLoad') {
    // v7.10 (027 §4-1): splitId 우선. v1 datasetId 는 legacy 호환.
    const dl = nodeData as { splitId?: string | null; datasetId?: string | null }
    const sourceRef = dl.splitId ?? dl.datasetId ?? null
    if (!sourceRef) {
      return { ref: null, reason: '소스 데이터셋을 먼저 선택하세요.' }
    }
    return { ref: `source:${sourceRef}` }
  }
  if (nodeData.type === 'operator' || nodeData.type === 'merge') {
    return { ref: `task_${selectedNodeId}` }
  }
  if (nodeData.type === 'save') {
    return { ref: null, reason: 'Save 노드는 상단 노드를 선택해 결과를 확인하세요.' }
  }
  if (nodeData.type === 'placeholder') {
    return { ref: null, reason: '인식되지 않은 노드라 프리뷰를 생성할 수 없습니다.' }
  }
  return { ref: null, reason: '이 노드는 schema 프리뷰를 지원하지 않습니다.' }
}

/** graph → partial config 직렬화. Save 없이도 동작. 실패 시 사유 반환. */
function tryBuildPartialConfig(
  nodes: PipelineNode[],
  edges: PipelineEdge[],
  nodeDataMap: Record<string, PipelineNodeData>,
): { ok: true; config: PartialPipelineConfig } | { ok: false; reason: string } {
  try {
    const config = graphToPartialPipelineConfig(nodes, edges, nodeDataMap)
    return { ok: true, config }
  } catch (err) {
    return { ok: false, reason: (err as Error).message }
  }
}

export default function SchemaPreviewSection({ selectedNodeId, nodeData }: Props) {
  const reactFlow = useReactFlow<PipelineNode, PipelineEdge>()
  const nodeDataMap = usePipelineEditorStore((s) => s.nodeDataMap)

  // 현재 그래프 snapshot. selectedNodeId / nodeDataMap 변화에 의존.
  const { nodes, edges } = useMemo(() => {
    return { nodes: reactFlow.getNodes(), edges: reactFlow.getEdges() }
    // reactFlow 인스턴스는 동일성 유지되므로 deps 에 selectedNodeId/nodeDataMap 만 넣는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId, nodeDataMap, reactFlow])

  const target = resolveTargetRef(selectedNodeId, nodeData)

  const buildResult = useMemo(
    () => (target.ref ? tryBuildPartialConfig(nodes, edges, nodeDataMap) : null),
    [nodes, edges, nodeDataMap, target.ref],
  )

  // 300ms debounce: target.ref + config 가 안정되면 호출.
  const [debouncedKey, setDebouncedKey] = useState<string | null>(null)
  useEffect(() => {
    if (!target.ref || !buildResult || !buildResult.ok) {
      setDebouncedKey(null)
      return
    }
    const handle = setTimeout(() => {
      setDebouncedKey(`${target.ref}::${JSON.stringify(buildResult.config)}`)
    }, 300)
    return () => clearTimeout(handle)
  }, [target.ref, buildResult])

  const { data: previewResponse, isFetching } = useQuery<SchemaPreviewResponse>({
    queryKey: ['schema-preview', debouncedKey],
    queryFn: async () => {
      if (!target.ref || !buildResult || !buildResult.ok) {
        throw new Error('preview 조건 미충족')
      }
      const response = await pipelinesApi.previewSchema(buildResult.config, target.ref)
      return response.data
    },
    enabled: debouncedKey !== null,
    staleTime: 30_000,
  })

  // detection 파이프라인이면 섹션 자체를 숨긴다.
  if (previewResponse?.task_kind === 'detection') return null

  return (
    <>
      <Divider style={{ margin: '12px 0 8px' }} />
      <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
        노드 시점 Classification Schema
      </Text>

      {target.ref === null && (
        <Text type="secondary" style={{ fontSize: 11 }}>{target.reason}</Text>
      )}

      {target.ref !== null && buildResult && !buildResult.ok && (
        <Alert
          type="info"
          showIcon
          style={{ fontSize: 11 }}
          message="프리뷰 불가"
          description={buildResult.reason}
        />
      )}

      {target.ref !== null && buildResult?.ok && isFetching && !previewResponse && (
        <div style={{ padding: 8, textAlign: 'center' }}>
          <Spin size="small" />
        </div>
      )}

      {previewResponse?.error_message && (
        <Alert
          type="warning"
          showIcon
          style={{ fontSize: 11 }}
          message="프리뷰 에러"
          description={previewResponse.error_message}
        />
      )}

      {previewResponse &&
        previewResponse.task_kind === 'classification' &&
        !previewResponse.error_message && (
          <SchemaList heads={previewResponse.head_schema ?? []} />
        )}
    </>
  )
}

function SchemaList({ heads }: { heads: { name: string; multi_label: boolean; classes: string[] }[] }) {
  if (heads.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Head 없음" />
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {heads.map((head) => (
        <div
          key={head.name}
          style={{
            border: '1px solid #f0f0f0',
            borderRadius: 4,
            padding: '6px 8px',
            background: '#fff',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
            <Text strong style={{ fontSize: 12 }}>{head.name}</Text>
            {head.multi_label && (
              <Tag color="purple" style={{ fontSize: 10, margin: 0 }}>multi</Tag>
            )}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {head.classes.map((className, idx) => (
              <Tag key={className} style={{ fontSize: 10, margin: 0 }}>
                [{idx}] {className}
              </Tag>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
