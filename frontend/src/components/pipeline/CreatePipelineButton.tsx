/**
 * CreatePipelineButton — "새 파이프라인" 생성 진입 버튼.
 *
 * 클릭 시 task_type (DETECTION / CLASSIFICATION / ...) 선택 Modal 을 띄우고,
 * 선택 시 `/pipelines/editor?taskType=<KEY>` 로 이동. SEGMENTATION / ZERO_SHOT 은
 * `ready=false` 로 "준비 중" 안내.
 *
 * 원래 PipelineHistoryPage 헤더에 있던 버튼이었으나, v7.10 §9-7 재배선 후 의미상
 * "파이프라인 목록 (Pipeline 엔티티)" 쪽에 배치되는 게 자연스러워 공통 컴포넌트로 분리.
 */
import { useState } from 'react'
import { Button, Modal, Typography } from 'antd'
import {
  PlusOutlined,
  AimOutlined,
  AppstoreOutlined,
  PictureOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { TaskType } from '@/types/dataset'

const { Text } = Typography

const TASK_TYPE_OPTIONS: {
  key: TaskType
  label: string
  description: string
  icon: React.ReactNode
  color: string
  ready: boolean
}[] = [
  {
    key: 'DETECTION',
    label: 'Object Detection',
    description: 'COCO/YOLO 포맷 기반 객체 탐지 데이터 변형',
    icon: <AimOutlined style={{ fontSize: 28 }} />,
    color: '#1677ff',
    ready: true,
  },
  {
    key: 'SEGMENTATION',
    label: 'Segmentation',
    description: '세그멘테이션 마스크 기반 데이터 변형',
    icon: <AppstoreOutlined style={{ fontSize: 28 }} />,
    color: '#52c41a',
    ready: false,
  },
  {
    key: 'CLASSIFICATION',
    label: 'Classification',
    description: '이미지 분류 데이터 변형 (단일/다중 head 포함)',
    icon: <PictureOutlined style={{ fontSize: 28 }} />,
    color: '#13c2c2',
    ready: true,
  },
  {
    key: 'ZERO_SHOT',
    label: 'Zero-Shot',
    description: '제로샷 학습용 데이터 변형',
    icon: <SearchOutlined style={{ fontSize: 28 }} />,
    color: '#722ed1',
    ready: false,
  },
]

interface CreatePipelineButtonProps {
  /** 버튼 라벨 — 기본 "새 파이프라인" */
  label?: string
}

export function CreatePipelineButton({ label = '새 파이프라인' }: CreatePipelineButtonProps) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        {label}
      </Button>

      <Modal
        title="데이터 변형 유형 선택"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width={640}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          변형할 데이터의 유형을 선택하세요. 유형에 따라 사용 가능한 Manipulator가 달라집니다.
        </Text>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {TASK_TYPE_OPTIONS.map((opt) => (
            <div
              key={opt.key}
              onClick={() => {
                if (opt.ready) {
                  setOpen(false)
                  navigate(`/pipelines/editor?taskType=${opt.key}`)
                } else {
                  Modal.info({
                    title: '준비 중',
                    content: `${opt.label} 유형의 데이터 변형은 아직 준비 중입니다.`,
                    okText: '확인',
                  })
                }
              }}
              style={{
                border: `1px solid ${opt.ready ? opt.color : '#d9d9d9'}`,
                borderRadius: 8,
                padding: 16,
                cursor: opt.ready ? 'pointer' : 'not-allowed',
                opacity: opt.ready ? 1 : 0.55,
                transition: 'transform 0.12s ease',
                background: '#fff',
              }}
              onMouseEnter={(e) => {
                if (opt.ready) (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)'
              }}
              onMouseLeave={(e) => {
                if (opt.ready) (e.currentTarget as HTMLDivElement).style.transform = 'translateY(0)'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ color: opt.color }}>{opt.icon}</div>
                <div>
                  <Text strong style={{ fontSize: 14, display: 'block' }}>
                    {opt.label}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {opt.description}
                  </Text>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </>
  )
}
