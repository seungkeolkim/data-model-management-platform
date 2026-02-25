/**
 * 데이터셋 목록 페이지
 * - 데이터셋 그룹 목록 조회 (페이지네이션, 검색)
 * - 데이터셋 등록 버튼 → DatasetRegisterModal
 * - 그룹 행 클릭 → 상세 페이지
 */
import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Typography,
  Button,
  Table,
  Space,
  Tag,
  Input,
  Empty,
  Alert,
  Tooltip,
  Badge,
} from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  ReloadOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { datasetGroupsApi } from '../api/dataset'
import DatasetRegisterModal from '../components/dataset/DatasetRegisterModal'
import type { DatasetGroup, DatasetSummary } from '../types/dataset'

const { Title, Text } = Typography

const STATUS_COLOR: Record<string, string> = {
  READY: 'success',
  PENDING: 'default',
  PROCESSING: 'processing',
  ERROR: 'error',
}

const SPLIT_COLOR: Record<string, string> = {
  TRAIN: 'blue',
  VAL: 'green',
  TEST: 'orange',
  NONE: 'default',
}

export default function DatasetListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [selectedGroup, setSelectedGroup] = useState<DatasetGroup | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dataset-groups', page, pageSize, search],
    queryFn: () =>
      datasetGroupsApi
        .list({ page, page_size: pageSize, search: search || undefined, dataset_type: 'object_detection' })
        .then(r => r.data),
  })

  const handleSearch = useCallback(() => {
    setSearch(searchInput)
    setPage(1)
  }, [searchInput])

  const handleRegisterSuccess = useCallback((group: DatasetGroup) => {
    queryClient.invalidateQueries({ queryKey: ['dataset-groups'] })
    setModalOpen(false)
    setSelectedGroup(null)
  }, [queryClient])

  const columns = [
    {
      title: '그룹명',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: DatasetGroup) => (
        <Space>
          <FolderOpenOutlined style={{ color: '#1677ff' }} />
          <Text strong style={{ cursor: 'pointer', color: '#1677ff' }}
            onClick={() => navigate(`/datasets/${record.id}`)}>
            {name}
          </Text>
        </Space>
      ),
    },
    {
      title: '유형',
      dataIndex: 'dataset_type',
      key: 'dataset_type',
      width: 140,
      render: (v: string) => <Tag color="purple">{v}</Tag>,
    },
    {
      title: 'Split',
      key: 'splits',
      width: 200,
      render: (_: unknown, record: DatasetGroup) => (
        <Space wrap size={4}>
          {record.datasets.map(d => (
            <Tooltip key={d.id} title={`${d.version} · ${d.image_count?.toLocaleString() ?? '-'}장`}>
              <Tag color={SPLIT_COLOR[d.split] ?? 'default'}>
                {d.split}
              </Tag>
            </Tooltip>
          ))}
          {record.datasets.length === 0 && <Text type="secondary" style={{ fontSize: 12 }}>없음</Text>}
        </Space>
      ),
    },
    {
      title: '총 이미지',
      key: 'image_count',
      width: 110,
      align: 'right' as const,
      render: (_: unknown, record: DatasetGroup) => {
        const total = record.datasets.reduce((s, d) => s + (d.image_count ?? 0), 0)
        return total > 0 ? <Text>{total.toLocaleString()}</Text> : <Text type="secondary">-</Text>
      },
    },
    {
      title: '상태',
      key: 'status',
      width: 100,
      render: (_: unknown, record: DatasetGroup) => {
        const statuses = [...new Set(record.datasets.map(d => d.status))]
        if (statuses.length === 0) return <Badge status="default" text="없음" />
        const worst = statuses.includes('ERROR') ? 'ERROR'
          : statuses.includes('PROCESSING') ? 'PROCESSING'
          : statuses.includes('PENDING') ? 'PENDING'
          : 'READY'
        return <Badge status={STATUS_COLOR[worst] as any} text={worst} />
      },
    },
    {
      title: '등록일',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '',
      key: 'action',
      width: 120,
      render: (_: unknown, record: DatasetGroup) => (
        <Space>
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={e => {
              e.stopPropagation()
              setSelectedGroup(record)
              setModalOpen(true)
            }}
          >
            Split 추가
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>데이터셋</Title>
          <Text type="secondary">Object Detection 데이터셋을 관리합니다. (COCO 형식)</Text>
        </div>
        <Space>
          <Tooltip title="새로고침">
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} />
          </Tooltip>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => { setSelectedGroup(null); setModalOpen(true) }}
          >
            데이터셋 등록
          </Button>
        </Space>
      </div>

      {/* 검색 */}
      <div style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="그룹명 검색"
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          onSearch={handleSearch}
          onPressEnter={handleSearch}
          style={{ width: 320 }}
          prefix={<SearchOutlined />}
          allowClear
          onClear={() => { setSearch(''); setSearchInput(''); setPage(1) }}
        />
      </div>

      {/* 오류 */}
      {error && (
        <Alert
          type="error"
          message="데이터셋 목록을 불러오지 못했습니다."
          description="백엔드 연결을 확인하세요."
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 테이블 */}
      <Table
        dataSource={data?.items ?? []}
        columns={columns}
        rowKey="id"
        loading={isLoading}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `총 ${total}개`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        locale={{
          emptyText: (
            <Empty
              description={
                <span>
                  등록된 데이터셋이 없습니다.<br />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    "데이터셋 등록" 버튼을 눌러 COCO 데이터셋을 등록하세요.
                  </Text>
                </span>
              }
            />
          ),
        }}
        onRow={record => ({
          onClick: () => navigate(`/datasets/${record.id}`),
          style: { cursor: 'pointer' },
        })}
      />

      {/* 등록 모달 */}
      <DatasetRegisterModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); setSelectedGroup(null) }}
        onSuccess={handleRegisterSuccess}
        existingGroup={selectedGroup}
      />
    </div>
  )
}
