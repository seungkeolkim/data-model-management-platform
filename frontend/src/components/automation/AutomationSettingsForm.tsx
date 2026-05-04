import { useEffect, useState } from 'react'
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
  Popconfirm,
} from 'antd'
import {
  createAutomationForVersion,
  deleteAutomation,
  updateAutomation,
} from '@/api/automation'
import type {
  AutomationMode,
  AutomationStatus,
  PipelineAutomation,
  PipelineVersion,
  PollInterval,
} from '@/types/automation'
import { AUTOMATION_ERROR_REASON_LABEL, StatusBadge } from './StatusBadge'

const { Text } = Typography

const POLL_INTERVAL_OPTIONS: PollInterval[] = ['10m', '1h', '6h', '24h']

/**
 * Automation 설정 폼 — v7.13 baseline (PipelineVersion 단위 1:0..1) 어댑트.
 *
 * 두 모드:
 *   - 등록된 경우 (version.automation !== null): 상태 토글 + mode 라디오 + poll interval + 해제 버튼
 *   - 미등록 (version.automation === null): "Automation 등록" 폼 (mode + interval 선택 → 생성)
 *
 * UX 결정 — feedback_format_change_ux: 속성 변경은 "선택 → 적용" 2단계.
 * Error 상태는 시스템 자동 전환 전용 (사이클 감지 등) — 사용자는 stopped / active 간 토글만.
 *
 * 027 §12-3 — soft delete 패턴. 해제 시 row 는 보존되며 is_active=false 처리. 같은 version 에 새
 * automation 을 등록하면 partial unique index 가 새 row 만 active 로 받는다.
 */
export default function AutomationSettingsForm({
  version,
}: {
  version: PipelineVersion
}) {
  const automation = version.automation
  if (automation) {
    return <ExistingAutomationForm version={version} automation={automation} />
  }
  return <CreateAutomationForm version={version} />
}

// =============================================================================
// 등록된 automation 의 설정 편집 폼
// =============================================================================

