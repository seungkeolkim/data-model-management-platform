/**
 * ExecutionDetailDrawer — 파이프라인 실행 상세 Drawer
 *
 * PipelineExecutionResponse 객체를 받아 실행 상세 정보를 표시한다.
 * 파이프라인 이력 페이지, 데이터셋 상세 페이지 등 여러 곳에서 재사용된다.
 */

import { useState } from 'react'
import {
  Drawer, Descriptions, Tag, Progress, Divider,
  Space, Button, Typography, Modal, Tooltip, message,
} from 'antd'
import {
  LinkOutlined,
  CopyOutlined,
  CodeOutlined,
} from '@ant-design/icons'
import type { PipelineExecutionResponse } from '@/types/pipeline'
import { formatDate } from '@/utils/format'
import dayjs from 'dayjs'

const { Text } = Typography

/** 상태별 Tag 색상 */
const STATUS_TAG: Record<string, { color: string; label: string }> = {
  PENDING: { color: 'default', label: '대기' },
  RUNNING: { color: 'processing', label: '실행 중' },
  DONE: { color: 'success', label: '완료' },
  FAILED: { color: 'error', label: '실패' },
}

/** operator 이름을 읽기 좋은 한글 라벨로 변환 */
const OPERATOR_LABELS: Record<string, string> = {
  det_format_convert_to_coco: 'COCO 변환',
  det_format_convert_to_yolo: 'YOLO 변환',
  det_format_convert_visdrone_to_coco: 'VisDrone→COCO',
  det_format_convert_visdrone_to_yolo: 'VisDrone→YOLO',
  det_merge_datasets: '데이터셋 병합',
  cls_merge_datasets: 'Classification 데이터셋 병합',
  det_filter_remain_selected_class_names_only_in_annotation: 'Annotation 클래스 필터',
  det_filter_keep_images_containing_class_name: '이미지 유지 필터',
  det_filter_remove_images_containing_class_name: '이미지 제거 필터',
  det_remap_class_name: '클래스명 변경',
  det_rotate_image: '이미지 회전',
  det_mask_region_by_class: '클래스 영역 마스킹',
  det_sample_n_images: '이미지 샘플링',
  det_change_compression: '압축률 변경',
  det_shuffle_image_ids: '이미지 ID 셔플',
}

/** task_progress 상태별 색상 */
const TASK_STATUS_COLOR: Record<string, string> = {
  PENDING: '#8c8c8c',
  RUNNING: '#1677ff',
  DONE: '#52c41a',
  FAILED: '#ff4d4f',
}

/**
 * 소요 시간을 읽기 좋은 문자열로 변환.
 * started_at/finished_at은 UTC naive — 차이만 계산.
 */
