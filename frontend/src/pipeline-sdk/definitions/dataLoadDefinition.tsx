/**
 * DataLoadDefinition — 소스 데이터셋 2단계 선택 노드.
 *
 * v7.10 (핸드오프 027 §4-1, §12-1) — schema_version=2 전환.
 * 그룹 → Split 까지만 선택. 버전은 실행 시점 Version Resolver Modal 에서 확정.
 * 이 노드는 task 를 발생시키지 않고 `source:<split_id>` 토큰만 outputRef 로 제공.
 *
 * schema v1 (legacy) config 은 configToGraph 에서 placeholder 노드로 복원되어
 * 읽기 전용이며 재실행 차단. 본 정의는 v2 config 만 생성 / 복원.
 */
import { memo, useMemo } from 'react'
import type { NodeProps } from '@xyflow/react'
import { Select, Typography, Tag, Divider, Alert } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { datasetsForPipelineApi } from '@/api/pipeline'
import { useNodeData, useSetNodeData } from '../hooks/useNodeData'
import { NodeShell } from '../components/NodeShell'
import type { NodeDefinition } from '../types'
import type { DataLoadNodeData } from '@/types/pipeline'
import type { DatasetGroup, DatasetSummary } from '@/types/dataset'

const { Text } = Typography

const DL_COLOR = '#52c41a'
const DL_EMOJI = '📂'

/**
 * 파이프라인 에디터의 taskType 과 호환되는 그룹인지 판정한다.
 * task_types 가 비어있으면 과거 데이터(레거시) 호환을 위해 DETECTION 으로 간주한다.
 */
function isCompatibleGroup(group: DatasetGroup, taskType: string): boolean {
  if (!group.task_types || group.task_types.length === 0) {
    return taskType === 'DETECTION'
  }
  return group.task_types.includes(taskType as never)
}
function readyDatasets(datasets: DatasetSummary[]): DatasetSummary[] {
  return datasets.filter((ds) => ds.status === 'READY')
}

/** 그룹 datasets 에서 split 별 splitId 를 1:1 매핑 추출 (정적 슬롯 기준). */
function collectSplitSlots(datasets: DatasetSummary[]): Map<string, string> {
  const slotMap = new Map<string, string>()
  for (const ds of datasets) {
    if (!slotMap.has(ds.split)) {
      slotMap.set(ds.split, ds.split_id)
    }
  }
  return slotMap
}

