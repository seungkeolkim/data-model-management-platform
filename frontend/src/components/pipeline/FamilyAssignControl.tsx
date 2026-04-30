/**
 * Pipeline (concept) 의 family_id 변경 — Select dropdown.
 * 옵션: 미분류 (NULL), 기존 family 들. ExpandedConceptContent 안에서 사용.
 */
import { useMemo } from 'react'
import { Select, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { pipelineConceptsApi, pipelineFamiliesApi } from '@/api/pipeline'

interface FamilyAssignControlProps {
  pipelineId: string
  currentFamilyId: string | null
  size?: 'small' | 'middle' | 'large'
  style?: React.CSSProperties
}

const UNFILED_VALUE = '__unfiled__'

export function FamilyAssignControl({
  pipelineId,
  currentFamilyId,
  size = 'small',
  style,
}: FamilyAssignControlProps) {
  const queryClient = useQueryClient()

  const familiesQuery = useQuery({
    queryKey: ['pipeline-families'],
    queryFn: () => pipelineFamiliesApi.list().then((r) => r.data),
    staleTime: 30_000,
  })

  const options = useMemo(() => {
    const fams = familiesQuery.data ?? []
    return [
      { value: UNFILED_VALUE, label: '미분류' },
      ...fams.map((f) => ({ value: f.id, label: f.name })),
    ]
  }, [familiesQuery.data])

  const updateMutation = useMutation({
    mutationFn: (newValue: string) => {
      if (newValue === UNFILED_VALUE) {
        return pipelineConceptsApi
          .update(pipelineId, { unset_family: true })
          .then((r) => r.data)
      }
      return pipelineConceptsApi
        .update(pipelineId, { family_id: newValue })
        .then((r) => r.data)
    },
    onSuccess: () => {
      message.success('Family 변경 완료')
      queryClient.invalidateQueries({ queryKey: ['pipeline-concepts'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-concept-detail'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-families'] })
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err as Error)?.message
        ?? '알 수 없는 오류'
      message.error(`Family 변경 실패: ${msg}`)
    },
  })

  return (
    <Select
      size={size}
      value={currentFamilyId ?? UNFILED_VALUE}
      style={{ minWidth: 140, ...style }}
      loading={familiesQuery.isLoading || updateMutation.isPending}
      options={options}
      onChange={(v) => updateMutation.mutate(v)}
    />
  )
}
