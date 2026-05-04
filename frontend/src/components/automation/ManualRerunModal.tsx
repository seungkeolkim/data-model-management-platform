import { useState } from 'react'
import { Modal, Space, Button, Typography, Alert, Result, Tag } from 'antd'
import {
  rerunAutomationManually,
  type ManualRerunMode,
  type ManualRerunResult,
} from '@/api/automation'

const { Text, Paragraph } = Typography

interface ManualRerunModalProps {
  open: boolean
  /** 재실행 대상 PipelineVersion.id — automation 이 version 단위로 붙으므로 키도 versionId. */
  versionId: string
  /** UI 표시용 — concept name */
  pipelineName: string
  /** UI 표시용 — "1.0" 등 */
  pipelineVersion: string
  onClose: () => void
}

/**
 * 수동 재실행 확인 모달 (027 §6 / 028 §1 기준).
 *
 * 2-버튼 UX — 사용자가 delta 검사 유무를 명시적으로 선택.
 *   - `변경사항 존재시 재실행` (if_delta) : 상류 변화 있으면 dispatch, 없으면 no-delta skip 안내
 *   - `강제 최신 재실행` (force_latest)    : delta 무시, 항상 dispatch
 *
 * 실행 결과는 async dispatch 후 Result 화면으로 교체 — 즉시 결과 기다리지 않음.
 */
export default function ManualRerunModal({
  open,
  versionId,
  pipelineName,
  pipelineVersion,
  onClose,
}: ManualRerunModalProps) {
  const [submitting, setSubmitting] = useState<ManualRerunMode | null>(null)
  const [result, setResult] = useState<ManualRerunResult | null>(null)

  const handleClose = () => {
    setSubmitting(null)
    setResult(null)
    onClose()
  }

  const handleSubmit = async (mode: ManualRerunMode) => {
    setSubmitting(mode)
    try {
      const response = await rerunAutomationManually(versionId, mode)
      setResult(response)
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <Modal
      open={open}
      title="수동 재실행"
      onCancel={handleClose}
      footer={null}
      destroyOnClose
      width={520}
    >
      {result ? (
        <Result
          status={result.dispatched ? 'success' : 'info'}
          title={result.dispatched ? '재실행이 dispatch 됐습니다' : '재실행되지 않았습니다'}
          subTitle={result.message}
          extra={<Button onClick={handleClose}>닫기</Button>}
        />
      ) : (
        <>
          <Paragraph>
            대상 파이프라인: <Text strong>{pipelineName}</Text>{' '}
            <Tag color="purple" style={{ fontSize: 11 }}>
              v{pipelineVersion}
            </Tag>
          </Paragraph>
          <Alert
            type="warning"
            showIcon
            message="실행은 비동기 dispatch 됩니다"
            description="결과는 즉시 나오지 않습니다. 실행 이력 페이지에서 진행 상태를 확인하세요."
            style={{ marginBottom: 16 }}
          />
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Button
              type="primary"
              block
              loading={submitting === 'if_delta'}
              disabled={submitting !== null}
              onClick={() => handleSubmit('if_delta')}
            >
              변경사항 존재시 재실행
            </Button>
            <Button
              danger
              block
              loading={submitting === 'force_latest'}
              disabled={submitting !== null}
              onClick={() => handleSubmit('force_latest')}
            >
              강제 최신 재실행
            </Button>
            <Button block type="text" onClick={handleClose} disabled={submitting !== null}>
              취소
            </Button>
          </Space>
        </>
      )}
    </Modal>
  )
}
