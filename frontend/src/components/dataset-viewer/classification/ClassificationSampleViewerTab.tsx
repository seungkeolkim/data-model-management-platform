/**
 * Classification 샘플 뷰어 탭.
 *
 * detection 탭과 기본 레이아웃은 같다 — 좌측 이미지 리스트(페이지네이션/검색) + 메인 이미지 미리보기.
 * 다른 점:
 *   - bbox overlay가 없다.
 *   - 대신 이미지 아래에 head별 class 라벨을 Tag로 나열.
 *   - 좌측 필터는 head별 체크박스 그룹. 같은 head 내 여러 class는 OR,
 *     서로 다른 head 간에는 AND로 결합된다. 필터는 서버 측에서 적용된다.
 */
import { useMemo, useState, useEffect, useRef, type CSSProperties } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Input,
  List,
  Pagination,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { FileImageOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../../../api/dataset'
import type {
  ClassificationSampleHeadInfo,
  ClassificationSampleImageItem,
} from '../../../types/dataset'

const { Text } = Typography

interface Props {
  datasetId: string
}

/** head별로 label에 실제 class가 하나라도 붙어 있는지 체크. */
function hasAnyLabel(
  labels: Record<string, string[]> | null | undefined,
  headName: string,
): boolean {
  return !!labels && (labels[headName]?.length ?? 0) > 0
}

export default function ClassificationSampleViewerTab({ datasetId }: Props) {
  const [currentPage, setCurrentPage] = useState(1)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [searchText, setSearchText] = useState('')
  // 필터: head별 선택된 class 목록. 같은 head 내 OR, 서로 다른 head 간 AND.
  // 서버에서 적용되므로 페이지네이션 전에 반영된다.
  const [headClassFilter, setHeadClassFilter] = useState<Record<string, string[]>>({})
  const pageSize = 20

  // FastAPI list[str] Query 직렬화 형식: "head:class" 반복
  const headFilterParams = useMemo(() => {
    const params: string[] = []
    for (const [headName, classes] of Object.entries(headClassFilter)) {
      for (const className of classes) {
        params.push(`${headName}:${className}`)
      }
    }
    return params
  }, [headClassFilter])

  const { data, isLoading } = useQuery({
    queryKey: ['classification-samples', datasetId, currentPage, pageSize, headFilterParams],
    queryFn: () =>
      datasetsApi
        .classificationSamples(datasetId, {
          page: currentPage,
          page_size: pageSize,
          head_filter: headFilterParams,
        })
        .then(r => r.data),
  })

  const [showCacheMessage, setShowCacheMessage] = useState(false)
  useEffect(() => {
    if (!isLoading) {
      setShowCacheMessage(false)
      return
    }
    const timer = setTimeout(() => setShowCacheMessage(true), 2000)
    return () => clearTimeout(timer)
  }, [isLoading])

  // 필터 or 검색이 바뀌면 선택 인덱스 리셋
  useEffect(() => {
    setSelectedIndex(0)
  }, [currentPage, headClassFilter, searchText])

  // 필터가 바뀌면 1페이지로 이동 (서버 결과가 달라지므로)
  useEffect(() => {
    setCurrentPage(1)
  }, [headClassFilter])

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const heads = data?.heads ?? []

  // 파일명 검색만 클라이언트 측. head/class 필터는 서버에서 처리됨.
  const filteredItems = useMemo(() => {
    if (!searchText) return items
    const query = searchText.toLowerCase()
    return items.filter(item => (item.file_name || '').toLowerCase().includes(query))
  }, [items, searchText])

  const totalSelectedFilters = headFilterParams.length
  const hasAnyFilter = totalSelectedFilters > 0

  // head별 체크박스 그룹 변경 핸들러
  const handleHeadClassToggle = (headName: string, nextClasses: string[]) => {
    setHeadClassFilter(prev => {
      const next = { ...prev }
      if (nextClasses.length === 0) delete next[headName]
      else next[headName] = nextClasses
      return next
    })
  }

  const handleClearFilters = () => setHeadClassFilter({})

  const selectedImage: ClassificationSampleImageItem | null =
    filteredItems[selectedIndex] ?? null

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

  // 필터가 없는데도 결과가 0이면 진짜로 빈 데이터셋 — Empty로 대체
  if (total === 0 && !hasAnyFilter) {
    return <Empty description="manifest.jsonl을 읽을 수 없거나 이미지가 없습니다." />
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 220px)' }}>
      {/* 좌측: 이미지 리스트 + 검색 + 필터 */}
      <div style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder="파일명 검색 (현재 페이지)"
          size="small"
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          allowClear
          style={{ marginBottom: 8 }}
        />

        <HeadClassFilterPanel
          heads={heads}
          selected={headClassFilter}
          onToggleHead={handleHeadClassToggle}
          onClearAll={handleClearFilters}
          totalSelected={totalSelectedFilters}
        />

        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            marginTop: 8,
          }}
        >
          {total === 0 ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                조건에 맞는 이미지가 없습니다.
              </Text>
            </div>
          ) : null}
          <List
            size="small"
            dataSource={filteredItems}
            renderItem={(item, index) => {
              // 현재 페이지 내에서 labels가 있는 head 수를 간단 표시 (전체 head 개수 대비).
              const totalHeads = heads.length
              const labeledHeads = heads.filter(h => hasAnyLabel(item.labels, h.name)).length
              return (
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
                      color={labeledHeads === totalHeads ? 'blue' : labeledHeads === 0 ? 'default' : 'orange'}
                      style={{ marginLeft: 4, fontSize: 11 }}
                    >
                      {labeledHeads}/{totalHeads}
                    </Tag>
                  </div>
                </List.Item>
              )
            }}
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
      </div>

      {/* 메인: 이미지 + head별 class 라벨 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowY: 'auto' }}>
        {selectedImage ? (
          <ClassificationImagePreview image={selectedImage} heads={heads.map(h => h.name)} />
        ) : (
          <Empty description="이미지를 선택하세요" />
        )}
      </div>
    </div>
  )
}

/**
 * head별 체크박스 필터 패널.
 * - Collapse로 head 단위 접고 펼침 — head 수가 많아도 스크롤/공간 문제가 적다.
 * - 같은 head 안에서 고른 여러 class는 OR (서버 구현과 일치).
 * - 서로 다른 head 간에는 AND.
 */
function HeadClassFilterPanel({
  heads,
  selected,
  onToggleHead,
  onClearAll,
  totalSelected,
}: {
  heads: ClassificationSampleHeadInfo[]
  selected: Record<string, string[]>
  onToggleHead: (headName: string, nextClasses: string[]) => void
  onClearAll: () => void
  totalSelected: number
}) {
  if (heads.length === 0) return null

  // 초기에 이미 선택된 head만 펼쳐 둔다. 나머지는 접힘.
  const defaultOpenKeys = heads
    .filter(head => (selected[head.name]?.length ?? 0) > 0)
    .map(head => head.name)

  return (
    <div style={{ marginBottom: 8 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 4,
          fontSize: 12,
        }}
      >
        <Text strong style={{ fontSize: 12 }}>
          Head / Class 필터
        </Text>
        <Space size={6}>
          {totalSelected > 0 && (
            <Tag color="blue" style={{ fontSize: 11, margin: 0 }}>
              {totalSelected} 선택
            </Tag>
          )}
          <Button
            type="link"
            size="small"
            disabled={totalSelected === 0}
            onClick={onClearAll}
            style={{ padding: 0, fontSize: 12 }}
          >
            초기화
          </Button>
        </Space>
      </div>
      <Collapse
        size="small"
        // key를 defaultOpenKeys의 join으로 만들어 selected가 바뀌면 강제 재마운트 없이
        // defaultActiveKey 효과만 살린다. 사용자가 수동으로 펼친 상태는 유지됨.
        defaultActiveKey={defaultOpenKeys}
        items={heads.map(head => {
          const selectedClasses = selected[head.name] ?? []
          return {
            key: head.name,
            label: (
              <span style={{ fontSize: 12 }}>
                {head.name}
                {head.multi_label && (
                  <Tag color="purple" style={{ marginLeft: 6, fontSize: 10 }}>
                    multi
                  </Tag>
                )}
                {selectedClasses.length > 0 && (
                  <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>
                    {selectedClasses.length}/{head.classes.length}
                  </Tag>
                )}
              </span>
            ),
            children: (
              <Checkbox.Group
                value={selectedClasses}
                onChange={next => onToggleHead(head.name, next as string[])}
                style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
                options={head.classes.map(className => ({
                  value: className,
                  label: <span style={{ fontSize: 12 }}>{className}</span>,
                }))}
              />
            ),
          }
        })}
      />
    </div>
  )
}

/**
 * 선택된 이미지 + head별 라벨 카드.
 * bbox overlay가 없으므로 단순 <img> 로 표시하고 밑에 head → class Tag 목록을 배치.
 */
function ClassificationImagePreview({
  image,
  heads,
}: {
  image: ClassificationSampleImageItem
  heads: string[]
}) {
  return (
    <div>
      <div style={{ marginBottom: 8, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Text strong>{image.file_name}</Text>
        {image.width && image.height && (
          <Text type="secondary">
            {image.width} x {image.height}
          </Text>
        )}
        <Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 11 }}>
          sha: {image.sha.slice(0, 10)}…
        </Text>
      </div>

      <ClassificationImageCanvas image={image} />

      <Card size="small" title="Head별 Class 라벨" style={{ marginTop: 12 }}>
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {heads.map(headName => {
            const classes = image.labels?.[headName] ?? []
            return (
              <div
                key={headName}
                style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}
              >
                <Text strong style={{ minWidth: 120 }}>{headName}</Text>
                {classes.length > 0 ? (
                  classes.map(className => (
                    <Tag key={className} color="blue">{className}</Tag>
                  ))
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>라벨 없음</Text>
                )}
              </div>
            )
          })}
        </Space>
      </Card>
    </div>
  )
}

