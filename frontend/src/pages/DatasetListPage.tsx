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
  Popconfirm,
  Select,
  message,
} from 'antd'
import type { TableProps } from 'antd'
import type { SortOrder } from 'antd/es/table/interface'
import {
  PlusOutlined,
  SearchOutlined,
  ReloadOutlined,
  FolderOpenOutlined,
  DeleteOutlined,
  ClearOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { datasetGroupsApi } from '../api/dataset'
import DatasetRegisterModal from '../components/dataset/DatasetRegisterModal'
import type { DatasetGroup, DatasetSummary } from '../types/dataset'
import { useResizableColumnWidths } from '../components/common/ResizableTableColumns'

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

// 그룹 목록 Split 컬럼에서 split별 표시 순서. 등록 순서와 무관하게 항상 동일.
const SPLIT_ORDER: Record<string, number> = {
  TRAIN: 0,
  VAL: 1,
  TEST: 2,
  NONE: 3,
}

/**
 * "{major}.{minor}" 형식의 버전 문자열을 숫자 튜플로 파싱.
 * 파싱 실패 시 [-1, -1]로 취급해 정상 버전에 밀리도록 한다.
 */
function parseVersionTuple(version: string): [number, number] {
  const [majorRaw, minorRaw] = (version ?? '').split('.')
  const major = Number.parseInt(majorRaw, 10)
  const minor = Number.parseInt(minorRaw, 10)
  return [
    Number.isFinite(major) ? major : -1,
    Number.isFinite(minor) ? minor : -1,
  ]
}

/**
 * split(TRAIN/VAL/TEST/NONE)별로 가장 최신 버전의 Dataset 한 개씩을 골라
 * SPLIT_ORDER 순서대로 정렬해 반환한다.
 * 같은 split에 여러 version이 존재해도 태그가 중복되지 않도록 하기 위한 도우미.
 */
function pickLatestDatasetPerSplit(datasets: DatasetSummary[]): DatasetSummary[] {
  const latestBySplit = new Map<string, DatasetSummary>()
  for (const dataset of datasets) {
    const current = latestBySplit.get(dataset.split)
    if (!current) {
      latestBySplit.set(dataset.split, dataset)
      continue
    }
    const [currentMajor, currentMinor] = parseVersionTuple(current.version)
    const [nextMajor, nextMinor] = parseVersionTuple(dataset.version)
    const isNewer =
      nextMajor > currentMajor ||
      (nextMajor === currentMajor && nextMinor > currentMinor)
    if (isNewer) {
      latestBySplit.set(dataset.split, dataset)
    }
  }
  return Array.from(latestBySplit.values()).sort(
    (a, b) => (SPLIT_ORDER[a.split] ?? 99) - (SPLIT_ORDER[b.split] ?? 99),
  )
}

export default function DatasetListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  // 필터 상태 — 다중 선택. 빈 배열이면 필터 미적용(undefined 로 바꿔 서버 전달).
  const [datasetTypeFilter, setDatasetTypeFilter] = useState<string[]>([])
  const [taskTypeFilter, setTaskTypeFilter] = useState<string[]>([])
  const [annotationFormatFilter, setAnnotationFormatFilter] = useState<string[]>([])
  // 정렬 상태 — 기본값은 서버 기본값(updated_at desc)과 동일하게 둔다.
  // 컬럼 헤더 클릭(Table onChange)으로 토글되며, 페이지네이션/필터는 유지된다.
  type SortColumnKey =
    | 'name'
    | 'dataset_type'
    | 'task_types'
    | 'annotation_format'
    | 'created_at'
    | 'updated_at'
    | 'dataset_count'
    | 'total_image_count'
  const [sortBy, setSortBy] = useState<SortColumnKey>('updated_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [modalOpen, setModalOpen] = useState(false)
  const [selectedGroup, setSelectedGroup] = useState<DatasetGroup | null>(null)
  const [deletingGroupId, setDeletingGroupId] = useState<string | null>(null)

  // 그룹 목록 테이블의 컬럼별 초기 너비. 헤더 우측 경계 드래그로 조정 가능.
  const {
    widthByKey: groupColumnWidths,
    buildHeaderCellProps: buildGroupHeaderCellProps,
    tableComponents: resizableTableComponents,
  } = useResizableColumnWidths({
    name: 280,
    dataset_type: 110,
    task_types: 130,
    annotation_format: 85,
    splits: 160,
    image_count: 110,
    status: 100,
    created_at: 120,
    updated_at: 120,
    action: 180,
  })

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: [
      'dataset-groups',
      page,
      pageSize,
      search,
      datasetTypeFilter,
      taskTypeFilter,
      annotationFormatFilter,
      sortBy,
      sortOrder,
    ],
    queryFn: () =>
      datasetGroupsApi
        .list({
          page,
          page_size: pageSize,
          search: search || undefined,
          dataset_type: datasetTypeFilter.length > 0 ? datasetTypeFilter : undefined,
          task_type: taskTypeFilter.length > 0 ? taskTypeFilter : undefined,
          annotation_format:
            annotationFormatFilter.length > 0 ? annotationFormatFilter : undefined,
          sort_by: sortBy,
          sort_order: sortOrder,
        })
        .then(r => r.data),
  })

  const handleSearch = useCallback(() => {
    setSearch(searchInput)
    setPage(1)
  }, [searchInput])

  // 필터 값이 바뀌면 현재 페이지의 의미가 달라지므로 1페이지로 되돌린다.
  const handleDatasetTypeFilterChange = useCallback((values: string[]) => {
    setDatasetTypeFilter(values)
    setPage(1)
  }, [])
  const handleTaskTypeFilterChange = useCallback((values: string[]) => {
    setTaskTypeFilter(values)
    setPage(1)
  }, [])
  const handleAnnotationFormatFilterChange = useCallback((values: string[]) => {
    setAnnotationFormatFilter(values)
    setPage(1)
  }, [])

  // 검색어 + 3종 필터를 모두 초기화. 정렬/페이지 크기는 사용자의 뷰 설정으로 보고
  // 유지하되 페이지만 1로 리셋한다.
  const handleResetFilters = useCallback(() => {
    setSearch('')
    setSearchInput('')
    setDatasetTypeFilter([])
    setTaskTypeFilter([])
    setAnnotationFormatFilter([])
    setPage(1)
  }, [])

  // 하나라도 필터/검색이 활성화돼 있는지 — reset 버튼 disabled 판단에 사용.
  const hasActiveFilter =
    search !== '' ||
    datasetTypeFilter.length > 0 ||
    taskTypeFilter.length > 0 ||
    annotationFormatFilter.length > 0

  // Ant Design Table onChange 는 pagination/filters/sorter 를 한꺼번에 통지한다.
  // 여기서는 sorter 변경만 서버 정렬 파라미터에 반영한다. pagination/필터는
  // 기존 state (setPage 등) 에서 직접 처리하므로 중복 처리하지 않는다.
  const handleTableChange: TableProps<DatasetGroup>['onChange'] = (
    _pagination,
    _filters,
    sorter,
  ) => {
    const activeSorter = Array.isArray(sorter) ? sorter[0] : sorter
    // 정렬 해제(order===undefined)면 기본값(updated_at desc)으로 복원.
    if (!activeSorter || !activeSorter.order) {
      setSortBy('updated_at')
      setSortOrder('desc')
      return
    }
    const columnKey = activeSorter.columnKey as SortColumnKey | undefined
    if (!columnKey) return
    setSortBy(columnKey)
    setSortOrder(activeSorter.order === 'ascend' ? 'asc' : 'desc')
  }

  // Ant Design Table 에 현재 정렬 상태를 되돌려 주기 위한 도우미.
  // 컬럼 정의마다 sortOrder 필드를 이 결과로 설정해 화살표를 표시한다.
  const antdSortOrder: SortOrder = sortOrder === 'asc' ? 'ascend' : 'descend'
  const buildSortOrderForColumn = (columnKey: SortColumnKey): SortOrder =>
    sortBy === columnKey ? antdSortOrder : null

  const handleRegisterSuccess = useCallback((group: DatasetGroup) => {
    queryClient.invalidateQueries({ queryKey: ['dataset-groups'] })
    setModalOpen(false)
    setSelectedGroup(null)
  }, [queryClient])

  const handleDeleteGroup = async (groupId: string) => {
    setDeletingGroupId(groupId)
    try {
      const response = await datasetGroupsApi.delete(groupId)
      message.success(response.data.message)
      queryClient.invalidateQueries({ queryKey: ['dataset-groups'] })
    } catch (requestError: any) {
      const errorDetail = requestError?.response?.data?.detail || '그룹 삭제 중 오류가 발생했습니다.'
      message.error(errorDetail)
    } finally {
      setDeletingGroupId(null)
    }
  }

  // 사용 목적(task type)별 태그 색상. DETECTION / CLASSIFICATION 구분이 한눈에 보이도록
  // 서로 대비되는 톤을 사용하고, 그 외는 기본 보라색으로 폴백한다.
  const TASK_TYPE_TAG_COLOR: Record<string, string> = {
    DETECTION: 'geekblue',
    CLASSIFICATION: 'magenta',
    SEGMENTATION: 'cyan',
    ZERO_SHOT: 'gold',
  }

  const columns = [
    {
      title: '사용 목적',
      key: 'task_types',
      width: groupColumnWidths.task_types,
      onHeaderCell: buildGroupHeaderCellProps('task_types'),
      sorter: true,
      sortOrder: buildSortOrderForColumn('task_types'),
      render: (_: unknown, record: DatasetGroup) => (
        <Space wrap size={4}>
          {(record.task_types ?? []).map(t => (
            <Tag key={t} color={TASK_TYPE_TAG_COLOR[t] ?? 'purple'} style={{ margin: 0 }}>
              {t}
            </Tag>
          ))}
          {!record.task_types?.length && <Text type="secondary">-</Text>}
        </Space>
      ),
    },
    {
      title: '그룹명',
      dataIndex: 'name',
      key: 'name',
      width: groupColumnWidths.name,
      onHeaderCell: buildGroupHeaderCellProps('name'),
      // 서버 측 정렬. 실제 비교는 DB 에서 수행하므로 sorter: true 로만 둔다.
      sorter: true,
      sortOrder: buildSortOrderForColumn('name'),
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
      title: '데이터 유형',
      dataIndex: 'dataset_type',
      key: 'dataset_type',
      width: groupColumnWidths.dataset_type,
      onHeaderCell: buildGroupHeaderCellProps('dataset_type'),
      sorter: true,
      sortOrder: buildSortOrderForColumn('dataset_type'),
      render: (v: string) => {
        const color: Record<string, string> = {
          RAW: 'default', SOURCE: 'blue', PROCESSED: 'green', FUSION: 'volcano',
        }
        return <Tag color={color[v] ?? 'default'}>{v}</Tag>
      },
    },
    {
      title: '포맷',
      dataIndex: 'annotation_format',
      key: 'annotation_format',
      width: groupColumnWidths.annotation_format,
      onHeaderCell: buildGroupHeaderCellProps('annotation_format'),
      sorter: true,
      sortOrder: buildSortOrderForColumn('annotation_format'),
      render: (v: string) => {
        const color: Record<string, string> = {
          COCO: 'green', YOLO: 'orange', ATTR_JSON: 'cyan',
          CLS_MANIFEST: 'geekblue', CUSTOM: 'purple', NONE: 'default',
        }
        return <Tag color={color[v] ?? 'default'}>{v ?? 'NONE'}</Tag>
      },
    },
    {
      title: 'Split',
      key: 'splits',
      width: groupColumnWidths.splits,
      onHeaderCell: buildGroupHeaderCellProps('splits'),
      render: (_: unknown, record: DatasetGroup) => {
        // split(TRAIN/VAL/TEST/NONE)별로 가장 최신 버전 1개씩만 추려 보여준다.
        // 같은 split에 여러 version이 있어도 tag가 중복으로 뜨지 않도록 함.
        const latestBySplit = pickLatestDatasetPerSplit(record.datasets)
        return (
          <Space wrap size={4}>
            {latestBySplit.map(dataset => (
              <Tooltip
                key={dataset.id}
                title={
                  <span>
                    버전: {dataset.version}<br />
                    이미지: {dataset.image_count?.toLocaleString() ?? '-'}장<br />
                    포맷: {dataset.annotation_format ?? 'NONE'}<br />
                    상태: {dataset.status}
                  </span>
                }
              >
                <Tag color={SPLIT_COLOR[dataset.split] ?? 'default'}>
                  {dataset.split}
                </Tag>
              </Tooltip>
            ))}
            {latestBySplit.length === 0 && <Text type="secondary" style={{ fontSize: 12 }}>없음</Text>}
          </Space>
        )
      },
    },
    {
      title: '총 이미지',
      // columnKey 를 서버 sort_by 값(total_image_count)과 일치시켜,
      // onChange 에서 그대로 백엔드로 전달할 수 있게 한다.
      key: 'total_image_count',
      width: groupColumnWidths.image_count,
      onHeaderCell: buildGroupHeaderCellProps('image_count'),
      align: 'right' as const,
      sorter: true,
      sortOrder: buildSortOrderForColumn('total_image_count'),
      render: (_: unknown, record: DatasetGroup) => {
        const total = record.datasets.reduce((s, d) => s + (d.image_count ?? 0), 0)
        return total > 0 ? <Text>{total.toLocaleString()}</Text> : <Text type="secondary">-</Text>
      },
    },
    {
      title: '상태',
      key: 'status',
      width: groupColumnWidths.status,
      onHeaderCell: buildGroupHeaderCellProps('status'),
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
      width: groupColumnWidths.created_at,
      onHeaderCell: buildGroupHeaderCellProps('created_at'),
      sorter: true,
      sortOrder: buildSortOrderForColumn('created_at'),
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '최종 수정일',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: groupColumnWidths.updated_at,
      onHeaderCell: buildGroupHeaderCellProps('updated_at'),
      sorter: true,
      sortOrder: buildSortOrderForColumn('updated_at'),
      // 등록일과 달리 같은 날 여러 번 수정되는 경우가 많으므로 시:분까지 표시.
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '',
      key: 'action',
      width: groupColumnWidths.action,
      onHeaderCell: buildGroupHeaderCellProps('action'),
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
          <Popconfirm
            title="그룹 삭제"
            description={
              <>
                <strong>'{record.name}'</strong> 그룹과 하위 데이터셋
                {record.datasets.length > 0 && ` ${record.datasets.length}건`}을
                모두 삭제하시겠습니까?
              </>
            }
            onConfirm={() => handleDeleteGroup(record.id)}
            okText="삭제"
            cancelText="취소"
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingGroupId === record.id}
              onClick={e => e.stopPropagation()}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="dataset-list-page">
      {/*
        AntD 기본 `.ant-table-content > table { width: 100% }` 가 컨테이너를
        채우면서 `table-layout: fixed` 컬럼들에 잉여 폭을 비례 분배하는 문제 회피.
        가장 넓은 컬럼 (그룹명 등) 이 잉여를 가장 많이 받아 우측 공백 + 드래그
        축소가 시각적으로 안 먹는 증상을 만든다. → inner table 폭을 max-content
        로 고정하고 잉여는 wrapper 우측 여백으로 흘려보낸다.
        (PipelineHistoryPage 와 동일 처리. 설계서 §6-3 참고)
      */}
      <style>{`
        .dataset-list-page .ant-table-content > table,
        .dataset-list-page .ant-table-body > table {
          width: max-content !important;
          min-width: 0 !important;
        }
      `}</style>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>데이터셋 그룹</Title>
          <Text type="secondary">등록된 데이터셋 그룹 목록입니다. 그룹 행을 클릭하면 상세 페이지로 이동합니다.</Text>
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
            원천 데이터셋 등록
          </Button>
        </Space>
      </div>

      {/* 검색 + 필터 바 — 모든 필터는 서버 측에서 적용되며, 값이 바뀌면 1페이지로 복귀한다.
          좌측 필터 영역과 우측 reset 버튼을 flex 로 분리해서, 넓은 화면에서도 reset 이
          항상 오른쪽 끝에 붙도록 한다. */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          marginBottom: 16,
        }}
      >
        <Space wrap size={8}>
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
          {/* 다중 선택 Select — mode="multiple" 이면 드롭다운 옵션 좌측에 체크박스 형태의
              선택 마크가 표시되고 선택된 값들은 태그로 노출된다. maxTagCount="responsive"
              로 필터 너비를 초과하면 "+N" 배지로 축약한다. */}
          <Select
            mode="multiple"
            allowClear
            placeholder="데이터 유형"
            value={datasetTypeFilter}
            onChange={handleDatasetTypeFilterChange}
            style={{ minWidth: 180 }}
            maxTagCount="responsive"
            options={[
              { value: 'RAW', label: 'RAW' },
              { value: 'SOURCE', label: 'SOURCE' },
              { value: 'PROCESSED', label: 'PROCESSED' },
              { value: 'FUSION', label: 'FUSION' },
            ]}
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="사용 목적"
            value={taskTypeFilter}
            onChange={handleTaskTypeFilterChange}
            style={{ minWidth: 220 }}
            maxTagCount="responsive"
            options={[
              { value: 'DETECTION', label: 'DETECTION' },
              { value: 'CLASSIFICATION', label: 'CLASSIFICATION' },
              { value: 'SEGMENTATION', label: 'SEGMENTATION' },
              { value: 'ZERO_SHOT', label: 'ZERO_SHOT' },
            ]}
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="포맷"
            value={annotationFormatFilter}
            onChange={handleAnnotationFormatFilterChange}
            style={{ minWidth: 200 }}
            maxTagCount="responsive"
            options={[
              { value: 'COCO', label: 'COCO' },
              { value: 'YOLO', label: 'YOLO' },
              { value: 'ATTR_JSON', label: 'ATTR_JSON' },
              { value: 'CLS_MANIFEST', label: 'CLS_MANIFEST' },
              { value: 'CUSTOM', label: 'CUSTOM' },
              { value: 'NONE', label: 'NONE' },
            ]}
          />
        </Space>
        <Button
          icon={<ClearOutlined />}
          onClick={handleResetFilters}
          disabled={!hasActiveFilter}
        >
          reset filter
        </Button>
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

      {/* 테이블 — 컬럼 너비는 헤더 우측 경계 드래그로 조정 가능,
          좁은 창에서는 가로 스크롤로 대응(그룹명 컬럼이 쪼개지는 문제 방지). */}
      <Table
        dataSource={data?.items ?? []}
        columns={columns}
        components={resizableTableComponents}
        scroll={{ x: 'max-content' }}
        rowKey="id"
        loading={isLoading}
        onChange={handleTableChange}
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
                    "데이터셋 등록" 버튼을 눌러 데이터셋을 등록하세요.
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
