/**
 * DataLoadNode — 소스 데이터셋 3단계 선택 노드
 *
 * 1단계: 데이터셋 그룹 선택 (삭제 안 된, DETECTION 태스크 타입 포함 그룹)
 * 2단계: Split 선택 (선택된 그룹의 READY 데이터셋에서 존재하는 split 추출)
 * 3단계: 버전 선택 (선택된 그룹+split의 READY 데이터셋 버전 목록)
 *
 * 상위 항목 변경 시 하위 항목은 초기화된다.
 * 최종 선택된 dataset_id가 하위 노드의 inputs에 "source:<dataset_id>"로 변환된다.
 *
 * 중요: React Flow node.data가 아닌 Zustand store의 nodeDataMap을 직접 구독하여
 * store 변경 시 즉시 re-render 되도록 한다.
 */

import { memo, useMemo } from 'react'
import { Handle, Position } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import { Select, Typography, Tag } from 'antd'
import { DatabaseOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { datasetsForPipelineApi } from '@/api/pipeline'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'
import type { DataLoadNodeData } from '@/types/pipeline'
import type { DatasetGroup, DatasetSummary } from '@/types/dataset'

const { Text } = Typography

/** 그룹이 DETECTION 태스크 타입을 포함하는지 확인 */
function isDetectionGroup(group: DatasetGroup): boolean {
  if (!group.task_types || group.task_types.length === 0) return true
  return group.task_types.includes('DETECTION')
}

/** READY 상태인 데이터셋만 필터 */
function readyDatasets(datasets: DatasetSummary[]): DatasetSummary[] {
  return datasets.filter((ds) => ds.status === 'READY')
}

function DataLoadNodeComponent({ id }: NodeProps) {
  // Zustand store에서 직접 구독 — store 변경 시 즉시 re-render
  const nodeData = usePipelineEditorStore(
    (s) => (s.nodeDataMap[id] as DataLoadNodeData) ?? null,
  )
  const setNodeData = usePipelineEditorStore((s) => s.setNodeData)

  // ── 1단계: 그룹 목록 조회 ──
  const { data: groupsResponse, isLoading: groupsLoading } = useQuery({
    queryKey: ['dataset-groups-for-pipeline'],
    queryFn: () => datasetsForPipelineApi.listGroups().then((r) => r.data),
    staleTime: 30_000,
  })

  // DETECTION 타입 + READY 데이터셋이 1개 이상인 그룹만 표시
  const availableGroups = useMemo(() => {
    const groups = groupsResponse?.items ?? []
    return groups.filter(
      (g) => isDetectionGroup(g) && readyDatasets(g.datasets).length > 0,
    )
  }, [groupsResponse])

  // ── 2단계: 선택된 그룹의 READY 데이터셋에서 split 추출 ──
  const selectedGroup = useMemo(
    () => availableGroups.find((g) => g.id === nodeData?.groupId) ?? null,
    [availableGroups, nodeData?.groupId],
  )

  const availableSplits = useMemo(() => {
    if (!selectedGroup) return []
    const ready = readyDatasets(selectedGroup.datasets)
    const splits = [...new Set(ready.map((ds) => ds.split))]
    return splits.sort()
  }, [selectedGroup])

  // ── 3단계: 선택된 그룹+split의 버전 목록 ──
  const availableVersions = useMemo(() => {
    if (!selectedGroup || !nodeData?.split) return []
    const ready = readyDatasets(selectedGroup.datasets)
    return ready
      .filter((ds) => ds.split === nodeData.split)
      .sort((a, b) => b.version.localeCompare(a.version))
  }, [selectedGroup, nodeData?.split])

  // nodeData가 아직 store에 없으면 빈 상태로 표시
  if (!nodeData) return null

  // ── 검증 상태 ──
  const hasErrors = (nodeData.validationIssues ?? []).some((i) => i.severity === 'error')
  const hasWarnings = (nodeData.validationIssues ?? []).some((i) => i.severity === 'warning')
  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : '#52c41a'

  // ── 핸들러 ──
  const handleGroupChange = (groupId: string) => {
    const group = availableGroups.find((g) => g.id === groupId)
    setNodeData(id, {
      ...nodeData,
      groupId,
      groupName: group?.name ?? '',
      split: null,
      datasetId: null,
      version: null,
      datasetLabel: group?.name ?? '',
    })
  }

  const handleSplitChange = (split: string) => {
    setNodeData(id, {
      ...nodeData,
      split,
      datasetId: null,
      version: null,
      datasetLabel: `${nodeData.groupName} / ${split}`,
    })
  }

  const handleVersionChange = (datasetId: string) => {
    const dataset = availableVersions.find((ds) => ds.id === datasetId)
    setNodeData(id, {
      ...nodeData,
      datasetId,
      version: dataset?.version ?? null,
      datasetLabel: `${nodeData.groupName} / ${nodeData.split} / ${dataset?.version ?? ''}`,
    })
  }

  return (
    <div
      style={{
        background: '#fff',
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        minWidth: 260,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      {/* 헤더 */}
      <div
        style={{
          background: '#52c41a',
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
        <DatabaseOutlined />
        Data Load
      </div>

      {/* 본문 — 3단계 캐스케이드 선택
           nopan: React Flow 캔버스 팬 방지, nodrag: 노드 드래그 방지 */}
      <div className="nopan nodrag" style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {/* 1단계: 데이터셋 그룹 */}
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>데이터셋</Text>
          <Select
            size="small"
            placeholder="데이터셋 선택"
            value={nodeData.groupId || undefined}
            loading={groupsLoading}
            style={{ width: '100%' }}
            onChange={handleGroupChange}
            options={availableGroups.map((g) => ({
              value: g.id,
              label: `${g.name} (${g.dataset_type})`,
            }))}
          />
        </div>

        {/* 2단계: Split */}
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>Split</Text>
          <Select
            size="small"
            placeholder="Split 선택"
            value={nodeData.split || undefined}
            disabled={!nodeData.groupId}
            style={{ width: '100%' }}
            onChange={handleSplitChange}
            options={availableSplits.map((s) => ({
              value: s,
              label: s,
            }))}
          />
        </div>

        {/* 3단계: 버전 */}
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>버전</Text>
          <Select
            size="small"
            placeholder="버전 선택"
            value={nodeData.datasetId || undefined}
            disabled={!nodeData.split}
            style={{ width: '100%' }}
            onChange={handleVersionChange}
            options={availableVersions.map((ds) => ({
              value: ds.id,
              label: `${ds.version} (${ds.image_count ?? '?'} images)`,
            }))}
          />
        </div>

        {/* 선택 완료 시 요약 정보 */}
        {nodeData.datasetId && (
          <Text type="secondary" style={{ fontSize: 10 }}>
            ID: {nodeData.datasetId.slice(0, 8)}...
          </Text>
        )}

        {/* 검증 이슈 표시 */}
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

      {/* 출력 핸들 */}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 10,
          height: 10,
          background: '#52c41a',
          border: '2px solid #fff',
        }}
      />
    </div>
  )
}

export default memo(DataLoadNodeComponent)
