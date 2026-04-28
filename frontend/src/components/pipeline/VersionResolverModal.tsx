/**
 * VersionResolverModal — Pipeline 실행 제출 전 input version 확인 모달.
 *
 * v7.10 핸드오프 027 §4-3, §12-1.
 * Pipeline 목록 각 행 우측 "실행" 버튼 클릭 시 노출. `config.tasks[*].inputs` 의
 * `source:<split_id>` 들과 `passthrough_source_split_id` 에서 필요한 split 목록을
 * 추출해, 각 split 별 최신 READY DatasetVersion 을 기본값으로 한 드롭다운을 표시.
 *
 * 확정 시 `POST /pipelines/entities/{id}/runs` 로 `{split_id: version}` 을 제출.
 */
import { useEffect, useMemo, useState } from 'react'
import { Modal, Select, Typography, Space, Alert, Spin, Tag, Divider } from 'antd'
import { useQueries, useMutation, useQueryClient } from '@tanstack/react-query'
import { datasetsForPipelineApi, pipelineEntitiesApi } from '@/api/pipeline'
import type { PipelineEntityResponse } from '@/types/pipeline'
import type { DatasetGroup, DatasetSummary } from '@/types/dataset'

const { Text } = Typography

interface VersionResolverModalProps {
  open: boolean
  pipeline: PipelineEntityResponse | null
  onClose: () => void
  onSubmitted?: (runId: string) => void
}

/**
 * config 에서 필요한 모든 source split_id 를 추출.
 * `config.tasks[*].inputs` 의 `source:<split_id>` + `config.passthrough_source_split_id`.
 */
function collectSourceSplitIdsFromConfig(config: Record<string, unknown>): string[] {
  const ids = new Set<string>()
  const tasks = config.tasks as Record<string, { inputs?: string[] }> | undefined
  for (const task of Object.values(tasks ?? {})) {
    for (const input of task.inputs ?? []) {
      if (input.startsWith('source:')) {
        ids.add(input.slice('source:'.length))
      }
    }
  }
  const passthrough = config.passthrough_source_split_id as string | null | undefined
  if (passthrough) {
    ids.add(passthrough)
  }
  return [...ids]
}

/**
 * datasetGroups 전체에서 특정 split_id 가 속한 group + split 문자열 + 가용 versions
 * (READY, 최신순) 을 조회. 개별 split_id → group 매핑 API 가 없으므로 group 목록을
 * 한 번 받아 in-memory 인덱싱.
 */
function lookupSplitInfo(
  groups: DatasetGroup[],
  splitId: string,
): {
  groupName: string | null
  split: string | null
  versions: DatasetSummary[]
} {
  for (const group of groups) {
    const matches = (group.datasets ?? []).filter(
      (ds) => ds.split_id === splitId && ds.status === 'READY',
    )
    if (matches.length > 0) {
      const sorted = [...matches].sort((a, b) =>
        b.version.localeCompare(a.version, 'en', { numeric: true }),
      )
      return {
        groupName: group.name,
        split: matches[0].split,
        versions: sorted,
      }
    }
  }
  return { groupName: null, split: null, versions: [] }
}

