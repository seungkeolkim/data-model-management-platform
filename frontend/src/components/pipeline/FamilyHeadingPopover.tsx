/**
 * Family heading 클릭 시 설명 + 인라인 수정 토글을 띄우는 Popover.
 * Pipeline 목록의 family 그룹 라벨에 부착.
 */
import { useState } from 'react'
import {
  Popover,
  Tag,
  Button,
  Input,
  Space,
  Typography,
  message,
  ColorPicker,
} from 'antd'
import type { Color } from 'antd/es/color-picker'
import {
  ApartmentOutlined,
  EditOutlined,
  SaveOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { pipelineFamiliesApi } from '@/api/pipeline'
import type { PipelineFamilyResponse } from '@/types/pipeline'

const { Text } = Typography

interface FamilyHeadingPopoverProps {
  family: PipelineFamilyResponse
}

export function FamilyHeadingPopover({ family }: FamilyHeadingPopoverProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draftName, setDraftName] = useState(family.name)
  const [draftDescription, setDraftDescription] = useState(family.description ?? '')
  const [draftColor, setDraftColor] = useState(family.color)

  const updateMutation = useMutation({
    mutationFn: () =>
      pipelineFamiliesApi
        .update(family.id, {
          name: draftName.trim(),
          description: draftDescription.trim() || null,
          color: draftColor,
        })
        .then((r) => r.data),
    onSuccess: () => {
      message.success('Family 수정 완료')
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['pipeline-families'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-concepts'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-concept-detail'] })
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err as Error)?.message
        ?? '알 수 없는 오류'
      message.error(`수정 실패: ${msg}`)
    },
  })

  const startEdit = () => {
    setDraftName(family.name)
    setDraftDescription(family.description ?? '')
    setDraftColor(family.color)
    setEditing(true)
  }
  const cancelEdit = () => {
    setEditing(false)
  }

  const content = (
    <div style={{ minWidth: 260, maxWidth: 360 }}>
      {!editing && (
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>이름</Text>
            <div>
              <Space size={6}>
                <span
                  style={{
                    display: 'inline-block',
                    width: 14,
                    height: 14,
                    borderRadius: 3,
                    background: family.color,
                    border: '1px solid rgba(0,0,0,0.08)',
                    verticalAlign: 'middle',
                  }}
                />
                <Text strong>{family.name}</Text>
              </Space>
            </div>
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>설명</Text>
            <div>
              {family.description ? (
                <Text>{family.description}</Text>
              ) : (
                <Text type="secondary">—</Text>
              )}
            </div>
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>
              소속 Pipeline: {family.pipeline_count}개 active
            </Text>
          </div>
          <Button
            type="primary"
            size="small"
            icon={<EditOutlined />}
            onClick={startEdit}
            style={{ alignSelf: 'flex-start' }}
          >
            수정
          </Button>
        </Space>
      )}
      {editing && (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>이름</Text>
            <Input
              size="small"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>설명 (선택)</Text>
            <Input.TextArea
              size="small"
              rows={2}
              value={draftDescription}
              onChange={(e) => setDraftDescription(e.target.value)}
              placeholder="이 family 의 용도를 적어주세요"
            />
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>색상</Text>
            <div>
              <ColorPicker
                value={draftColor}
                onChange={(c: Color) => setDraftColor(c.toHexString())}
                disabledAlpha
                showText
                presets={[
                  {
                    label: '추천',
                    colors: [
                      '#8a91a8', '#6c8aae', '#7ab0a8', '#a3b56b',
                      '#d8a657', '#d68a8a', '#a37cb5', '#b58a6c',
                      '#5a7a9a', '#7c9a5a', '#9a7c5a', '#9a5a7c',
                    ],
                  },
                ]}
              />
            </div>
          </div>
          <Space size={6}>
            <Button
              type="primary"
              size="small"
              icon={<SaveOutlined />}
              loading={updateMutation.isPending}
              disabled={!draftName.trim()}
              onClick={() => updateMutation.mutate()}
            >
              저장
            </Button>
            <Button
              size="small"
              icon={<CloseOutlined />}
              onClick={cancelEdit}
            >
              취소
            </Button>
          </Space>
        </Space>
      )}
    </div>
  )

  return (
    <Popover
      content={content}
      title={null}
      trigger="click"
      open={open}
      onOpenChange={(v) => {
        setOpen(v)
        if (!v) setEditing(false)
      }}
      placement="bottomLeft"
      destroyTooltipOnHide
    >
      <Tag
        style={{
          margin: 0,
          fontSize: 12,
          cursor: 'pointer',
          background: family.color,
          color: '#fff',
          borderColor: family.color,
        }}
      >
        <ApartmentOutlined /> {family.name}
      </Tag>
    </Popover>
  )
}
