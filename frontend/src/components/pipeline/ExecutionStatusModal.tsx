/**
 * ExecutionStatusModal — 파이프라인 실행 상태 polling 모달
 *
 * 실행 제출 후 execution_id로 상태를 주기적으로 조회하여
 * 진행률, 현재 단계, 에러 메시지를 표시한다.
 */

import { useEffect } from 'react'
import { Modal, Progress, Typography, Tag, Space, Result, Button } from 'antd'
import {
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { pipelinesApi } from '@/api/pipeline'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'

const { Text, Paragraph } = Typography

export default function ExecutionStatusModal() {
  const navigate = useNavigate()
  const executionId = usePipelineEditorStore((s) => s.executionId)
  const setExecutionId = usePipelineEditorStore((s) => s.setExecutionId)
  const setExecutionStatus = usePipelineEditorStore((s) => s.setExecutionStatus)

  const { data: statusData } = useQuery({
    queryKey: ['pipeline-execution-status', executionId],
    queryFn: () => pipelinesApi.getStatus(executionId!).then((r) => r.data),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'DONE' || status === 'FAILED') return false
      return 2000  // 2초 간격 polling
    },
    enabled: !!executionId,
  })

  // 스토어에 최신 상태 동기화
  // statusData 객체 참조는 매 query마다 바뀌므로, 실질 변경(status/processed_count)만 추적
  const statusValue = statusData?.status
  const processedCount = statusData?.processed_count
  useEffect(() => {
    if (statusData) {
      setExecutionStatus(statusData)
    }
  }, [statusValue, processedCount, setExecutionStatus]) // eslint-disable-line react-hooks/exhaustive-deps

  const isOpen = !!executionId
  const status = statusData?.status ?? 'PENDING'
  const progressPercent =
    statusData?.total_count && statusData.total_count > 0
      ? Math.round((statusData.processed_count / statusData.total_count) * 100)
      : 0

  const handleClose = () => {
    setExecutionId(null)
    setExecutionStatus(null)
  }

  const handleViewDataset = () => {
    handleClose()
    // 생성된 데이터셋 그룹으로 이동
    if (statusData?.output_dataset_id) {
      navigate(`/datasets`)
    }
  }

  return (
    <Modal
      title="파이프라인 실행"
      open={isOpen}
      onCancel={handleClose}
      footer={null}
      closable={status === 'DONE' || status === 'FAILED'}
      maskClosable={false}
      width={480}
    >
      {/* PENDING / RUNNING 상태 */}
      {(status === 'PENDING' || status === 'RUNNING') && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <LoadingOutlined style={{ fontSize: 40, color: '#1677ff', marginBottom: 16 }} />
          <div>
            <Tag color={status === 'PENDING' ? 'default' : 'processing'}>
              {status === 'PENDING' ? '대기 중' : '실행 중'}
            </Tag>
          </div>

          {statusData?.current_stage && (
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              {statusData.current_stage}
            </Text>
          )}

          {statusData?.total_count != null && statusData.total_count > 0 && (
            <div style={{ marginTop: 16 }}>
              <Progress percent={progressPercent} size="small" />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {statusData.processed_count} / {statusData.total_count}
              </Text>
            </div>
          )}
        </div>
      )}

      {/* DONE 상태 */}
      {status === 'DONE' && (
        <Result
          status="success"
          icon={<CheckCircleOutlined />}
          title="파이프라인 실행 완료"
          subTitle={`실행 ID: ${executionId?.slice(0, 8)}...`}
          extra={
            <Space>
              <Button type="primary" onClick={handleViewDataset}>
                데이터셋 보기
              </Button>
              <Button onClick={handleClose}>닫기</Button>
            </Space>
          }
        />
      )}

      {/* FAILED 상태 */}
      {status === 'FAILED' && (
        <Result
          status="error"
          icon={<CloseCircleOutlined />}
          title="파이프라인 실행 실패"
          subTitle={
            statusData?.error_message ? (
              <Paragraph
                style={{ maxHeight: 200, overflow: 'auto', textAlign: 'left' }}
                type="danger"
              >
                {statusData.error_message}
              </Paragraph>
            ) : (
              '알 수 없는 오류가 발생했습니다.'
            )
          }
          extra={<Button onClick={handleClose}>닫기</Button>}
        />
      )}
    </Modal>
  )
}
