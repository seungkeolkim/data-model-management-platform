import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Card,
  Space,
  Button,
  Radio,
  Select,
  Typography,
  Form,
  message,
  Tag,
  Descriptions,
  Alert,
} from 'antd'
import { updatePipelineAutomation } from '@/api/automation'
import type {
  Pipeline,
  AutomationMode,
  AutomationStatus,
  PollInterval,
} from '@/types/automation'
import {
  StatusBadge,
  AUTOMATION_ERROR_REASON_LABEL,
} from './StatusBadge'

const { Text } = Typography

const POLL_INTERVAL_OPTIONS: PollInterval[] = ['10m', '1h', '6h', '24h']

/**
 * Automation 설정 폼 (023 §6-4).
 *
 * 상태 토글 (stopped ↔ active) + mode 라디오 + poll interval 드롭다운.
 * error 상태는 시스템 자동 전환 전용이라 사용자가 직접 선택할 수 없다 — 버튼 2개 (stopped / active) 만.
 * error 에서 active 로 되돌릴 때 error_reason 은 목업 api 레이어가 정리해 준다.
 *
 * 변경 UX 는 "선택 → 적용 버튼 클릭" 의 2단계 (feedback_format_change_ux 메모리 — 속성 변경은 2단계
 * 확정 패턴 선호). 실수로 자동 저장되는 것을 방지.
 */
export default function AutomationSettingsForm({ pipeline }: { pipeline: Pipeline }) {
  const queryClient = useQueryClient()

  // 로컬 폼 상태 — 적용 전까지 서버 상태와 분리.
  const [draftMode, setDraftMode] = useState<AutomationMode | null>(pipeline.automation_mode)
  const [draftInterval, setDraftInterval] = useState<PollInterval | null>(
    pipeline.automation_poll_interval,
  )

  const mutation = useMutation({
    mutationFn: (update: {
      status?: AutomationStatus
      mode?: AutomationMode | null
      poll_interval?: PollInterval | null
    }) => updatePipelineAutomation(pipeline.id, update),
    onSuccess: () => {
      message.success('automation 설정이 반영됐습니다')
      // 목록 / 상세 / DAG 전부 invalidate — 목록 페이지 재진입 시 색상 일관성 유지.
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`업데이트 실패: ${error.message}`)
    },
  })

  const handleStatusToggle = (status: AutomationStatus) => {
    if (status === 'active') {
      // active 로 전환 시 현재 draft mode / interval 을 같이 반영.
      mutation.mutate({
        status: 'active',
        mode: draftMode ?? 'polling',
        poll_interval: draftMode === 'polling' ? draftInterval ?? '1h' : null,
      })
    } else {
      mutation.mutate({ status: 'stopped' })
    }
  }

  const handleApplySettings = () => {
    if (pipeline.automation_status === 'stopped') {
      message.info('stopped 상태에서는 모드/주기 설정이 적용되지 않습니다. active 로 전환하세요.')
      return
    }
    mutation.mutate({
      mode: draftMode,
      poll_interval: draftMode === 'polling' ? draftInterval : null,
    })
  }

  const hasSettingsDraft =
    draftMode !== pipeline.automation_mode ||
    draftInterval !== pipeline.automation_poll_interval

  return (
    <Card title="자동화 설정" size="small">
      {pipeline.automation_status === 'error' && pipeline.automation_error_reason && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={AUTOMATION_ERROR_REASON_LABEL[pipeline.automation_error_reason]}
          description={errorGuidance(pipeline)}
        />
      )}

      <Descriptions size="small" column={1} style={{ marginBottom: 16 }} bordered>
        <Descriptions.Item label="상태">
          <Space>
            <StatusBadge status={pipeline.automation_status} />
            {pipeline.automation_mode && <Tag>{pipeline.automation_mode}</Tag>}
            {pipeline.automation_poll_interval && (
              <Tag color="geekblue">{pipeline.automation_poll_interval}</Tag>
            )}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="마지막 실행">
          {pipeline.last_execution_at ? (
            <Text>{new Date(pipeline.last_execution_at).toLocaleString('ko-KR')}</Text>
          ) : (
            <Text type="secondary">이력 없음</Text>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="다음 예정">
          {pipeline.next_scheduled_at ? (
            <Text>{new Date(pipeline.next_scheduled_at).toLocaleString('ko-KR')}</Text>
          ) : (
            <Text type="secondary">—</Text>
          )}
        </Descriptions.Item>
      </Descriptions>

      <Form layout="vertical">
        <Form.Item label="Status 전환">
          <Space>
            <Button
              onClick={() => handleStatusToggle('stopped')}
              disabled={pipeline.automation_status === 'stopped' || mutation.isPending}
            >
              Stopped 으로 내리기
            </Button>
            <Button
              type="primary"
              onClick={() => handleStatusToggle('active')}
              disabled={pipeline.automation_status === 'active' || mutation.isPending}
            >
              Active 로 전환
            </Button>
          </Space>
          <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>
            Error 상태는 시스템이 자동 감지 시에만 설정됩니다 (예: 사이클 감지). 사용자는 stopped /
            active 간 전환만 가능합니다.
          </div>
        </Form.Item>

        <Form.Item label="Mode">
          <Radio.Group
            value={draftMode}
            onChange={(event) => setDraftMode(event.target.value)}
          >
            <Radio value="polling">Polling</Radio>
            <Radio value="triggering">Triggering</Radio>
          </Radio.Group>
        </Form.Item>

        <Form.Item label="Poll interval">
          <Select<PollInterval>
            value={draftInterval ?? undefined}
            onChange={setDraftInterval}
            disabled={draftMode !== 'polling'}
            style={{ width: 160 }}
            placeholder="주기 선택"
            options={POLL_INTERVAL_OPTIONS.map((interval) => ({
              value: interval,
              label: interval,
            }))}
          />
          {draftMode === 'triggering' && (
            <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>
              Triggering 모드에서는 주기 설정이 사용되지 않습니다.
            </div>
          )}
        </Form.Item>

        <Form.Item>
          <Button
            type="primary"
            disabled={!hasSettingsDraft || pipeline.automation_status === 'stopped'}
            loading={mutation.isPending}
            onClick={handleApplySettings}
          >
            설정 적용
          </Button>
          {pipeline.automation_status === 'stopped' && (
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 11 }}>
              (stopped 상태에서는 직접 적용되지 않음 — active 전환 시 draft 값이 반영됨)
            </Text>
          )}
        </Form.Item>
      </Form>
    </Card>
  )
}

/**
 * error 사유별 해결 가이드. 023 §6-4 "사용자 해결 가이드" 문구.
 */
function errorGuidance(pipeline: Pipeline): string {
  if (pipeline.automation_error_reason === 'CYCLE_DETECTED') {
    return `현재 파이프라인이 사이클의 일부입니다. 이 파이프라인 또는 반대편 파이프라인 중 하나를 stopped 로 전환하면 에러가 해제됩니다.`
  }
  if (pipeline.automation_error_reason === 'INPUT_GROUP_NOT_FOUND') {
    return `입력 DatasetGroup 을 찾을 수 없습니다. 파이프라인 설정을 점검하세요.`
  }
  return '자동화가 일시 중단됐습니다.'
}
