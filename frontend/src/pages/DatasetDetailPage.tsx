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
  Popover,
  Popconfirm,
  Select,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  InfoCircleOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  FileOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { datasetGroupsApi, datasetsApi } from '../api/dataset'
import ServerFileBrowser from '../components/common/ServerFileBrowser'
import type { AnnotationFormat, DatasetSummary } from '../types/dataset'

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
  CLS_FOLDER: 'geekblue',
  CUSTOM: 'purple',
  NONE: 'default',
}

/**
 * 클래스 매핑 Popover 내용 컴포넌트.
 * ID → 클래스명 테이블을 간결하게 보여준다.
 */
function ClassMappingContent({ classMapping }: { classMapping: Record<string, string> }) {
  const entries = Object.entries(classMapping).sort(
    ([keyA], [keyB]) => Number(keyA) - Number(keyB)
  )

  return (
    <div style={{ maxHeight: 300, overflowY: 'auto', minWidth: 180 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #f0f0f0' }}>
            <th style={{ textAlign: 'left', padding: '4px 12px 4px 0', color: '#888' }}>ID</th>
            <th style={{ textAlign: 'left', padding: '4px 0', color: '#888' }}>클래스명</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([classId, className]) => (
            <tr key={classId} style={{ borderBottom: '1px solid #fafafa' }}>
              <td style={{ padding: '3px 12px 3px 0', fontFamily: 'monospace' }}>{classId}</td>
              <td style={{ padding: '3px 0' }}>{className}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
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

  /* -- 데이터셋 테이블 컬럼 -- */
  const datasetColumns = [
    {
      title: 'Split',
      dataIndex: 'split',
      key: 'split',
      width: 100,
      render: (split: string) => (
        <Tag color={SPLIT_COLOR[split] ?? 'default'}>{split}</Tag>
      ),
    },
    {
      title: '버전',
      dataIndex: 'version',
      key: 'version',
      width: 100,
    },
    {
      title: '상태',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: string) => (
        <Badge status={STATUS_BADGE[status] as any} text={status} />
      ),
    },
    {
      title: '이미지 수',
      dataIndex: 'image_count',
      key: 'image_count',
      width: 110,
      align: 'right' as const,
      render: (count: number | null) =>
        count != null ? count.toLocaleString() : <Text type="secondary">-</Text>,
    },
    {
      title: '클래스 정보',
      key: 'class_info',
      width: 150,
      render: (_: unknown, record: DatasetSummary) => {
        const classInfo = record.metadata?.class_info
        const classCount = record.class_count ?? classInfo?.class_count
        const classMapping = classInfo?.class_mapping

        // 클래스 정보가 있으면 — 개수 + 상세보기 Popover
        if (classCount != null && classMapping) {
          return (
            <Space size={4}>
              <Text>{classCount}개</Text>
              <Popover
                title={`클래스 매핑 (${classCount}개)`}
                content={<ClassMappingContent classMapping={classMapping} />}
                trigger="click"
                placement="left"
              >
                <Button
                  type="link"
                  size="small"
                  icon={<InfoCircleOutlined />}
                  style={{ padding: 0 }}
                >
                  상세보기
                </Button>
              </Popover>
            </Space>
          )
        }

        // 클래스 수만 있고 매핑은 없는 경우
        if (classCount != null) {
          return <Text>{classCount}개</Text>
        }

        // 클래스 정보 없음 — 검증 버튼 표시
        const annotationFormat = record.annotation_format || group.annotation_format
        const isValidatable = annotationFormat && annotationFormat !== 'NONE'

        if (isValidatable) {
          return (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              loading={validatingDatasetId === record.id}
              onClick={(e) => {
                e.stopPropagation()
                handleValidateDataset(record)
              }}
            >
              검증
            </Button>
          )
        }

        return <Text type="secondary">-</Text>
      },
    },
    {
      title: '포맷',
      key: 'annotation_format',
      width: 200,
      render: (_: unknown, record: DatasetSummary) => {
        const currentFormat = record.annotation_format ?? 'NONE'
        const isEditing = editingFormatId === record.id

        if (isEditing) {
          return (
            <Space size={4} onClick={(e) => e.stopPropagation()}>
              <Select
                size="small"
                value={editingFormatValue}
                onChange={(value: AnnotationFormat) => setEditingFormatValue(value)}
                style={{ width: 110 }}
                options={[
                  { value: 'COCO', label: 'COCO' },
                  { value: 'YOLO', label: 'YOLO' },
                  { value: 'ATTR_JSON', label: 'ATTR_JSON' },
                  { value: 'CLS_FOLDER', label: 'CLS_FOLDER' },
                  { value: 'CUSTOM', label: 'CUSTOM' },
                  { value: 'NONE', label: 'NONE' },
                ]}
              />
              <Button
                type="primary"
                size="small"
                loading={updatingFormatDatasetId === record.id}
                onClick={() => confirmFormatChange(record.id)}
              >
                확인
              </Button>
              <Button
                size="small"
                onClick={() => setEditingFormatId(null)}
              >
                취소
              </Button>
            </Space>
          )
        }

        return (
          <Space size={4}>
            <Tag color={FORMAT_COLOR[currentFormat] ?? 'default'}>{currentFormat}</Tag>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={(e) => { e.stopPropagation(); startEditingFormat(record) }}
            >
              변경
            </Button>
          </Space>
        )
      },
    },
    {
      title: '저장 경로',
      dataIndex: 'storage_uri',
      key: 'storage_uri',
      ellipsis: true,
      render: (uri: string) => (
        <Text copyable style={{ fontSize: 12 }}>{uri}</Text>
      ),
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
      render: (_: unknown, record: DatasetSummary) => (
        <Space size={0}>
          <Button
            type="text"
            size="small"
            icon={<FileOutlined />}
            loading={replacingMetaFileDatasetId === record.id}
            onClick={(e) => {
              e.stopPropagation()
              setMetaFileTargetDatasetId(record.id)
              setMetaFileBrowserOpen(true)
            }}
            title={record.annotation_meta_file
              ? `메타 파일 교체 (현재: ${record.annotation_meta_file})`
              : '메타 파일 추가'}
            style={record.annotation_meta_file ? { color: '#1677ff' } : undefined}
          />
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
      <Table<DatasetSummary>
        dataSource={[...group.datasets].sort((a, b) => {
          const splitDiff = (SPLIT_ORDER[a.split] ?? 99) - (SPLIT_ORDER[b.split] ?? 99)
          if (splitDiff !== 0) return splitDiff
          return b.version.localeCompare(a.version)
        })}
        columns={datasetColumns}
        rowKey="id"
        pagination={false}
        size="middle"
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