export function VersionResolverModal({
  open,
  pipeline,
  onClose,
  onSubmitted,
}: VersionResolverModalProps) {
  const queryClient = useQueryClient()
  const [resolvedVersions, setResolvedVersions] = useState<Record<string, string>>({})
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // 필요한 split_id 목록을 config 에서 추출
  const requiredSplitIds = useMemo(() => {
    if (!pipeline) return []
    return collectSourceSplitIdsFromConfig(pipeline.config)
  }, [pipeline])

  // DatasetGroup 전체 로드 (split_id 역조회용). §9-7 페이지 재배선 시 전용 lookup
  // 엔드포인트로 교체 검토.
  const [groupsQuery] = useQueries({
    queries: [
      {
        queryKey: ['dataset-groups-all-for-resolver'],
        queryFn: () => datasetsForPipelineApi.listGroups().then((r) => r.data),
        enabled: open && !!pipeline,
        staleTime: 10_000,
      },
    ],
  })

  const splitInfoMap = useMemo(() => {
    const map = new Map<string, ReturnType<typeof lookupSplitInfo>>()
    if (!groupsQuery.data) return map
    for (const splitId of requiredSplitIds) {
      map.set(splitId, lookupSplitInfo(groupsQuery.data.items ?? [], splitId))
    }
    return map
  }, [groupsQuery.data, requiredSplitIds])

  // 최초 로드 시 각 split 의 최신 버전을 기본값으로 설정
  useEffect(() => {
    if (!open || !groupsQuery.data) return
    const defaults: Record<string, string> = {}
    for (const splitId of requiredSplitIds) {
      const info = splitInfoMap.get(splitId)
      if (info && info.versions.length > 0) {
        defaults[splitId] = info.versions[0].version
      }
    }
    setResolvedVersions(defaults)
    setErrorMessage(null)
  }, [open, groupsQuery.data, requiredSplitIds, splitInfoMap])

  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!pipeline) throw new Error('pipeline 없음')
      const response = await pipelineEntitiesApi.submitRun(pipeline.id, {
        resolved_input_versions: resolvedVersions,
      })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['pipeline-entities'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] })
      onSubmitted?.(data.execution_id)
      onClose()
    },
    onError: (err: unknown) => {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err as Error)?.message
        ?? '알 수 없는 오류'
      setErrorMessage(message)
    },
  })

  if (!pipeline) return null

  const isLoading = groupsQuery.isLoading
  const allVersionsSelected =
    requiredSplitIds.length > 0
    && requiredSplitIds.every((sid) => !!resolvedVersions[sid])

  return (
    <Modal
      open={open}
      title={
        <Space>
          <span>파이프라인 실행</span>
          <Tag color="blue" style={{ margin: 0 }}>
            {pipeline.name} v{pipeline.version}
          </Tag>
        </Space>
      }
      onCancel={onClose}
      onOk={() => submitMutation.mutate()}
      okText="이 버전으로 실행"
      okButtonProps={{ disabled: !allVersionsSelected || submitMutation.isPending }}
      cancelText="취소"
      confirmLoading={submitMutation.isPending}
      width={600}
      destroyOnClose
    >
      {errorMessage && (
        <Alert
          type="error" showIcon closable
          message="실행 제출 실패"
          description={errorMessage}
          style={{ marginBottom: 12 }}
          onClose={() => setErrorMessage(null)}
        />
      )}
      <Text type="secondary" style={{ fontSize: 12 }}>
        각 입력 split 에서 사용할 DatasetVersion 을 선택하세요. 기본값은 해당 split 의
        최신 READY 버전입니다.
      </Text>
      <Divider style={{ margin: '12px 0' }} />
      {isLoading ? (
        <Spin />
      ) : requiredSplitIds.length === 0 ? (
        <Alert
          type="info" showIcon
          message="이 Pipeline 은 외부 입력 split 이 없습니다 (passthrough / 상수 입력)."
        />
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {requiredSplitIds.map((splitId) => {
            const info = splitInfoMap.get(splitId)
            if (!info || info.versions.length === 0) {
              return (
                <Alert
                  key={splitId}
                  type="error" showIcon
                  message={`split ${splitId.slice(0, 8)}... 에서 READY 버전을 찾지 못함`}
                  description="상류 데이터셋이 삭제되었거나 READY 상태가 아닙니다. Pipeline 을 다시 구성하세요."
                />
              )
            }
            const selected = resolvedVersions[splitId] ?? info.versions[0]?.version
            return (
              <div key={splitId}>
                <Text strong style={{ fontSize: 13, display: 'block' }}>
                  {info.groupName} / {info.split}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  split_id: <code>{splitId.slice(0, 12)}...</code>
                </Text>
                <Select
                  size="middle"
                  style={{ width: '100%', marginTop: 4 }}
                  value={selected}
                  onChange={(version) =>
                    setResolvedVersions((prev) => ({ ...prev, [splitId]: version }))
                  }
                  options={info.versions.map((dv, idx) => ({
                    value: dv.version,
                    label:
                      idx === 0
                        ? `${dv.version} (최신, ${dv.image_count ?? '?'} images)`
                        : `${dv.version} (${dv.image_count ?? '?'} images)`,
                  }))}
                />
              </div>
            )
          })}
        </Space>
      )}
    </Modal>
  )
}
