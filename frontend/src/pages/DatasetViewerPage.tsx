/**
 * 데이터셋 상세 뷰어 페이지
 *
 * 3탭 구조:
 *   1. 샘플 뷰어 — 이미지 + bbox 오버레이 + annotation 테이블
 *   2. EDA — 클래스 분포, bbox 크기 분포, 이미지 해상도 범위
 *   3. Lineage — upstream/downstream DAG 시각화
 *
 * 경로: /datasets/:groupId/:datasetId?tab=viewer|eda|lineage
 */
import { useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Typography,
  Tabs,
  Descriptions,
  Tag,
  Badge,
  Button,
  Spin,
  Alert,
  Space,
} from 'antd'
import {
  ArrowLeftOutlined,
  EyeOutlined,
  BarChartOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { datasetsApi, datasetGroupsApi } from '../api/dataset'
import SampleViewerTab from '../components/dataset-viewer/SampleViewerTab'
import EdaTab from '../components/dataset-viewer/EdaTab'
import LineageTab from '../components/dataset-viewer/LineageTab'

const { Title, Text } = Typography

const STATUS_BADGE: Record<string, string> = {
  READY: 'success',
  PENDING: 'default',
  PROCESSING: 'processing',
  ERROR: 'error',
}

const TYPE_COLOR: Record<string, string> = {
  RAW: 'default',
  SOURCE: 'blue',
  PROCESSED: 'green',
  FUSION: 'purple',
}

const FORMAT_COLOR: Record<string, string> = {
  COCO: 'green',
  YOLO: 'orange',
  NONE: 'default',
}

export default function DatasetViewerPage() {
  const { groupId, datasetId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const activeTab = searchParams.get('tab') || 'viewer'

  const { data: group, isLoading: groupLoading } = useQuery({
    queryKey: ['dataset-group', groupId],
    queryFn: () => datasetGroupsApi.get(groupId!).then(r => r.data),
    enabled: !!groupId,
  })

  const { data: dataset, isLoading: datasetLoading } = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => datasetsApi.get(datasetId!).then(r => r.data),
    enabled: !!datasetId,
  })

  const handleTabChange = (tab: string) => {
    setSearchParams({ tab })
  }

  if (groupLoading || datasetLoading) {
    return <Spin size="large" style={{ display: 'block', marginTop: 120, textAlign: 'center' }} />
  }

  if (!group || !dataset) {
    return (
      <Alert
        type="error"
        message="데이터셋을 불러오지 못했습니다."
        description="백엔드 연결 또는 ID를 확인하세요."
        showIcon
        style={{ marginTop: 24 }}
      />
    )
  }

  const annotationFormat = dataset.annotation_format || group.annotation_format

  return (
    <div>
      {/* 헤더: 뒤로가기 + 데이터셋 기본 정보 */}
      <Space style={{ marginBottom: 8 }}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(`/datasets/${groupId}`)}
        >
          그룹으로
        </Button>
      </Space>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
        <Title level={3} style={{ margin: 0 }}>{group.name}</Title>
        <Text type="secondary" style={{ fontSize: 16 }}>
          / {dataset.split} / {dataset.version}
        </Text>
        <Badge
          status={STATUS_BADGE[dataset.status] as any}
          text={dataset.status}
        />
      </div>

      <Descriptions size="small" style={{ marginBottom: 16 }} column={{ xs: 2, sm: 4, md: 6 }}>
        <Descriptions.Item label="타입">
          <Tag color={TYPE_COLOR[group.dataset_type]}>{group.dataset_type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="포맷">
          <Tag color={FORMAT_COLOR[annotationFormat] ?? 'default'}>{annotationFormat}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="이미지">
          {dataset.image_count != null ? `${dataset.image_count.toLocaleString()}장` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="클래스">
          {dataset.class_count != null ? `${dataset.class_count}개` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="등록일">
          {dayjs(dataset.created_at).format('YYYY-MM-DD')}
        </Descriptions.Item>
        <Descriptions.Item label="경로">
          <Text copyable style={{ fontSize: 12 }}>{dataset.storage_uri}</Text>
        </Descriptions.Item>
      </Descriptions>

      {/* 3탭 */}
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          {
            key: 'viewer',
            label: (
              <span><EyeOutlined /> 샘플 뷰어</span>
            ),
            children: <SampleViewerTab datasetId={datasetId!} />,
          },
          {
            key: 'eda',
            label: (
              <span><BarChartOutlined /> EDA</span>
            ),
            children: <EdaTab datasetId={datasetId!} />,
          },
          {
            key: 'lineage',
            label: (
              <span><ApartmentOutlined /> Lineage</span>
            ),
            children: <LineageTab datasetId={datasetId!} />,
          },
        ]}
      />
    </div>
  )
}
