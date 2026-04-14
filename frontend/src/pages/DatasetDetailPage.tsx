/**
 * 데이터셋 그룹 상세 페이지
 * - 그룹 기본 정보 (Descriptions)
 * - 소속 데이터셋(split × version) 목록 테이블
 * - 클래스 정보 Popover 상세보기 + 검증 버튼
 * - 데이터셋 개별 삭제 + 그룹 삭제
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Typography,
  Descriptions,
  Table,
  Tag,
  Badge,
  Space,
  Button,
  Spin,
  Alert,
  Popconfirm,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { datasetGroupsApi, datasetsApi } from '../api/dataset'
import ServerFileBrowser from '../components/common/ServerFileBrowser'
import type { AnnotationFormat, DatasetSummary } from '../types/dataset'
import { resolveDatasetKind } from '../dataset-display-sdk/registry'
import type { DatasetListCellContext } from '../dataset-display-sdk/types'
import { useResizableColumnWidths } from '../components/common/ResizableTableColumns'

const { Title, Text } = Typography

const STATUS_BADGE: Record<string, string> = {
  READY: 'success',
  PENDING: 'default',
  PROCESSING: 'processing',
  ERROR: 'error',
}

const SPLIT_ORDER: Record<string, number> = {
  TRAIN: 0,
  VAL: 1,
  TEST: 2,
  NONE: 3,
}

const SPLIT_COLOR: Record<string, string> = {
  TRAIN: 'blue',
  VAL: 'green',
  TEST: 'orange',
  NONE: 'default',
}

const FORMAT_COLOR: Record<string, string> = {
  COCO: 'green',
  YOLO: 'orange',
  ATTR_JSON: 'cyan',
  CLS_MANIFEST: 'geekblue',
  CUSTOM: 'purple',
  NONE: 'default',
}

export default function DatasetDetailPage() {
  const { groupId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [validatingDatasetId, setValidatingDatasetId] = useState<string | null>(null)
  const [updatingFormatDatasetId, setUpdatingFormatDatasetId] = useState<string | null>(null)
  const [deletingDatasetId, setDeletingDatasetId] = useState<string | null>(null)
  const [deletingGroup, setDeletingGroup] = useState(false)
  // 포맷 편집 모드: dataset ID → 선택 중인 포맷 값
  const [editingFormatId, setEditingFormatId] = useState<string | null>(null)
  const [editingFormatValue, setEditingFormatValue] = useState<AnnotationFormat>('NONE')
  // 메타 파일 교체
  const [metaFileTargetDatasetId, setMetaFileTargetDatasetId] = useState<string | null>(null)
  const [metaFileBrowserOpen, setMetaFileBrowserOpen] = useState(false)
  const [replacingMetaFileDatasetId, setReplacingMetaFileDatasetId] = useState<string | null>(null)

  // 데이터셋 목록 테이블의 컬럼별 초기 너비. 헤더 우측 경계 드래그로 조정 가능.
  // 훅 호출은 early-return 이전이어야 하므로 최상위에 둔다.
  const {
    widthByKey: datasetColumnWidths,
    buildHeaderCellProps: buildDatasetHeaderCellProps,
    tableComponents: resizableTableComponents,
  } = useResizableColumnWidths({
    split: 100,
    version: 100,
    status: 110,
    image_count: 110,
    class_info: 280,
    annotation_format: 180,
    storage_uri: 200,
    created_at: 120,
    action: 120,
  })

  const { data: group, isLoading, error } = useQuery({
    queryKey: ['dataset-group', groupId],
    queryFn: () => datasetGroupsApi.get(groupId!).then(r => r.data),
    enabled: !!groupId,
  })

  /** 포맷 편집 모드 진입 */
  const startEditingFormat = (record: DatasetSummary) => {
    setEditingFormatId(record.id)
    setEditingFormatValue((record.annotation_format ?? 'NONE') as AnnotationFormat)
  }

  /** 포맷 변경 확정 */
  const confirmFormatChange = async (datasetId: string) => {
    setUpdatingFormatDatasetId(datasetId)
    try {
      await datasetsApi.update(datasetId, { annotation_format: editingFormatValue })
      message.success(`포맷이 ${editingFormatValue}(으)로 변경되었습니다. 클래스 정보는 재검증이 필요합니다.`)
      queryClient.invalidateQueries({ queryKey: ['dataset-group', groupId] })
    } catch (requestError: any) {
      const errorDetail = requestError?.response?.data?.detail || '포맷 변경 중 오류가 발생했습니다.'
      message.error(errorDetail)
    } finally {
      setUpdatingFormatDatasetId(null)
      setEditingFormatId(null)
    }
  }

  /** 데이터셋 검증 실행 — 현재 포맷 기준으로 검증하고 클래스 정보 저장 */
  const handleValidateDataset = async (record: DatasetSummary) => {
    const annotationFormat = record.annotation_format || group?.annotation_format
    if (!annotationFormat || annotationFormat === 'NONE') {
      message.warning('어노테이션 포맷이 지정되지 않아 검증할 수 없습니다.')
      return
    }

    setValidatingDatasetId(record.id)
    try {
      const response = await datasetsApi.validate(record.id, {
        annotation_format: annotationFormat,
      })
      if (response.data.valid) {
        message.success('검증 완료 — 클래스 정보가 저장되었습니다.')
        queryClient.invalidateQueries({ queryKey: ['dataset-group', groupId] })
      } else {
        message.error(`검증 실패: ${response.data.errors.join(', ')}`)
      }
    } catch (requestError: any) {
      const errorDetail = requestError?.response?.data?.detail || '검증 요청 중 오류가 발생했습니다.'
      message.error(errorDetail)
    } finally {
      setValidatingDatasetId(null)
    }
  }

  /** 데이터셋 개별 삭제 */
  const handleDeleteDataset = async (record: DatasetSummary) => {
    setDeletingDatasetId(record.id)
    try {
      const response = await datasetsApi.delete(record.id)
      message.success(response.data.message)
      queryClient.invalidateQueries({ queryKey: ['dataset-group', groupId] })
    } catch (requestError: any) {
      const errorDetail = requestError?.response?.data?.detail || '삭제 중 오류가 발생했습니다.'
      message.error(errorDetail)
    } finally {
      setDeletingDatasetId(null)
    }
  }

  /** 메타 파일 교체 — ServerFileBrowser에서 선택 후 호출 */
  const handleReplaceMetaFile = async (paths: string[]) => {
    if (!metaFileTargetDatasetId || paths.length === 0) return
    const datasetId = metaFileTargetDatasetId
    setMetaFileBrowserOpen(false)
    setReplacingMetaFileDatasetId(datasetId)
    try {
      await datasetsApi.replaceMetaFile(datasetId, paths[0])
      message.success('메타 파일이 교체되었습니다.')
      queryClient.invalidateQueries({ queryKey: ['dataset-group', groupId] })
    } catch (requestError: any) {
      const errorDetail = requestError?.response?.data?.detail || '메타 파일 교체 중 오류가 발생했습니다.'
      message.error(errorDetail)
    } finally {
      setReplacingMetaFileDatasetId(null)
      setMetaFileTargetDatasetId(null)
    }
  }

  /** 그룹 전체 삭제 */
  const handleDeleteGroup = async () => {
    if (!groupId) return
    setDeletingGroup(true)
    try {
      const response = await datasetGroupsApi.delete(groupId)
      message.success(response.data.message)
      queryClient.invalidateQueries({ queryKey: ['dataset-groups'] })
      navigate('/datasets')
    } catch (requestError: any) {
      const errorDetail = requestError?.response?.data?.detail || '그룹 삭제 중 오류가 발생했습니다.'
      message.error(errorDetail)
    } finally {
      setDeletingGroup(false)
    }
  }

  if (isLoading) {
    return <Spin size="large" style={{ display: 'block', marginTop: 120, textAlign: 'center' }} />
  }

  if (error || !group) {
    return (
      <Alert
        type="error"
        message="데이터셋 그룹을 불러오지 못했습니다."
        description="백엔드 연결 또는 그룹 ID를 확인하세요."
        showIcon
        style={{ marginTop: 24 }}
      />
    )
  }

  /* -- Display SDK — 그룹 용도(detection/classification/...)별 셀 렌더러 해석 -- */
  const kindDefinition = resolveDatasetKind(group)
  const cellContext: DatasetListCellContext = {
    editingFormatDatasetId: editingFormatId,
    editingFormatValue,
    updatingFormatDatasetId,
    validatingDatasetId,
    replacingMetaFileDatasetId,
    onStartEditFormat: startEditingFormat,
    onChangeEditingFormat: setEditingFormatValue,
    onConfirmFormatChange: confirmFormatChange,
    onCancelEditFormat: () => setEditingFormatId(null),
    onValidateDataset: handleValidateDataset,
    onOpenMetaFileBrowser: (datasetId: string) => {
      setMetaFileTargetDatasetId(datasetId)
      setMetaFileBrowserOpen(true)
    },
  }

  /* -- 데이터셋 테이블 컬럼 -- 너비는 resize 훅 state에서 읽는다 */
  const datasetColumns = [
    {
      title: 'Split',
      dataIndex: 'split',
      key: 'split',
      width: datasetColumnWidths.split,
      onHeaderCell: buildDatasetHeaderCellProps('split'),
      render: (split: string) => (
        <Tag color={SPLIT_COLOR[split] ?? 'default'}>{split}</Tag>
      ),
    },
    {
      title: '버전',
      dataIndex: 'version',
      key: 'version',
      width: datasetColumnWidths.version,
      onHeaderCell: buildDatasetHeaderCellProps('version'),
    },
    {
      title: '상태',
      dataIndex: 'status',
      key: 'status',
      width: datasetColumnWidths.status,
      onHeaderCell: buildDatasetHeaderCellProps('status'),
      render: (status: string) => (
        <Badge status={STATUS_BADGE[status] as any} text={status} />
      ),
    },
    {
      title: '이미지 수',
      dataIndex: 'image_count',
      key: 'image_count',
      width: datasetColumnWidths.image_count,
      onHeaderCell: buildDatasetHeaderCellProps('image_count'),
      align: 'right' as const,
      render: (count: number | null) =>
        count != null ? count.toLocaleString() : <Text type="secondary">-</Text>,
    },
    {
      title: '클래스 정보',
      key: 'class_info',
      width: datasetColumnWidths.class_info,
      onHeaderCell: buildDatasetHeaderCellProps('class_info'),
      render: (_: unknown, record: DatasetSummary) =>
        kindDefinition.renderClassInfoCell(record, group, cellContext),
    },
    {
      title: '포맷',
      key: 'annotation_format',
      width: datasetColumnWidths.annotation_format,
      onHeaderCell: buildDatasetHeaderCellProps('annotation_format'),
      render: (_: unknown, record: DatasetSummary) =>
        kindDefinition.renderFormatCell(record, group, cellContext),
    },
    {
      title: '저장 경로',
      dataIndex: 'storage_uri',
      key: 'storage_uri',
      width: datasetColumnWidths.storage_uri,
      onHeaderCell: buildDatasetHeaderCellProps('storage_uri'),
      ellipsis: true,
      render: (uri: string) => (
        <Text copyable style={{ fontSize: 12 }}>{uri}</Text>
      ),
    },
    {
      title: '등록일',
      dataIndex: 'created_at',
      key: 'created_at',
      width: datasetColumnWidths.created_at,
      onHeaderCell: buildDatasetHeaderCellProps('created_at'),
      render: (v: string) => dayjs(v).format('YYYY-MM-DD'),
    },
    {
      title: '',
      key: 'action',
      width: datasetColumnWidths.action,
      onHeaderCell: buildDatasetHeaderCellProps('action'),
      render: (_: unknown, record: DatasetSummary) => (
        <Space size={0}>
          {kindDefinition.renderMetaFileAction(record, group, cellContext)}
          <Popconfirm
            title="데이터셋 삭제"
            description={`${record.split}/${record.version}을 삭제하시겠습니까?`}
            onConfirm={() => handleDeleteDataset(record)}
            okText="삭제"
            cancelText="취소"
            okButtonProps={{ danger: true }}
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingDatasetId === record.id}
              onClick={(e) => e.stopPropagation()}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Space style={{ marginBottom: 16 }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/datasets')}
          >
            목록으로
          </Button>
        </Space>
        <Popconfirm
          title="그룹 삭제"
          description={
            <>
              <strong>'{group.name}'</strong> 그룹과 하위 데이터셋
              {group.datasets.length > 0 && ` ${group.datasets.length}건`}을
              모두 삭제하시겠습니까?
            </>
          }
          onConfirm={handleDeleteGroup}
          okText="삭제"
          cancelText="취소"
          okButtonProps={{ danger: true }}
        >
          <Button
            danger
            icon={<DeleteOutlined />}
            loading={deletingGroup}
          >
            그룹 삭제
          </Button>
        </Popconfirm>
      </div>

      <Title level={3} style={{ marginBottom: 4 }}>{group.name}</Title>
      {group.description && (
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {group.description}
        </Text>
      )}

      {/* 그룹 기본 정보 */}
      <Descriptions
        bordered
        size="small"
        column={{ xs: 1, sm: 2, md: 3 }}
        style={{ marginBottom: 24 }}
      >
        <Descriptions.Item label="데이터셋 유형">
          <Tag>{group.dataset_type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="어노테이션 포맷">
          <Tag color={FORMAT_COLOR[group.annotation_format] ?? 'default'}>
            {group.annotation_format}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="모달리티">
          {group.modality}
        </Descriptions.Item>
        <Descriptions.Item label="사용 목적">
          <Space wrap size={4}>
            {(group.task_types ?? []).map(t => (
              <Tag key={t} color="purple">{t}</Tag>
            ))}
            {!group.task_types?.length && <Text type="secondary">-</Text>}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="출처">
          {group.source_origin || <Text type="secondary">-</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="등록일">
          {dayjs(group.created_at).format('YYYY-MM-DD HH:mm')}
        </Descriptions.Item>
      </Descriptions>

      {/* 소속 데이터셋 목록 */}
      <Title level={5} style={{ marginBottom: 12 }}>
        데이터셋 목록 ({group.datasets.length}건)
      </Title>
      {/* 컬럼 너비는 헤더 우측 경계 드래그로 조정 가능(useResizableColumnWidths). */}
      <Table<DatasetSummary>
        dataSource={[...group.datasets].sort((a, b) => {
          const splitDiff = (SPLIT_ORDER[a.split] ?? 99) - (SPLIT_ORDER[b.split] ?? 99)
          if (splitDiff !== 0) return splitDiff
          return b.version.localeCompare(a.version)
        })}
        columns={datasetColumns}
        components={resizableTableComponents}
        rowKey="id"
        pagination={false}
        size="middle"
        // 창이 좁아 컬럼 합보다 컨테이너가 작을 때 테이블이 밖으로 넘치지 않도록 가로 스크롤 허용.
        scroll={{ x: 'max-content' }}
        onRow={(record) => ({
          onClick: (e: React.MouseEvent) => {
            // 버튼, 링크, Popover 등 인터랙티브 요소 클릭 시 행 네비게이션 무시
            const target = e.target as HTMLElement
            if (target.closest('button, a, .ant-popover, .ant-select, .ant-btn')) return
            if (record.status === 'READY') {
              navigate(`/datasets/${groupId}/${record.id}`)
            }
          },
          style: { cursor: record.status === 'READY' ? 'pointer' : 'default' },
        })}
        locale={{
          emptyText: <Text type="secondary">등록된 데이터셋이 없습니다.</Text>,
        }}
      />

      {/* 메타 파일 교체용 파일 브라우저 */}
      <ServerFileBrowser
        open={metaFileBrowserOpen}
        onClose={() => {
          setMetaFileBrowserOpen(false)
          setMetaFileTargetDatasetId(null)
        }}
        onSelect={handleReplaceMetaFile}
        mode="file"
        title="어노테이션 메타 파일 선택 (예: data.yaml)"
      />
    </div>
  )
}