function formatDuration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt || !finishedAt) return '-'
  const start = dayjs(startedAt)
  const end = dayjs(finishedAt)
  const diffSeconds = end.diff(start, 'second')
  if (diffSeconds < 60) return `${diffSeconds}초`
  const minutes = Math.floor(diffSeconds / 60)
  const seconds = diffSeconds % 60
  if (minutes < 60) return `${minutes}분 ${seconds}초`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}시간 ${remainMinutes}분`
}

/** config.tasks에서 소스 데이터셋 ID 목록 추출 */
function extractSourceDatasetIds(config: Record<string, unknown> | null): string[] {
  if (!config || !config.tasks) return []
  const tasks = config.tasks as Record<string, { inputs?: string[] }>
  const sourceIds = new Set<string>()
  for (const task of Object.values(tasks)) {
    for (const input of task.inputs ?? []) {
      if (input.startsWith('source:')) {
        sourceIds.add(input.replace('source:', ''))
      }
    }
  }
  return Array.from(sourceIds)
}

/**
 * 클립보드에 텍스트를 복사한다.
 * navigator.clipboard가 지원되지 않는 환경(HTTP + 비localhost)에서는
 * textarea fallback을 사용한다.
 */
function copyToClipboard(text: string): boolean {
  if (navigator.clipboard) {
    try {
      navigator.clipboard.writeText(text)
      return true
    } catch {
      // secure context가 아니면 여기로 떨어짐 — fallback 시도
    }
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
    return true
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
  }
}

export default function ExecutionDetailDrawer({
  execution,
  onClose,
  onNavigateToDataset,
}: {
  execution: PipelineExecutionResponse | null
  onClose: () => void
  onNavigateToDataset?: (groupId: string, datasetId: string) => void
}) {
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false)

  if (!execution) return null

  const config = execution.config as Record<string, unknown> | null
  const pipelineName = (config?.name as string) ?? '(이름 없음)'
  const pipelineDescription = (config?.description as string) ?? null
  const outputConfig = config?.output as { dataset_type?: string; annotation_format?: string; split?: string } | undefined

  const sourceDatasetIds = extractSourceDatasetIds(config)
  const taskProgressRaw = execution.task_progress as Record<string, {
    status: string; operator: string;
    started_at?: string; finished_at?: string;
    input_images?: number; output_images?: number;
    total_images?: number; materialized?: number; skipped?: number;
  }> | null

  // PostgreSQL JSONB는 키를 알파벳순 재정렬하므로, started_at 기준으로 실행 순서 복원
  const sortedTaskProgressEntries = taskProgressRaw
    ? Object.entries(taskProgressRaw).sort((a, b) => {
        const timeA = a[1].started_at ?? ''
        const timeB = b[1].started_at ?? ''
        return timeA.localeCompare(timeB)
      })
    : []

  const statusTag = STATUS_TAG[execution.status] ?? { color: 'default', label: execution.status }
  const progressPercent = execution.total_count > 0
    ? Math.round((execution.processed_count / execution.total_count) * 100)
    : 0

  return (
    <>
    <Drawer
      title={
        <Space>
          <span>{pipelineName}</span>
          <Tag color={statusTag.color}>{statusTag.label}</Tag>
        </Space>
      }
      open={!!execution}
      onClose={onClose}
      width={560}
    >
      {/* ── 파이프라인 구조 + Config 복사 ── */}
      {config && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>파이프라인 구조</Divider>
          <div style={{ marginBottom: 8 }}>
            <Tooltip title="PipelineConfig JSON을 확인하고 복사할 수 있습니다.">
              <Button
                icon={<CodeOutlined />}
                size="small"
                onClick={() => setIsConfigModalOpen(true)}
              >
                Config JSON 확인
              </Button>
            </Tooltip>
          </div>
        </>
      )}
      {execution.pipeline_image_url && (
        <div style={{
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          padding: 8,
          textAlign: 'center',
          marginBottom: 8,
        }}>
          <img
            src={execution.pipeline_image_url}
            alt="파이프라인 DAG"
            style={{ maxWidth: '100%', height: 'auto' }}
          />
        </div>
      )}

      {/* ── 기본 정보 ── */}
      <Divider orientation="left" style={{ fontSize: 13 }}>기본 정보</Divider>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="실행 ID">
          <Text code style={{ fontSize: 11 }}>{execution.id}</Text>
        </Descriptions.Item>
        {pipelineDescription && (
          <Descriptions.Item label="설명">{pipelineDescription}</Descriptions.Item>
        )}
        <Descriptions.Item label="소요 시간">
          {formatDuration(execution.started_at, execution.finished_at)}
        </Descriptions.Item>
        <Descriptions.Item label="시작">
          {execution.started_at ? formatDate(execution.started_at) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="완료">
          {execution.finished_at ? formatDate(execution.finished_at) : '-'}
        </Descriptions.Item>
      </Descriptions>

      {/* ── 진행률 (RUNNING 또는 완료 시) ── */}
      {execution.total_count > 0 && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>진행률</Divider>
          <Progress
            percent={progressPercent}
            status={
              execution.status === 'FAILED' ? 'exception'
                : execution.status === 'DONE' ? 'success'
                  : 'active'
            }
            format={() => `${execution.processed_count.toLocaleString()} / ${execution.total_count.toLocaleString()}`}
          />
        </>
      )}

      {/* ── 태스크별 진행 상태 (task_progress가 있으면 표시) ── */}
      {sortedTaskProgressEntries.length > 0 && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>태스크별 진행</Divider>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {sortedTaskProgressEntries.map(([taskName, progress], index) => {
              const isImageMaterialize = taskName === '__image_materialize__'
              const operatorLabel = isImageMaterialize
                ? '이미지 저장'
                : (OPERATOR_LABELS[progress.operator] ?? progress.operator)
              const statusColor = TASK_STATUS_COLOR[progress.status] ?? '#8c8c8c'

              return (
                <div
                  key={taskName}
                  style={{
                    padding: '6px 10px',
                    background: progress.status === 'RUNNING' ? '#e6f4ff' : '#fafafa',
                    borderRadius: 4,
                    border: `1px solid ${progress.status === 'RUNNING' ? '#91caff' : '#f0f0f0'}`,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Tag
                      color={statusColor}
                      style={{ margin: 0, minWidth: 24, textAlign: 'center' }}
                    >
                      {isImageMaterialize ? 'S' : index + 1}
                    </Tag>
                    <Text strong style={{ fontSize: 13, flex: 1 }}>
                      {operatorLabel}
                    </Text>
                    <Tag
                      color={statusColor}
                      style={{ margin: 0, fontSize: 11 }}
                    >
                      {progress.status === 'DONE' ? '완료'
                        : progress.status === 'RUNNING' ? '실행 중'
                          : progress.status === 'FAILED' ? '실패' : '대기'}
                    </Tag>
                  </div>

                  {/* 상세 정보 (완료된 태스크) */}
                  {progress.status === 'DONE' && (
                    <div style={{ marginTop: 4, paddingLeft: 36, fontSize: 12, color: '#8c8c8c' }}>
                      {isImageMaterialize ? (
                        <>
                          {progress.materialized != null && `저장: ${progress.materialized.toLocaleString()}장`}
                          {progress.skipped != null && progress.skipped > 0 && ` / 스킵: ${progress.skipped}장`}
                        </>
                      ) : (
                        <>
                          {progress.input_images != null && `입력: ${progress.input_images.toLocaleString()}장`}
                          {progress.output_images != null && ` → 출력: ${progress.output_images.toLocaleString()}장`}
                        </>
                      )}
                      {progress.started_at && progress.finished_at && (
                        <span style={{ marginLeft: 8 }}>
                          ({formatDuration(progress.started_at, progress.finished_at)})
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* ── 출력 설정 ── */}
      {outputConfig && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>출력 설정</Divider>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="데이터셋 타입">
              <Tag color={
                outputConfig.dataset_type === 'SOURCE' ? 'green'
                  : outputConfig.dataset_type === 'PROCESSED' ? 'orange'
                    : outputConfig.dataset_type === 'FUSION' ? 'purple' : 'default'
              }>
                {outputConfig.dataset_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="출력 포맷">
              <Tag>{outputConfig.annotation_format ?? '자동'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Split">
              {outputConfig.split ?? 'NONE'}
            </Descriptions.Item>
            <Descriptions.Item label="버전">
              {execution.output_dataset_version ?? '-'}
            </Descriptions.Item>
            {onNavigateToDataset && (
              <Descriptions.Item label="출력 데이터셋">
                {execution.output_dataset_group_id ? (
                  <Button
                    type="link"
                    size="small"
                    icon={<LinkOutlined />}
                    style={{ padding: 0 }}
                    onClick={() => onNavigateToDataset(execution.output_dataset_group_id!, execution.output_dataset_id)}
                  >
                    데이터셋 보기
                  </Button>
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {execution.output_dataset_id.slice(0, 8)}...
                  </Text>
                )}
              </Descriptions.Item>
            )}
          </Descriptions>
        </>
      )}

      {/* ── 소스 데이터셋 ── */}
      {sourceDatasetIds.length > 0 && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>소스 데이터셋</Divider>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sourceDatasetIds.map((sourceId) => (
              <Text key={sourceId} code style={{ fontSize: 11 }}>{sourceId}</Text>
            ))}
          </div>
        </>
      )}

      {/* ── 에러 메시지 (실패 시) ── */}
      {execution.error_message && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>에러 메시지</Divider>
          <div style={{
            background: '#fff2f0',
            border: '1px solid #ffccc7',
            borderRadius: 6,
            padding: 12,
          }}>
            <Text type="danger" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {execution.error_message}
            </Text>
          </div>
        </>
      )}

      {/* ── Celery 태스크 정보 ── */}
      {execution.celery_task_id && (
        <>
          <Divider orientation="left" style={{ fontSize: 13 }}>시스템 정보</Divider>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Celery Task ID">
              <Text code style={{ fontSize: 11 }}>{execution.celery_task_id}</Text>
            </Descriptions.Item>
          </Descriptions>
        </>
      )}
    </Drawer>

    {/* ── Config JSON 복사 모달 ── */}
    <Modal
      title="PipelineConfig JSON"
      open={isConfigModalOpen}
      onCancel={() => setIsConfigModalOpen(false)}
      width={600}
      footer={
        <Space>
          <Button onClick={() => setIsConfigModalOpen(false)}>닫기</Button>
          <Button
            type="primary"
            icon={<CopyOutlined />}
            onClick={() => {
              const configJson = JSON.stringify(config, null, 2)
              const success = copyToClipboard(configJson)
              if (success) {
                message.success('클립보드에 복사되었습니다.')
              } else {
                message.error('복사에 실패했습니다. 직접 선택하여 복사해 주세요.')
              }
            }}
          >
            클립보드에 복사
          </Button>
        </Space>
      }
    >
      <div style={{ marginBottom: 8, color: '#8c8c8c', fontSize: 13 }}>
        아래 JSON을 복사하여 파이프라인 에디터의 <b>JSON 불러오기</b>에 붙여넣으면
        동일한 파이프라인을 복원할 수 있습니다.
      </div>
      <pre
        style={{
          background: '#1e1e1e',
          color: '#d4d4d4',
          padding: 16,
          borderRadius: 6,
          fontSize: 12,
          fontFamily: 'monospace',
          maxHeight: 400,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.5,
          userSelect: 'all',
        }}
      >
        {config ? JSON.stringify(config, null, 2) : ''}
      </pre>
    </Modal>
    </>
  )
}
