/**
 * EditorToolbar — 에디터 상단 툴바
 *
 * [뒤로가기] [검증] [실행] [JSON 프리뷰] 버튼을 제공한다.
 */

import { Button, Space, Typography, Tooltip, Badge, Tag } from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  PlayCircleOutlined,
  CodeOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'

const { Text } = Typography

/** 태스크 타입 표시용 라벨 */
const TASK_TYPE_LABEL: Record<string, string> = {
  DETECTION: 'Object Detection',
  SEGMENTATION: 'Segmentation',
  ATTR_CLASSIFICATION: 'Attribute Classification',
  ZERO_SHOT: 'Zero-Shot',
  CLASSIFICATION: 'Classification',
}

interface EditorToolbarProps {
  onValidate: () => void
  onExecute: () => void
  onClearCanvas: () => void
  isValidating: boolean
  isExecuting: boolean
  taskType: string
}

export default function EditorToolbar({
  onValidate,
  onExecute,
  onClearCanvas,
  isValidating,
  isExecuting,
  taskType,
}: EditorToolbarProps) {
  const navigate = useNavigate()
  const validationResult = usePipelineEditorStore((s) => s.validationResult)
  const isJsonPreviewOpen = usePipelineEditorStore((s) => s.isJsonPreviewOpen)
  const toggleJsonPreview = usePipelineEditorStore((s) => s.toggleJsonPreview)

  return (
    <div
      style={{
        height: 48,
        background: '#fff',
        borderBottom: '1px solid #f0f0f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
        zIndex: 10,
      }}
    >
      {/* 좌측: 뒤로가기 + 타이틀 */}
      <Space>
        <Tooltip title="파이프라인 목록으로 돌아가기">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/pipelines')}
          />
        </Tooltip>
        <Text strong style={{ fontSize: 15 }}>
          파이프라인 에디터
        </Text>
        <Tag color="blue">{TASK_TYPE_LABEL[taskType] ?? taskType}</Tag>
      </Space>

      {/* 우측: 액션 버튼들 */}
      <Space>
        {/* 검증 결과 뱃지 */}
        {validationResult && (
          <Space size={4}>
            {validationResult.is_valid ? (
              <Badge status="success" text={<Text style={{ fontSize: 12 }}>검증 통과</Text>} />
            ) : (
              <Badge
                status="error"
                text={
                  <Text style={{ fontSize: 12 }}>
                    오류 {validationResult.error_count} / 경고 {validationResult.warning_count}
                  </Text>
                }
              />
            )}
          </Space>
        )}

        <Button
          icon={<CodeOutlined />}
          type={isJsonPreviewOpen ? 'primary' : 'default'}
          ghost={isJsonPreviewOpen}
          onClick={toggleJsonPreview}
        >
          JSON
        </Button>

        <Button
          icon={<CheckCircleOutlined />}
          onClick={onValidate}
          loading={isValidating}
        >
          검증
        </Button>

        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          onClick={onExecute}
          loading={isExecuting}
        >
          실행
        </Button>

        <Tooltip title="캔버스 초기화">
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={onClearCanvas}
          />
        </Tooltip>
      </Space>
    </div>
  )
}
