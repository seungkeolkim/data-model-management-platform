/**
 * DataLoadDefinition — 소스 데이터셋 3단계 선택 노드.
 *
 * 그룹 → Split → 버전 순서로 선택하여 최종 dataset_id를 확정.
 * 이 노드는 task를 발생시키지 않고 `source:<dataset_id>` 토큰만 outputRef로 제공한다.
 * 하위 노드가 이 토큰을 inputs에 포함시킨다.
 */
import { memo, useMemo } from 'react'
import type { NodeProps } from '@xyflow/react'
import { Select, Typography, Tag, Divider } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { datasetsForPipelineApi } from '@/api/pipeline'
import { useNodeData, useSetNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import type { NodeDefinition } from '../types'
import type { DataLoadNodeData } from '@/types/pipeline'
import type { DatasetGroup, DatasetSummary } from '@/types/dataset'

const { Text } = Typography

const DL_COLOR = '#52c41a'
const DL_EMOJI = '📂'

function isDetectionGroup(group: DatasetGroup): boolean {
  if (!group.task_types || group.task_types.length === 0) return true
  return group.task_types.includes('DETECTION')
}
function readyDatasets(datasets: DatasetSummary[]): DatasetSummary[] {
  return datasets.filter((ds) => ds.status === 'READY')
}

const DataLoadNodeComponent = memo(function DataLoadNodeInner({ id }: NodeProps) {
  const nodeData = useNodeData<'dataLoad'>(id)
  const setNodeData = useSetNodeData()

  const { data: groupsResponse, isLoading: groupsLoading } = useQuery({
    queryKey: ['dataset-groups-for-pipeline'],
    queryFn: () => datasetsForPipelineApi.listGroups().then((r) => r.data),
    staleTime: 30_000,
  })

  const availableGroups = useMemo(() => {
    const groups = groupsResponse?.items ?? []
    return groups.filter(
      (g) => isDetectionGroup(g) && readyDatasets(g.datasets).length > 0,
    )
  }, [groupsResponse])

  const selectedGroup = useMemo(
    () => availableGroups.find((g) => g.id === nodeData?.groupId) ?? null,
    [availableGroups, nodeData?.groupId],
  )
  const availableSplits = useMemo(() => {
    if (!selectedGroup) return []
    const ready = readyDatasets(selectedGroup.datasets)
    return [...new Set(ready.map((ds) => ds.split))].sort()
  }, [selectedGroup])
  const availableVersions = useMemo(() => {
    if (!selectedGroup || !nodeData?.split) return []
    const ready = readyDatasets(selectedGroup.datasets)
    return ready
      .filter((ds) => ds.split === nodeData.split)
      .sort((a, b) => b.version.localeCompare(a.version))
  }, [selectedGroup, nodeData?.split])

  if (!nodeData) return null

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
    <NodeShell
      color={DL_COLOR}
      emoji={DL_EMOJI}
      headerLabel="Data Load"
      inputs="none"
      outputs="single"
      issues={nodeData.validationIssues ?? []}
      minWidth={260}
    >
      <div className="nopan nodrag" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
        <div>
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>Split</Text>
          <Select
            size="small"
            placeholder="Split 선택"
            value={nodeData.split || undefined}
            disabled={!nodeData.groupId}
            style={{ width: '100%' }}
            onChange={handleSplitChange}
            options={availableSplits.map((s) => ({ value: s, label: s }))}
          />
        </div>
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
        {nodeData.datasetId && (
          <Text type="secondary" style={{ fontSize: 10 }}>
            ID: {nodeData.datasetId.slice(0, 8)}...
          </Text>
        )}
      </div>
    </NodeShell>
  )
})

// DataLoad 전용 PropertiesPanel — 그룹/버전 정보 + 클래스 매핑 테이블 표시.
// 기존 PropertiesPanel의 DataLoadProperties를 그대로 이관.
import { Table } from 'antd'

function PropRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
      <div style={{ fontSize: 12, textAlign: 'right' }}>{value}</div>
    </div>
  )
}

