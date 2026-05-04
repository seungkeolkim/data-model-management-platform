import { Tag } from 'antd'
import type { AutomationStatus, AutomationErrorReason } from '@/types/automation'
import type { TaskType } from '@/types/dataset'

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
  // 027 §6-4 — automation 이 가리키던 PipelineVersion 이 비활성화되면 자동 전환되는 사유.
  PIPELINE_DELETED: '대상 Pipeline 비활성',
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

// =============================================================================
// TaskType 태그 — DatasetListPage 의 팔레트와 통일
// =============================================================================

/**
 * 축약 라벨. DAG 노드 카드·목록 컬럼처럼 폭이 좁은 자리에서 사용.
 */
const TASK_TYPE_SHORT_LABEL: Record<TaskType, string> = {
  DETECTION: 'DET',
  CLASSIFICATION: 'CLS',
  SEGMENTATION: 'SEG',
  ZERO_SHOT: 'ZS',
}

const TASK_TYPE_LONG_LABEL: Record<TaskType, string> = {
  DETECTION: 'Detection',
  CLASSIFICATION: 'Classification',
  SEGMENTATION: 'Segmentation',
  ZERO_SHOT: 'Zero-Shot',
}

const TASK_TYPE_COLOR: Record<TaskType, string> = {
  DETECTION: 'geekblue',
  CLASSIFICATION: 'magenta',
  SEGMENTATION: 'cyan',
  ZERO_SHOT: 'gold',
}

/**
 * 파이프라인 task 종류 태그. DETECTION / CLASSIFICATION / SEGMENTATION / ZERO_SHOT.
 * `variant="short"` 는 축약 라벨 (DET / CLS 등) — 좁은 자리에서 사용.
 * `variant="long"` 은 전체 이름 — 상세 페이지 헤더 등 여유 있는 자리에서 사용.
 */
export function TaskTypeTag({
  taskType,
  variant = 'short',
}: {
  taskType: TaskType
  variant?: 'short' | 'long'
}) {
  const label = variant === 'short' ? TASK_TYPE_SHORT_LABEL[taskType] : TASK_TYPE_LONG_LABEL[taskType]
  return (
    <Tag color={TASK_TYPE_COLOR[taskType]} style={{ fontSize: variant === 'short' ? 10 : 12 }}>
      {label}
    </Tag>
  )
}

// =============================================================================
// PipelineVersion 태그 — concept name 옆에 v1.0 형태로 노출
// =============================================================================

/**
 * "v1.0" / "v2.0" 같은 version 라벨 태그. 목록 행, DAG 노드, 상세 헤더에서 공용.
 * 같은 concept 안의 여러 version 을 시각적으로 구분하기 위해 옅은 보라색 단일 색상 사용.
 * Pipeline.name 자체와 시각적 분리되도록 background tag 형태.
 */
export function VersionTag({ version }: { version: string }) {
  return (
    <Tag color="purple" style={{ fontSize: 11, marginLeft: 0 }}>
      v{version}
    </Tag>
  )
}
