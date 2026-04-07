/**
 * ExecutionSubmittedModal — 파이프라인 실행 제출 완료 확인 모달
 *
 * 실행 제출 후 polling 없이, 데이터셋 목록에서 상태를 확인하라는 안내만 표시.
 * 파이프라인 실행은 비동기로 진행되므로 사용자가 기다릴 필요 없음.
 */

import { Modal, Result, Button, Space } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'

export default function ExecutionSubmittedModal() {
  const navigate = useNavigate()
  const executionId = usePipelineEditorStore((s) => s.executionId)
  const setExecutionId = usePipelineEditorStore((s) => s.setExecutionId)

  const handleClose = () => {
    setExecutionId(null)
  }

  const handleGoToDatasets = () => {
    setExecutionId(null)
    navigate('/datasets')
  }

  return (
    <Modal
      title={null}
      open={!!executionId}
      onCancel={handleClose}
      footer={null}
      closable
      maskClosable
      width={440}
    >
      <Result
        icon={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
        title="파이프라인 실행 제출 완료"
        subTitle="실행에는 시간이 걸릴 수 있습니다. 데이터셋 목록에서 상태를 확인하세요."
        extra={
          <Space>
            <Button type="primary" onClick={handleGoToDatasets}>
              데이터셋 목록으로 이동
            </Button>
            <Button onClick={handleClose}>계속 편집</Button>
          </Space>
        }
      />
    </Modal>
  )
}