/**
 * 이미지 캔버스. 캔버스 한 변은 min(프레임 폭, 640)px.
 *   - 이미지가 캔버스보다 작으면 비율을 유지하며 캔버스에 딱 맞게 확장
 *   - 이미지가 캔버스보다 크면 원본 크기 그대로 표시(축소하지 않음 — 스크롤)
 */
function ClassificationImageCanvas({ image }: { image: ClassificationSampleImageItem }) {
  const MAX_CANVAS_SIZE = 640
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [canvasSize, setCanvasSize] = useState(MAX_CANVAS_SIZE)

  useEffect(() => {
    if (!wrapperRef.current) return
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        // 상자 padding 8×2 감안
        const available = Math.max(1, Math.floor(entry.contentRect.width) - 16)
        setCanvasSize(Math.min(MAX_CANVAS_SIZE, available))
      }
    })
    observer.observe(wrapperRef.current)
    return () => observer.disconnect()
  }, [])

  const imageStyle: CSSProperties = { display: 'block' }
  if (image.width && image.height) {
    const longerEdge = Math.max(image.width, image.height)
    if (longerEdge < canvasSize) {
      // 작은 이미지: 비율 유지해서 캔버스 한 변에 딱 맞게 확장
      const scale = canvasSize / longerEdge
      imageStyle.width = Math.round(image.width * scale)
      imageStyle.height = Math.round(image.height * scale)
    } else {
      // 캔버스보다 큰 원본은 그대로 노출
      imageStyle.width = image.width
      imageStyle.height = image.height
    }
  } else {
    // 크기 정보가 없으면 fallback: 캔버스 변에 맞추고 비율은 브라우저가 유지
    imageStyle.maxWidth = canvasSize
    imageStyle.maxHeight = canvasSize
  }

  return (
    <div ref={wrapperRef} style={{ width: '100%' }}>
      <div
        style={{
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          padding: 8,
          display: 'inline-block',
          maxWidth: '100%',
          overflow: 'auto',
        }}
      >
        <img src={image.image_url} alt={image.file_name} style={imageStyle} />
      </div>
    </div>
  )
}