const DataLoadNodeComponent = memo(function DataLoadNodeInner({ id }: NodeProps) {
  const nodeData = useNodeData<'dataLoad'>(id)
  const setNodeData = useSetNodeData()
  const [searchParams] = useSearchParams()
  const taskType = searchParams.get('taskType') ?? 'DETECTION'

  const { data: groupsResponse, isLoading: groupsLoading } = useQuery({
    queryKey: ['dataset-groups-for-pipeline'],
    queryFn: () => datasetsForPipelineApi.listGroups().then((r) => r.data),
    staleTime: 30_000,
  })

  const availableGroups = useMemo(() => {
    const groups = groupsResponse?.items ?? []
    // taskType 일치 + READY 데이터셋 1건 이상 보유 그룹만.
    return groups.filter(
      (g) => isCompatibleGroup(g, taskType) && readyDatasets(g.datasets).length > 0,
    )
  }, [groupsResponse, taskType])

  const selectedGroup = useMemo(
    () => availableGroups.find((g) => g.id === nodeData?.groupId) ?? null,
    [availableGroups, nodeData?.groupId],
  )
  // (split 문자열 → split_id) 매핑. group 안에서 split 당 하나만 존재.
  const splitSlots = useMemo(() => {
    if (!selectedGroup) return new Map<string, string>()
    const ready = readyDatasets(selectedGroup.datasets)
    return collectSplitSlots(ready)
  }, [selectedGroup])
  const availableSplits = useMemo(
    () => Array.from(splitSlots.keys()).sort(),
    [splitSlots],
  )

  if (!nodeData) return null

  const handleGroupChange = (groupId: string) => {
    const group = availableGroups.find((g) => g.id === groupId)
    setNodeData(id, {
      ...nodeData,
      groupId,
      groupName: group?.name ?? '',
      split: null,
      splitId: null,
      datasetLabel: group?.name ?? '',
    })
  }
  const handleSplitChange = (split: string) => {
    const splitId = splitSlots.get(split) ?? null
    setNodeData(id, {
      ...nodeData,
      split,
      splitId,
      datasetLabel: `${nodeData.groupName} / ${split}`,
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
        {nodeData.splitId && (
          <Text type="secondary" style={{ fontSize: 10 }}>
            split: {nodeData.splitId.slice(0, 8)}...
          </Text>
        )}
      </div>
    </NodeShell>
  )
})

// DataLoad 전용 PropertiesPanel — 그룹/split 정보 + 해당 split 의 클래스 매핑 표시.
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

  // 선택 split 의 최신 버전 (참고 표시용) — 구성 spec 에는 박지 않음.
  const latestDatasetInSplit = useMemo(() => {
    if (!groupData || !data.split) return null
    const ready = (groupData.datasets ?? []).filter(
      (ds) => ds.status === 'READY' && ds.split === data.split,
    )
    return ready.sort((a, b) => b.version.localeCompare(a.version))[0] ?? null
  }, [groupData, data.split])

  const classTableData = useMemo(() => {
    const classInfo = latestDatasetInSplit?.metadata?.class_info
    const classMapping = classInfo && 'class_mapping' in classInfo && !('heads' in classInfo)
      ? classInfo.class_mapping
      : undefined
    if (!classMapping) return []
    return Object.entries(classMapping)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([index, name]) => ({ index, name }))
  }, [latestDatasetInSplit])

  // Classification 그룹의 head_schema 는 group SSOT 에서 직접 읽는다 (v7.8 §2-8).
  // 노드 클릭 시 head 별 class 목록이 보여야 한다는 사용자 요구 (§9-9 피드백 #5).
  const classificationHeads = useMemo(() => {
    const heads = groupData?.head_schema?.heads
    if (!heads || heads.length === 0) return []
    return heads
  }, [groupData])

  return (
    <>
      <Tag color="green">Data Load</Tag>
      <Divider style={{ margin: '8px 0' }} />
      <Text type="secondary" style={{ fontSize: 12 }}>
        데이터셋 · Split 까지 선택합니다. 버전은 실행 시 별도 모달에서 확정 (v7.10).
      </Text>
      {data.groupName && (
        <div style={{ marginTop: 8 }}>
          <PropRow label="그룹" value={<Text strong style={{ fontSize: 12 }}>{data.groupName}</Text>} />
        </div>
      )}
      {data.split && <PropRow label="Split" value={data.split} />}
      {data.splitId && (
        <PropRow label="Split ID" value={<Text code style={{ fontSize: 10 }}>{data.splitId.slice(0, 12)}...</Text>} />
      )}
      {latestDatasetInSplit && groupData && (
        <>
          <Divider style={{ margin: '8px 0' }} />
          <Alert
            type="info" showIcon
            message={`참고: 최신 버전 ${latestDatasetInSplit.version}`}
            description="실행 시 다른 버전을 선택할 수 있습니다 (Version Resolver)."
            style={{ fontSize: 11, marginBottom: 8 }}
          />
          <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>데이터셋 정보 (최신 버전 기준)</Text>
          <PropRow label="데이터 타입" value={<Tag color="blue" style={{ margin: 0 }}>{groupData.dataset_type}</Tag>} />
          <PropRow label="어노테이션 포맷" value={<Tag style={{ margin: 0 }}>{latestDatasetInSplit.annotation_format ?? '없음'}</Tag>} />
          <PropRow label="최신 이미지 수" value={latestDatasetInSplit.image_count ?? '-'} />
          <PropRow label="클래스 수" value={latestDatasetInSplit.class_count ?? classTableData.length ?? '-'} />
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
          {classificationHeads.length > 0 && (
            <>
              <Divider style={{ margin: '8px 0' }} />
              <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                Head Schema (Classification)
              </Text>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 320, overflowY: 'auto' }}>
                {classificationHeads.map((head) => (
                  <div
                    key={head.name}
                    style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <Text strong style={{ fontSize: 12 }}>{head.name}</Text>
                      <Tag
                        color={head.multi_label ? 'magenta' : 'blue'}
                        style={{ margin: 0, fontSize: 10 }}
                      >
                        {head.multi_label ? 'multi' : 'single'}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        ({head.classes.length} classes)
                      </Text>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {head.classes.map((cls, idx) => (
                        <Tag
                          key={`${head.name}-${idx}`}
                          style={{ margin: 0, fontSize: 10 }}
                        >
                          {idx}: {cls}
                        </Tag>
                      ))}
                    </div>
                  </div>
                ))}
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
      splitId: null,
      datasetLabel: '',
    }),
  },
  NodeComponent: DataLoadNodeComponent,
  PropertiesComponent: DataLoadPropertiesComponent,

  validate(data, ctx) {
    if (!data.splitId) {
      return [{ nodeId: ctx.nodeId, message: '데이터셋과 Split 을 모두 선택해 주세요.' }]
    }
    return []
  },

  // v7.10: task 를 발생시키지 않고 `source:<splitId>` outputRef 제공.
  toConfigContribution(data) {
    if (!data.splitId) return null
    return { outputRef: `source:${data.splitId}` }
  },

  /**
   * schema_version=2 config 의 `source:<split_id>` 토큰을 점유하여 DataLoadNode 로 복원.
   * passthrough_source_split_id 도 포함. v1 (source:<dataset_version_id>) 토큰은
   * placeholderDefinition 이 수거해 읽기 전용 노드로 복원.
   */
  matchFromConfig(ctx) {
    const { config, datasetDisplayMap, claimedSourceDatasetIds } = ctx
    const isV2 = config.schema_version === 2

    // v1 legacy 는 DataLoad 가 수거하지 않는다 — placeholder 로 흘려보냄
    if (!isV2) return []

    const splitIds = new Set<string>()
    for (const task of Object.values(config.tasks)) {
      for (const input of task.inputs) {
        if (input.startsWith('source:')) {
          splitIds.add(input.split(':', 2)[1])
        }
      }
    }
    const v2PassthroughId = (config as { passthrough_source_split_id?: string | null })
      .passthrough_source_split_id
    if (v2PassthroughId) {
      splitIds.add(v2PassthroughId)
    }

    const restored = []
    for (const splitId of splitIds) {
      if (claimedSourceDatasetIds.has(splitId)) continue
      const nodeId = `dl_${splitId.slice(0, 8)}`
      const display = datasetDisplayMap[splitId]
      const data: DataLoadNodeData = {
        type: 'dataLoad',
        groupId: display?.groupId ?? null,
        groupName: display?.groupName ?? '',
        split: display?.split ?? null,
        splitId,
        datasetLabel: display
          ? `${display.groupName} / ${display.split}`
          : `source:${splitId.slice(0, 8)}...`,
      }
      restored.push({
        nodeId,
        data,
        ownedTaskKeys: [],
        ownedSourceDatasetIds: [splitId],
      })
    }
    return restored
  },

  matchIssueField(issue, data) {
    if (!issue.code?.startsWith('SOURCE_DATASET_')) return false
    if (!data.splitId) return false
    return issue.field.includes(data.splitId) || issue.message.includes(data.splitId)
  },
}
