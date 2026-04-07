/**
 * 샘플 뷰어 탭
 *
 * 좌측: 이미지 파일명 리스트 (페이지네이션)
 * 메인: 선택된 이미지 + bbox 오버레이 (canvas)
 * 하단: 선택된 이미지의 annotation 테이블
 */
import { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import {
  List,
  Spin,
  Empty,
  Tag,
  Table,
  Typography,
  Pagination,
  Input,
  Checkbox,
  Button,
} from 'antd'
import { FileImageOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../../api/dataset'
import type { SampleImageItem, SampleAnnotationItem } from '../../types/dataset'

const { Text } = Typography

/**
 * 카테고리별 색상을 순환 할당하기 위한 팔레트.
 * detection 시각화에서 일반적으로 사용하는 고대비 색상 10가지.
 */
const CATEGORY_COLORS = [
  '#1677ff', '#52c41a', '#fa541c', '#722ed1', '#faad14',
  '#13c2c2', '#eb2f96', '#2f54eb', '#a0d911', '#fa8c16',
]

function getCategoryColor(categoryId: number): string {
  return CATEGORY_COLORS[categoryId % CATEGORY_COLORS.length]
}

interface Props {
  datasetId: string
}

export default function SampleViewerTab({ datasetId }: Props) {
  const [currentPage, setCurrentPage] = useState(1)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [searchText, setSearchText] = useState('')
  const pageSize = 20

  const { data, isLoading } = useQuery({
    queryKey: ['dataset-samples', datasetId, currentPage, pageSize],
    queryFn: () =>
      datasetsApi.samples(datasetId, { page: currentPage, page_size: pageSize }).then(r => r.data),
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

  // 페이지 변경 시 선택 초기화
  useEffect(() => {
    setSelectedIndex(0)
  }, [currentPage])

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const categories = data?.categories ?? []

  // 클래스 필터 상태 — 카테고리 데이터 로드 시 전부 활성화로 초기화
  const [enabledCategoryIds, setEnabledCategoryIds] = useState<Set<number>>(new Set())
  const [categoryInitialized, setCategoryInitialized] = useState(false)

  useEffect(() => {
    if (categories.length > 0 && !categoryInitialized) {
      setEnabledCategoryIds(new Set(categories.map(cat => cat.id)))
      setCategoryInitialized(true)
    }
  }, [categories, categoryInitialized])

  // 검색 필터 (파일명 기준)
  const filteredItems = searchText
    ? items.filter(item => item.file_name.toLowerCase().includes(searchText.toLowerCase()))
    : items

  const selectedImage = filteredItems[selectedIndex] ?? null

  // 선택된 이미지의 annotation을 클래스 필터 적용하여 반환
  const filteredAnnotations = useMemo(() => {
    if (!selectedImage) return []
    return selectedImage.annotations.filter(
      ann => enabledCategoryIds.has(ann.category_id)
    )
  }, [selectedImage, enabledCategoryIds])

  const handleToggleCategory = (categoryId: number, checked: boolean) => {
    setEnabledCategoryIds(prev => {
      const next = new Set(prev)
      if (checked) {
        next.add(categoryId)
      } else {
        next.delete(categoryId)
      }
      return next
    })
  }

  const handleSelectAllCategories = () => {
    setEnabledCategoryIds(new Set(categories.map(cat => cat.id)))
  }

  const handleDeselectAllCategories = () => {
    setEnabledCategoryIds(new Set())
  }

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

  if (total === 0) {
    return <Empty description="이미지가 없거나 annotation 파일을 파싱할 수 없습니다." />
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 220px)' }}>
      {/* 좌측: 이미지 리스트 — 브라우저 높이에 맞춰 스크롤 */}
      <div style={{ width: 220, flexShrink: 0, display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder="파일명 검색"
          size="small"
          value={searchText}
          onChange={e => { setSearchText(e.target.value); setSelectedIndex(0) }}
          allowClear
          style={{ marginBottom: 8 }}
        />
        <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 6 }}>
          <List
            size="small"
            dataSource={filteredItems}
            renderItem={(item, index) => (
              <List.Item
                onClick={() => setSelectedIndex(index)}
                style={{
                  cursor: 'pointer',
                  padding: '6px 12px',
                  background: index === selectedIndex ? '#e6f4ff' : undefined,
                  borderLeft: index === selectedIndex ? '3px solid #1677ff' : '3px solid transparent',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', fontSize: 12 }}>
                  <Text ellipsis style={{ flex: 1, fontSize: 12 }}>
                    <FileImageOutlined style={{ marginRight: 4 }} />
                    {item.file_name}
                  </Text>
                  <Tag
                    color={item.annotation_count > 0 ? 'blue' : 'default'}
                    style={{ marginLeft: 4, fontSize: 11 }}
                  >
                    {item.annotation_count}
                  </Tag>
                </div>
              </List.Item>
            )}
          />
        </div>
        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <Pagination
            size="small"
            current={currentPage}
            total={total}
            pageSize={pageSize}
            onChange={page => setCurrentPage(page)}
            showSizeChanger={false}
            simple
          />
        </div>

        {/* 클래스 필터 */}
        {categories.length > 0 && (
          <div style={{ marginTop: 12, border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <Text strong style={{ fontSize: 12 }}>클래스 필터</Text>
              <div style={{ display: 'flex', gap: 4 }}>
                <Button size="small" type="link" style={{ fontSize: 11, padding: 0 }} onClick={handleSelectAllCategories}>전체</Button>
                <Button size="small" type="link" style={{ fontSize: 11, padding: 0 }} onClick={handleDeselectAllCategories}>해제</Button>
              </div>
            </div>
            <div style={{ maxHeight: 160, overflowY: 'auto' }}>
              {categories.map(cat => (
                <div key={cat.id} style={{ marginBottom: 2 }}>
                  <Checkbox
                    checked={enabledCategoryIds.has(cat.id)}
                    onChange={e => handleToggleCategory(cat.id, e.target.checked)}
                    style={{ fontSize: 11 }}
                  >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                      <span style={{
                        display: 'inline-block',
                        width: 8,
                        height: 8,
                        borderRadius: 2,
                        background: getCategoryColor(cat.id),
                      }} />
                      {cat.name}
                    </span>
                  </Checkbox>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 메인: 이미지 프리뷰 + annotation 정보 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowY: 'auto' }}>
        {selectedImage ? (
          <>
            <ImageWithBboxOverlay
              image={selectedImage}
              filteredAnnotations={filteredAnnotations}
              getCategoryColor={getCategoryColor}
            />
            <AnnotationTable
              annotations={filteredAnnotations}
              getCategoryColor={getCategoryColor}
            />
          </>
        ) : (
          <Empty description="이미지를 선택하세요" />
        )}
      </div>
    </div>
  )
}


/**
 * 이미지 위에 bbox를 canvas로 오버레이하는 컴포넌트.
 * 이미지 로드 후 자연 크기 비율을 유지하며 컨테이너에 맞게 스케일링.
 */
function ImageWithBboxOverlay({
  image,
  filteredAnnotations,
  getCategoryColor,
}: {
  image: SampleImageItem
  filteredAnnotations: SampleAnnotationItem[]
  getCategoryColor: (id: number) => string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const [imageLoaded, setImageLoaded] = useState(false)
  const [imageError, setImageError] = useState(false)

  const drawBboxOverlay = useCallback(() => {
    const canvas = canvasRef.current
    const img = imgRef.current
    const container = containerRef.current
    if (!canvas || !img || !container || !imageLoaded) return

    const containerWidth = container.clientWidth
    const maxHeight = 400

    // 이미지 자연 크기 기준 스케일 계산
    const naturalWidth = img.naturalWidth
    const naturalHeight = img.naturalHeight
    if (naturalWidth === 0 || naturalHeight === 0) return

    const scaleByWidth = containerWidth / naturalWidth
    const scaleByHeight = maxHeight / naturalHeight
    const scale = Math.min(scaleByWidth, scaleByHeight, 1) // 원본보다 커지지 않음

    const displayWidth = Math.round(naturalWidth * scale)
    const displayHeight = Math.round(naturalHeight * scale)

    canvas.width = displayWidth
    canvas.height = displayHeight
    img.style.width = `${displayWidth}px`
    img.style.height = `${displayHeight}px`

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, displayWidth, displayHeight)

    // 클래스 필터가 적용된 annotation만 그린다
    for (const ann of filteredAnnotations) {
      if (!ann.bbox || ann.bbox.length !== 4) continue

      const [bboxX, bboxY, bboxW, bboxH] = ann.bbox
      const drawX = bboxX * scale
      const drawY = bboxY * scale
      const drawW = bboxW * scale
      const drawH = bboxH * scale

      const color = getCategoryColor(ann.category_id)

      // bbox 사각형
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.strokeRect(drawX, drawY, drawW, drawH)

      // 라벨 배경
      const labelText = ann.category_name
      ctx.font = '12px sans-serif'
      const textMetrics = ctx.measureText(labelText)
      const labelHeight = 16
      const labelWidth = textMetrics.width + 6
      const labelY = drawY - labelHeight > 0 ? drawY - labelHeight : drawY

      ctx.fillStyle = color
      ctx.fillRect(drawX, labelY, labelWidth, labelHeight)

      // 라벨 텍스트
      ctx.fillStyle = '#fff'
      ctx.fillText(labelText, drawX + 3, labelY + 12)
    }
  }, [filteredAnnotations, imageLoaded, getCategoryColor])

  useEffect(() => {
    setImageLoaded(false)
    setImageError(false)
  }, [image.image_url])

  useEffect(() => {
    if (imageLoaded) {
      drawBboxOverlay()
    }
  }, [imageLoaded, drawBboxOverlay])

  // 윈도우 리사이즈 시 다시 그리기
  useEffect(() => {
    const handleResize = () => drawBboxOverlay()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [drawBboxOverlay])

  return (
    <div>
      {/* 이미지 정보 헤더 */}
      <div style={{ marginBottom: 8, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Text strong>{image.file_name}</Text>
        {image.width && image.height && (
          <Text type="secondary">{image.width} x {image.height}</Text>
        )}
        <Tag color="blue">{image.annotation_count}개 annotation</Tag>
      </div>

      {/* 이미지 + canvas 오버레이 */}
      <div
        ref={containerRef}
        style={{
          position: 'relative',
          display: 'inline-block',
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          overflow: 'hidden',
          minHeight: 200,
        }}
      >
        {imageError ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <Text type="secondary">이미지를 로드할 수 없습니다: {image.file_name}</Text>
          </div>
        ) : (
          <>
            <img
              ref={imgRef}
              src={image.image_url}
              alt={image.file_name}
              onLoad={() => setImageLoaded(true)}
              onError={() => setImageError(true)}
              style={{
                display: imageLoaded ? 'block' : 'none',
                maxHeight: 400,
                objectFit: 'contain',
              }}
            />
            {!imageLoaded && !imageError && (
              <Spin style={{ display: 'block', padding: 60 }} />
            )}
            <canvas
              ref={canvasRef}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                pointerEvents: 'none',
              }}
            />
          </>
        )}
      </div>
    </div>
  )
}


/**
 * 선택된 이미지의 annotation 목록 테이블.
 */
function AnnotationTable({
  annotations,
  getCategoryColor,
}: {
  annotations: SampleAnnotationItem[]
  getCategoryColor: (id: number) => string
}) {
  if (annotations.length === 0) {
    return (
      <Text type="secondary" style={{ marginTop: 12 }}>
        이 이미지에 annotation이 없습니다 (negative sample).
      </Text>
    )
  }

  const columns = [
    {
      title: '#',
      key: 'index',
      width: 40,
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      title: '클래스',
      dataIndex: 'category_name',
      key: 'category_name',
      width: 120,
      render: (name: string, record: SampleAnnotationItem) => (
        <Tag color={getCategoryColor(record.category_id)}>{name}</Tag>
      ),
    },
    {
      title: 'bbox [x, y, w, h]',
      dataIndex: 'bbox',
      key: 'bbox',
      render: (bbox: number[] | null) =>
        bbox
          ? `[${bbox.map(v => Math.round(v)).join(', ')}]`
          : '-',
    },
    {
      title: '면적 (px)',
      dataIndex: 'area',
      key: 'area',
      width: 100,
      align: 'right' as const,
      render: (area: number | null) =>
        area != null ? Math.round(area).toLocaleString() : '-',
    },
  ]

  return (
    <Table
      dataSource={annotations}
      columns={columns}
      rowKey={(_, index) => String(index)}
      size="small"
      pagination={false}
      style={{ marginTop: 12 }}
      scroll={{ y: 200 }}
    />
  )
}
