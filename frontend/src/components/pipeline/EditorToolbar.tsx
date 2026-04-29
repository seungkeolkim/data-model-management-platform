/**
 * EditorToolbar — 에디터 상단 툴바
 *
 * [뒤로가기] [검증] [저장] [JSON 프리뷰] 버튼을 제공한다.
 *
 * §12-1 저장/실행 분리: "실행" 은 더 이상 에디터에서 트리거하지 않는다.
 * 저장 후 파이프라인 목록의 행 우측 "실행" 버튼으로 Version Resolver Modal 에 진입.
 */

import { Button, Space, Typography, Tooltip, Badge, Tag } from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  SaveOutlined,
  CodeOutlined,
  DeleteOutlined,
  ImportOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { usePipelineEditorStore } from '@/stores/pipelineEditorStore'

const { Text } = Typography

/** 태스크 타입 표시용 라벨 */
const TASK_TYPE_LABEL: Record<string, string> = {
  DETECTION: 'Object Detection',
  SEGMENTATION: 'Segmentation',
  CLASSIFICATION: 'Classification',
  ZERO_SHOT: 'Zero-Shot',
}

interface EditorToolbarProps {
  onValidate: () => void
  onSave: () => void
  onClearCanvas: () => void
  onLoadJson: () => void
  isValidating: boolean
  isSaving: boolean
  taskType: string
}

export default function EditorToolbar({
  onValidate,
  onSave,
  onClearCanvas,
  onLoadJson,
  isValidating,
  isSaving,
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
          icon={<ImportOutlined />}
          onClick={onLoadJson}
        >
          JSON 불러오기
        </Button>

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

        <Tooltip title="Pipeline (concept) + 새 PipelineVersion 으로 저장. 실행은 목록 페이지에서.">
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={onSave}
            loading={isSaving}
          >
            저장
          </Button>
        </Tooltip>

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
