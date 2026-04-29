/**
 * PipelineFamily 관리 Modal — list / create / edit / delete.
 *
 * Pipeline 목록 페이지의 "Family 관리" 버튼에서 호출.
 * Family 는 Pipeline 의 즐겨찾기 폴더이며 자유 이동 가능 (강제 구조 X).
 */
import { useState } from 'react'
import {
  Modal,
  Table,
  Button,
  Input,
  Space,
  message,
  Popconfirm,
  Tooltip,
  Typography,
  Tag,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SaveOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnsType } from 'antd/es/table'
import { pipelineFamiliesApi } from '@/api/pipeline'
import type { PipelineFamilyResponse } from '@/types/pipeline'

const { Text } = Typography

interface FamilyManagementModalProps {
  open: boolean
  onClose: () => void
}

interface EditState {
  id: string
  name: string
  description: string
}

export function FamilyManagementModal({
  open,
  onClose,
}: FamilyManagementModalProps) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [editing, setEditing] = useState<EditState | null>(null)

  const listQuery = useQuery({
    queryKey: ['pipeline-families'],
    queryFn: () => pipelineFamiliesApi.list().then((r) => r.data),
    enabled: open,
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['pipeline-families'] })
    queryClient.invalidateQueries({ queryKey: ['pipeline-concepts'] })
    queryClient.invalidateQueries({ queryKey: ['pipeline-concept-detail'] })
  }

  const showError = (err: unknown) => {
    const msg =
      (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      ?? (err as Error)?.message
      ?? '알 수 없는 오류'
    message.error(`처리 실패: ${msg}`)
  }

  const createMutation = useMutation({
    mutationFn: () =>
      pipelineFamiliesApi
        .create({ name: newName.trim(), description: newDescription.trim() || null })
        .then((r) => r.data),
    onSuccess: () => {
      message.success('Family 생성 완료')
      setCreating(false)
      setNewName('')
      setNewDescription('')
      invalidateAll()
    },
    onError: showError,
  })

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; name: string; description: string | null }) =>
      pipelineFamiliesApi
        .update(vars.id, { name: vars.name, description: vars.description })
        .then((r) => r.data),
    onSuccess: () => {
      message.success('Family 수정 완료')
      setEditing(null)
      invalidateAll()
    },
    onError: showError,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => pipelineFamiliesApi.delete(id),
    onSuccess: () => {
      message.success('Family 삭제 완료. 묶여있던 Pipeline 들은 미분류로 전환됩니다.')
      invalidateAll()
    },
    onError: showError,
  })

  const columns: ColumnsType<PipelineFamilyResponse> = [
    {
      title: 'Family',
      dataIndex: 'name',
      key: 'name',
      render: (_v, row) =>
        editing?.id === row.id ? (
          <Input
            size="small"
            value={editing.name}
            onChange={(e) => setEditing({ ...editing, name: e.target.value })}
            onPressEnter={() =>
              updateMutation.mutate({
                id: editing.id,
                name: editing.name.trim(),
                description: editing.description.trim() || null,
              })
            }
          />
        ) : (
          <Text strong>{row.name}</Text>
        ),
    },
    {
      title: '설명',
      dataIndex: 'description',
      key: 'description',
      render: (_v, row) =>
        editing?.id === row.id ? (
          <Input
            size="small"
            value={editing.description}
            placeholder="(선택)"
            onChange={(e) => setEditing({ ...editing, description: e.target.value })}
          />
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.description || '—'}
          </Text>
        ),
    },
    {
      title: '소속 Pipeline',
      dataIndex: 'pipeline_count',
      key: 'pipeline_count',
      width: 110,
      render: (count: number) => (
        <Tag style={{ margin: 0 }}>{count}개 active</Tag>
      ),
    },
    {
      title: '작업',
      key: 'actions',
      width: 150,
      render: (_v, row) =>
        editing?.id === row.id ? (
          <Space size={4}>
            <Tooltip title="저장">
              <Button
                size="small"
                type="primary"
                icon={<SaveOutlined />}
                loading={updateMutation.isPending}
                onClick={() =>
                  updateMutation.mutate({
                    id: editing.id,
                    name: editing.name.trim(),
                    description: editing.description.trim() || null,
                  })
                }
              />
            </Tooltip>
            <Tooltip title="취소">
              <Button
                size="small"
                icon={<CloseOutlined />}
                onClick={() => setEditing(null)}
              />
            </Tooltip>
          </Space>
        ) : (
          <Space size={4}>
            <Tooltip title="이름/설명 수정">
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() =>
                  setEditing({
                    id: row.id,
                    name: row.name,
                    description: row.description ?? '',
                  })
                }
              />
            </Tooltip>
            <Popconfirm
              title="Family 삭제"
              description={
                row.pipeline_count > 0
                  ? `이 family 에 묶인 ${row.pipeline_count}개 Pipeline 은 미분류로 전환됩니다. 진행할까요?`
                  : '삭제할까요?'
              }
              okText="삭제"
              cancelText="취소"
              okButtonProps={{ danger: true }}
              onConfirm={() => deleteMutation.mutate(row.id)}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={deleteMutation.isPending}
              />
            </Popconfirm>
          </Space>
        ),
    },
  ]

  return (
    <Modal
      open={open}
      title="Pipeline Family 관리"
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          Family 는 Pipeline 의 즐겨찾기 폴더입니다. 자유롭게 만들고 옮길 수 있으며,
          Pipeline 은 family 에 속하지 않아도 됩니다 (미분류).
        </Text>
        {creating ? (
          <Space.Compact style={{ width: '100%' }}>
            <Input
              placeholder="새 Family 이름"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoFocus
              style={{ width: '40%' }}
            />
            <Input
              placeholder="설명 (선택)"
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              onPressEnter={() => newName.trim() && createMutation.mutate()}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={createMutation.isPending}
              disabled={!newName.trim()}
              onClick={() => createMutation.mutate()}
            >
              생성
            </Button>
            <Button
              icon={<CloseOutlined />}
              onClick={() => {
                setCreating(false)
                setNewName('')
                setNewDescription('')
              }}
            >
              취소
            </Button>
          </Space.Compact>
        ) : (
          <Button
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => setCreating(true)}
          >
            새 Family 만들기
          </Button>
        )}
        <Table<PipelineFamilyResponse>
          rowKey="id"
          loading={listQuery.isLoading}
          dataSource={listQuery.data ?? []}
          columns={columns}
          pagination={false}
          size="small"
          locale={{ emptyText: 'Family 가 없습니다. 새로 만들어 보세요.' }}
        />
      </Space>
    </Modal>
  )
}
