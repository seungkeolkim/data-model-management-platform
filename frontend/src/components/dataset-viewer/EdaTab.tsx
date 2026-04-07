/**
 * EDA 탭
 *
 * 자동 분석 결과를 간결하게 표시:
 *   - 요약 통계 카드 (이미지수, annotation수, 클래스수, negative 이미지)
 *   - 클래스별 annotation 수 분포 (가로 바 차트, CSS 기반)
 *   - bbox 면적 분포 (가로 바 차트)
 *   - 이미지 해상도 범위
 */
import { useState, useEffect } from 'react'
import {
  Spin,
  Empty,
  Card,
  Statistic,
  Table,
  Tag,
  Typography,
  Progress,
} from 'antd'
import {
  PictureOutlined,
  TagsOutlined,
  AppstoreOutlined,
  EyeInvisibleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../../api/dataset'
import type { ClassDistributionItem, BboxSizeDistributionItem } from '../../types/dataset'

const { Text, Title } = Typography

interface Props {
  datasetId: string
}

export default function EdaTab({ datasetId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['dataset-eda', datasetId],
    queryFn: () => datasetsApi.eda(datasetId).then(r => r.data),
  })

  // 로딩이 2초 이상 지속되면 캐시 생성 중 안내 메시지 표시
  const [showCacheMessage, setShowCacheMessage] = useState(false)
  useEffect(() => {
    if (!isLoading) {
      setShowCacheMessage(false)
      return
    }
    const timer = setTimeout(() => setShowCacheMessage(true), 2000)
    return () => clearTimeout(timer)
  }, [isLoading])

  if (isLoading) {
    return (
      <div style={{ marginTop: 60, textAlign: 'center' }}>
        <Spin />
        {showCacheMessage && (
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">
              인덱스 캐시를 생성하고 있습니다. 데이터 규모에 따라 시간이 걸릴 수 있습니다.
            </Text>
          </div>
        )}
      </div>
    )
  }

  if (!data) {
    return <Empty description="EDA 데이터를 불러올 수 없습니다." />
  }

  const maxAnnotationCount = Math.max(
    ...data.class_distribution.map(c => c.annotation_count),
    1,
  )
  const maxBboxCount = Math.max(
    ...data.bbox_area_distribution.map(b => b.count),
    1,
  )

  return (
    <div>
      {/* 요약 통계 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 24 }}>
        <Card size="small">
          <Statistic
            title="전체 이미지"
            value={data.total_images}
            prefix={<PictureOutlined />}
          />
        </Card>
        <Card size="small">
          <Statistic
            title="전체 Annotation"
            value={data.total_annotations}
            prefix={<TagsOutlined />}
          />
        </Card>
        <Card size="small">
          <Statistic
            title="클래스 수"
            value={data.total_classes}
            prefix={<AppstoreOutlined />}
          />
        </Card>
        <Card size="small">
          <Statistic
            title="Negative 이미지"
            value={data.images_without_annotations}
            prefix={<EyeInvisibleOutlined />}
            valueStyle={data.images_without_annotations > 0 ? { color: '#faad14' } : undefined}
          />
        </Card>
        {data.image_width_min != null && data.image_width_max != null && (
          <Card size="small">
            <Statistic
              title="해상도 (W)"
              value={`${data.image_width_min} ~ ${data.image_width_max}`}
              valueStyle={{ fontSize: 16 }}
            />
          </Card>
        )}
        {data.image_height_min != null && data.image_height_max != null && (
          <Card size="small">
            <Statistic
              title="해상도 (H)"
              value={`${data.image_height_min} ~ ${data.image_height_max}`}
              valueStyle={{ fontSize: 16 }}
            />
          </Card>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        {/* 클래스별 분포 */}
        <Card
          title="클래스별 Annotation 분포"
          size="small"
          style={{ maxHeight: 500, overflow: 'auto' }}
        >
          {data.class_distribution.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="annotation 없음" />
          ) : (
            <div>
              {data.class_distribution.map(item => (
                <ClassDistributionBar
                  key={item.category_id}
                  item={item}
                  maxCount={maxAnnotationCount}
                />
              ))}
            </div>
          )}
        </Card>

        {/* bbox 면적 분포 */}
        <Card title="Bbox 면적 분포" size="small">
          {data.bbox_area_distribution.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="bbox 없음" />
          ) : (
            <div>
              {data.bbox_area_distribution.map(item => (
                <BboxDistributionBar
                  key={item.range_label}
                  item={item}
                  maxCount={maxBboxCount}
                />
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}


/** 클래스 분포 개별 바 */
function ClassDistributionBar({
  item,
  maxCount,
}: {
  item: ClassDistributionItem
  maxCount: number
}) {
  const percent = Math.round((item.annotation_count / maxCount) * 100)

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 2 }}>
        <Text ellipsis style={{ maxWidth: 160 }}>{item.category_name}</Text>
        <Text type="secondary">
          {item.annotation_count.toLocaleString()}개 / {item.image_count}장
        </Text>
      </div>
      <Progress
        percent={percent}
        showInfo={false}
        size="small"
        strokeColor="#1677ff"
      />
    </div>
  )
}


/** bbox 면적 분포 개별 바 */
function BboxDistributionBar({
  item,
  maxCount,
}: {
  item: BboxSizeDistributionItem
  maxCount: number
}) {
  const percent = Math.round((item.count / maxCount) * 100)

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 2 }}>
        <Text>{item.range_label}</Text>
        <Text type="secondary">{item.count.toLocaleString()}개</Text>
      </div>
      <Progress
        percent={percent}
        showInfo={false}
        size="small"
        strokeColor="#52c41a"
      />
    </div>
  )
}