function DataLoadPropertiesComponent({ data }: { nodeId: string; data: DataLoadNodeData }) {
  const { data: groupData } = useQuery({
    queryKey: ['dataset-group-detail', data.groupId],
    queryFn: () => datasetsForPipelineApi.getGroup(data.groupId!).then((r) => r.data),
    enabled: !!data.groupId,
    staleTime: 30_000,
  })

  const selectedDataset = useMemo(() => {
    if (!groupData || !data.datasetId) return null
    return groupData.datasets.find((ds) => ds.id === data.datasetId) ?? null
  }, [groupData, data.datasetId])

  const classTableData = useMemo(() => {
    // Data Load 노드는 detection 전제(파이프라인이 detection만 지원) → detection class_mapping만 표시
    const classInfo = selectedDataset?.metadata?.class_info
    const classMapping = classInfo && 'class_mapping' in classInfo && !('heads' in classInfo)
      ? classInfo.class_mapping
      : undefined
    if (!classMapping) return []
    return Object.entries(classMapping)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([index, name]) => ({ index, name }))
  }, [selectedDataset])

  return (
    <>
      <Tag color="green">Data Load</Tag>
      <Divider style={{ margin: '8px 0' }} />
      <Text type="secondary" style={{ fontSize: 12 }}>
        데이터셋 · Split · 버전을 노드에서 순서대로 선택합니다.
      </Text>
      {data.groupName && (
        <div style={{ marginTop: 8 }}>
          <PropRow label="그룹" value={<Text strong style={{ fontSize: 12 }}>{data.groupName}</Text>} />
        </div>
      )}
      {data.split && <PropRow label="Split" value={data.split} />}
      {data.version && <PropRow label="버전" value={data.version} />}
      {data.datasetId && (
        <PropRow label="ID" value={<Text code style={{ fontSize: 10 }}>{data.datasetId.slice(0, 12)}...</Text>} />
      )}
      {selectedDataset && groupData && (
        <>
          <Divider style={{ margin: '8px 0' }} />
          <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>데이터셋 정보</Text>
          <PropRow label="데이터 타입" value={<Tag color="blue" style={{ margin: 0 }}>{groupData.dataset_type}</Tag>} />
          <PropRow label="어노테이션 포맷" value={<Tag style={{ margin: 0 }}>{selectedDataset.annotation_format ?? '없음'}</Tag>} />
          <PropRow label="이미지 수" value={selectedDataset.image_count ?? '-'} />
          <PropRow label="클래스 수" value={selectedDataset.class_count ?? classTableData.length ?? '-'} />
          {classTableData.length > 0 && (
            <>
              <Divider style={{ margin: '8px 0' }} />
              <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>클래스 목록</Text>
              <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                <Table
                  dataSource={classTableData}
                  columns={[
                    { title: 'ID', dataIndex: 'index', width: 45, render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
                    { title: '클래스명', dataIndex: 'name', render: (v: string) => <Text style={{ fontSize: 11 }}>{v}</Text> },
                  ]}
                  rowKey="index"
                  size="small"
                  pagination={false}
                  showHeader
                  style={{ fontSize: 11 }}
                />
              </div>
            </>
          )}
        </>
      )}
    </>
  )
}

export const dataLoadDefinition: NodeDefinition<'dataLoad'> = {
  kind: 'dataLoad',
  palette: {
    section: 'basic',
    label: 'Data Load',
    color: DL_COLOR,
    emoji: DL_EMOJI,
    order: 10,
    createDefaultData: () => ({
      type: 'dataLoad',
      groupId: null,
      groupName: '',
      split: null,
      datasetId: null,
      version: null,
      datasetLabel: '',
    }),
  },
  NodeComponent: DataLoadNodeComponent,
  PropertiesComponent: DataLoadPropertiesComponent,

  validate(data, ctx) {
    if (!data.datasetId) {
      return [{ nodeId: ctx.nodeId, message: '데이터셋을 선택해 주세요.' }]
    }
    return []
  },

  // DataLoad는 task를 발생시키지 않고 outputRef만 제공.
  toConfigContribution(data) {
    if (!data.datasetId) return null
    return { outputRef: `source:${data.datasetId}` }
  },

  // source:<id> 토큰을 점유하여 DataLoadNode로 복원.
  matchFromConfig(ctx) {
    const { config, datasetDisplayMap, claimedSourceDatasetIds } = ctx
    const sourceIds = new Set<string>()
    for (const task of Object.values(config.tasks)) {
      for (const input of task.inputs) {
        if (input.startsWith('source:')) {
          sourceIds.add(input.split(':', 2)[1])
        }
      }
    }
    const restored = []
    for (const datasetId of sourceIds) {
      if (claimedSourceDatasetIds.has(datasetId)) continue
      const nodeId = `dl_${datasetId.slice(0, 8)}`
      const display = datasetDisplayMap[datasetId]
      const data: DataLoadNodeData = {
        type: 'dataLoad',
        groupId: display?.groupId ?? null,
        groupName: display?.groupName ?? '',
        split: display?.split ?? null,
        datasetId,
        version: display?.version ?? null,
        datasetLabel: display
          ? `${display.groupName} / ${display.split} / ${display.version}`
          : `source:${datasetId.slice(0, 8)}...`,
      }
      restored.push({
        nodeId,
        data,
        ownedTaskKeys: [],
        ownedSourceDatasetIds: [datasetId],
      })
    }
    return restored
  },

  matchIssueField(issue, data) {
    if (!issue.code?.startsWith('SOURCE_DATASET_')) return false
    if (!data.datasetId) return false
    return issue.field.includes(data.datasetId) || issue.message.includes(data.datasetId)
  },
}