function ExistingAutomationForm({
  version,
  automation,
}: {
  version: PipelineVersion
  automation: PipelineAutomation
}) {
  const queryClient = useQueryClient()

  const [draftMode, setDraftMode] = useState<AutomationMode | null>(automation.mode)
  const [draftInterval, setDraftInterval] = useState<PollInterval | null>(
    automation.poll_interval,
  )

  // automation 변경 시 draft 동기화 (외부 invalidate 후 신규 데이터 들어왔을 때).
  useEffect(() => {
    setDraftMode(automation.mode)
    setDraftInterval(automation.poll_interval)
  }, [automation.id, automation.mode, automation.poll_interval])

  const updateMutation = useMutation({
    mutationFn: (update: {
      status?: AutomationStatus
      mode?: AutomationMode | null
      poll_interval?: PollInterval | null
    }) => updateAutomation(automation.id, update),
    onSuccess: () => {
      message.success('automation 설정이 반영됐습니다')
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`업데이트 실패: ${error.message}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteAutomation(automation.id),
    onSuccess: () => {
      message.success('automation 등록이 해제됐습니다')
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`해제 실패: ${error.message}`)
    },
  })

  const handleStatusToggle = (status: AutomationStatus) => {
    if (status === 'active') {
      updateMutation.mutate({
        status: 'active',
        mode: draftMode ?? 'polling',
        poll_interval: draftMode === 'polling' ? draftInterval ?? '1h' : null,
      })
    } else {
      updateMutation.mutate({ status: 'stopped' })
    }
  }

  const handleApplySettings = () => {
    if (automation.status === 'stopped') {
      message.info('stopped 상태에서는 모드/주기 설정이 적용되지 않습니다. active 로 전환하세요.')
      return
    }
    updateMutation.mutate({
      mode: draftMode,
      poll_interval: draftMode === 'polling' ? draftInterval : null,
    })
  }

  const hasSettingsDraft =
    draftMode !== automation.mode || draftInterval !== automation.poll_interval

  return (
    <Card title="자동화 설정" size="small">
      {automation.status === 'error' && automation.error_reason && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={AUTOMATION_ERROR_REASON_LABEL[automation.error_reason]}
          description={errorGuidance(automation)}
        />
      )}

      <Descriptions size="small" column={1} style={{ marginBottom: 16 }} bordered>
        <Descriptions.Item label="상태">
          <Space>
            <StatusBadge status={automation.status} />
            {automation.mode && <Tag>{automation.mode}</Tag>}
            {automation.poll_interval && <Tag color="geekblue">{automation.poll_interval}</Tag>}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="마지막 dispatch">
          {automation.last_dispatched_at ? (
            <Text>{new Date(automation.last_dispatched_at).toLocaleString('ko-KR')}</Text>
          ) : (
            <Text type="secondary">이력 없음</Text>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="다음 예정">
          {automation.next_scheduled_at ? (
            <Text>{new Date(automation.next_scheduled_at).toLocaleString('ko-KR')}</Text>
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
              disabled={automation.status === 'stopped' || updateMutation.isPending}
            >
              Stopped 으로 내리기
            </Button>
            <Button
              type="primary"
              onClick={() => handleStatusToggle('active')}
              disabled={automation.status === 'active' || updateMutation.isPending}
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
          <Space>
            <Button
              type="primary"
              disabled={!hasSettingsDraft || automation.status === 'stopped'}
              loading={updateMutation.isPending}
              onClick={handleApplySettings}
            >
              설정 적용
            </Button>
            <Popconfirm
              title="automation 등록을 해제할까요?"
              description="현재 row 는 보존되며 (soft delete) 같은 version 에 새 automation 을 등록할 수 있게 됩니다."
              okText="해제"
              cancelText="취소"
              onConfirm={() => deleteMutation.mutate()}
            >
              <Button danger loading={deleteMutation.isPending}>
                Automation 등록 해제
              </Button>
            </Popconfirm>
          </Space>
          {automation.status === 'stopped' && (
            <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>
              stopped 상태에서는 직접 적용되지 않음 — active 전환 시 draft 값이 반영됨.
            </div>
          )}
          <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>
            대상 PipelineVersion: <Tag>{version.pipeline_name}</Tag>
            <Tag color="purple">v{version.version}</Tag>
          </div>
        </Form.Item>
      </Form>
    </Card>
  )
}

// =============================================================================
// 미등록 version 에 대한 신규 등록 폼
// =============================================================================

function CreateAutomationForm({ version }: { version: PipelineVersion }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<AutomationMode>('polling')
  const [interval, setIntervalValue] = useState<PollInterval>('1h')

  const createMutation = useMutation({
    mutationFn: () =>
      createAutomationForVersion(version.id, {
        mode,
        poll_interval: mode === 'polling' ? interval : null,
        status: 'active',
      }),
    onSuccess: () => {
      message.success('automation 이 등록되어 active 상태로 전환됐습니다')
      queryClient.invalidateQueries({ queryKey: ['automation'] })
    },
    onError: (error: Error) => {
      message.error(`등록 실패: ${error.message}`)
    },
  })

  return (
    <Card title="자동화 설정" size="small">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="이 PipelineVersion 에는 등록된 automation 이 없습니다."
        description="아래 폼으로 새 automation 을 등록하면 즉시 active 상태로 시작됩니다. 등록 후에도 status / mode / 주기는 언제든 변경할 수 있습니다."
      />
      <Form layout="vertical">
        <Form.Item label="Mode">
          <Radio.Group value={mode} onChange={(event) => setMode(event.target.value)}>
            <Radio value="polling">Polling</Radio>
            <Radio value="triggering">Triggering</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item label="Poll interval">
          <Select<PollInterval>
            value={interval}
            onChange={setIntervalValue}
            disabled={mode !== 'polling'}
            style={{ width: 160 }}
            options={POLL_INTERVAL_OPTIONS.map((value) => ({ value, label: value }))}
          />
          {mode === 'triggering' && (
            <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>
              Triggering 모드에서는 주기 설정이 사용되지 않습니다.
            </div>
          )}
        </Form.Item>
        <Form.Item>
          <Button
            type="primary"
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Automation 등록하고 시작
          </Button>
          <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>
            대상 PipelineVersion: <Tag>{version.pipeline_name}</Tag>
            <Tag color="purple">v{version.version}</Tag>
          </div>
        </Form.Item>
      </Form>
    </Card>
  )
}

/**
 * error 사유별 해결 가이드.
 */
function errorGuidance(automation: PipelineAutomation): string {
  if (automation.error_reason === 'CYCLE_DETECTED') {
    return `현재 파이프라인이 사이클의 일부입니다. 이 파이프라인 또는 반대편 파이프라인 중 하나를 stopped 로 전환하면 에러가 해제됩니다.`
  }
  if (automation.error_reason === 'INPUT_GROUP_NOT_FOUND') {
    return `입력 DatasetSplit 을 찾을 수 없습니다. 파이프라인 설정을 점검하세요.`
  }
  if (automation.error_reason === 'PIPELINE_DELETED') {
    return `automation 이 가리키던 PipelineVersion 이 비활성화됐습니다. 다른 version 으로 reassign 하거나 등록을 해제하세요.`
  }
  return '자동화가 일시 중단됐습니다.'
}
