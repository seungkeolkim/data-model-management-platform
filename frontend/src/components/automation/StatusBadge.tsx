import { Tag } from 'antd'
import type { AutomationStatus, AutomationErrorReason } from '@/types/automation'

/**
 * 파이프라인 automation 상태 배지. 023 §E-21 팔레트:
 *   stopped = 회색, active = 초록, error = 빨강.
 *
 * 목록 / DAG / 상세 탭에서 공용으로 쓴다. 상태 문자열은 UI 표기 (영문 그대로 노출 — 규약).
 */
export const AUTOMATION_STATUS_LABEL: Record<AutomationStatus, string> = {
  stopped: 'Stopped',
  active: 'Active',
  error: 'Error',
}

export const AUTOMATION_ERROR_REASON_LABEL: Record<AutomationErrorReason, string> = {
  CYCLE_DETECTED: '사이클 감지됨',
  INPUT_GROUP_NOT_FOUND: '입력 그룹 없음',
}

export function StatusBadge({ status }: { status: AutomationStatus }) {
  const colorByStatus: Record<AutomationStatus, string> = {
    stopped: 'default',
    active: 'success',
    error: 'error',
  }
  return <Tag color={colorByStatus[status]}>{AUTOMATION_STATUS_LABEL[status]}</Tag>
}

/**
 * Chaining DAG 노드 테두리 / 배경 색 팔레트. StatusBadge 의 antd 색상과 시각적으로 일치시켜
 * 목록 배지와 DAG 노드가 같은 색상 언어를 공유하게 한다.
 */
export const AUTOMATION_STATUS_COLOR: Record<
  AutomationStatus,
  { border: string; background: string; text: string }
> = {
  stopped: { border: '#d9d9d9', background: '#fafafa', text: '#8c8c8c' },
  active: { border: '#52c41a', background: '#f6ffed', text: '#389e0d' },
  error: { border: '#ff4d4f', background: '#fff1f0', text: '#cf1322' },
}
