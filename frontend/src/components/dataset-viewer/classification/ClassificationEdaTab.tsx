/**
 * Classification EDA 탭.
 *
 * 표시 구성:
 *   1. 요약 카드: 전체 이미지 수, 해상도 범위 (min/max)
 *   2. head별 class distribution — head 단위 카드 안에 가로 Progress bar
 *   3. head 쌍별 co-occurrence — 각 쌍마다 class × class 히트맵(테이블)
 *   4. multi-label head의 positive ratio — head별 그룹화된 목록 (없으면 섹션 생략)
 */
import { useState, useEffect, useMemo } from 'react'
import {
  Card,
  Empty,
  Progress,
  Spin,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import {
  BranchesOutlined,
  PictureOutlined,
  ProfileOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { datasetsApi } from '../../../api/dataset'
import type {
  ClassificationCooccurrencePair,
  ClassificationHeadDistribution,
} from '../../../types/dataset'

const { Text } = Typography

interface Props {
  datasetId: string
}

export default function ClassificationEdaTab({ datasetId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['classification-eda', datasetId],
    queryFn: () => datasetsApi.classificationEda(datasetId).then(r => r.data),
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

  // multi-label positive ratio를 head별로 그룹화
  const positiveRatioByHead = useMemo(() => {
    const grouped: Record<string, { class_name: string; positive_count: number; negative_count: number; positive_ratio: number }[]> = {}
    for (const item of data?.multi_label_positive_ratio ?? []) {
      if (!grouped[item.head_name]) grouped[item.head_name] = []
      grouped[item.head_name].push({
        class_name: item.class_name,
        positive_count: item.positive_count,
        negative_count: item.negative_count,
        positive_ratio: item.positive_ratio,
      })
    }
    return grouped
  }, [data])

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

  const hasWidthRange = data.image_width_min != null && data.image_width_max != null
  const hasHeightRange = data.image_height_min != null && data.image_height_max != null

  return (
    <div>
      {/* 1. 요약 카드 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 12,
          marginBottom: 24,
        }}
      >
        <Card size="small">
          <Statistic title="전체 이미지" value={data.total_images} prefix={<PictureOutlined />} />
        </Card>
        <Card size="small">
          <Statistic
            title="Head 수"
            value={data.per_head_distribution.length}
            prefix={<ProfileOutlined />}
          />
        </Card>
        {hasWidthRange && (
          <Card size="small">
            <Statistic
              title="해상도 (W)"
              value={`${data.image_width_min} ~ ${data.image_width_max}`}
              valueStyle={{ fontSize: 16 }}
            />
          </Card>
        )}
        {hasHeightRange && (
          <Card size="small">
            <Statistic
              title="해상도 (H)"
              value={`${data.image_height_min} ~ ${data.image_height_max}`}
              valueStyle={{ fontSize: 16 }}
            />
          </Card>
        )}
      </div>

      {/* 2. head별 class 분포 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: 16,
          marginBottom: 24,
        }}
      >
        {data.per_head_distribution.map(head => (
          <HeadDistributionCard key={head.head_name} head={head} />
        ))}
      </div>

      {/* 3. head 쌍별 co-occurrence. head가 1개면 쌍이 없어 섹션 생략. */}
      {data.head_cooccurrence.length > 0 && (
        <Card
          size="small"
          title={<span><BranchesOutlined /> Head 간 Co-occurrence</span>}
          style={{ marginBottom: 24 }}
        >
          <Text type="secondary" style={{ fontSize: 12 }}>
            두 head에 모두 라벨이 있는 이미지만 집계합니다. 숫자는 동시 발생 이미지 수이며,
            칸 배경 진하기는 행 최댓값 대비 비율입니다.
          </Text>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24, marginTop: 12 }}>
            {data.head_cooccurrence.map((pair, index) => (
              <CooccurrenceMatrix key={index} pair={pair} />
            ))}
          </div>
        </Card>
      )}

      {/* 4. multi-label positive ratio (multi_label head가 없으면 섹션 생략) */}
      {Object.keys(positiveRatioByHead).length > 0 && (
        <Card size="small" title="Multi-label Head Positive Ratio">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {Object.entries(positiveRatioByHead).map(([headName, rows]) => (
              <div key={headName}>
                <div style={{ marginBottom: 8 }}>
                  <Text strong>{headName}</Text>
                  <Tag color="purple" style={{ marginLeft: 8 }}>multi-label</Tag>
                </div>
                {rows.map(row => (
                  <div key={row.class_name} style={{ marginBottom: 8 }}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: 12,
                        marginBottom: 2,
                      }}
                    >
                      <Text>{row.class_name}</Text>
                      <Text type="secondary">
                        pos {row.positive_count.toLocaleString()} / neg {row.negative_count.toLocaleString()}
                        {' · '}
                        {(row.positive_ratio * 100).toFixed(1)}%
                      </Text>
                    </div>
                    <Progress
                      percent={Math.round(row.positive_ratio * 100)}
                      showInfo={false}
                      size="small"
                      strokeColor="#722ed1"
                    />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

/** head 1개의 class 분포 카드. 각 class를 가로 bar로 렌더. */
function HeadDistributionCard({ head }: { head: ClassificationHeadDistribution }) {
  const maxCount = Math.max(1, ...head.classes.map(c => c.image_count))

  return (
    <Card
      size="small"
      title={
        <span>
          {head.head_name}
          {head.multi_label && (
            <Tag color="purple" style={{ marginLeft: 8 }}>multi-label</Tag>
          )}
        </span>
      }
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          labeled {head.labeled_image_count.toLocaleString()}
          {head.unlabeled_image_count > 0 && (
            <> / unlabeled {head.unlabeled_image_count.toLocaleString()}</>
          )}
        </Text>
      }
    >
      {head.classes.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="class 없음" />
      ) : (
        head.classes.map(item => {
          const percent = Math.round((item.image_count / maxCount) * 100)
          return (
            <div key={item.class_name} style={{ marginBottom: 8 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: 12,
                  marginBottom: 2,
                }}
              >
                <Text ellipsis style={{ maxWidth: 200 }}>{item.class_name}</Text>
                <Text type="secondary">{item.image_count.toLocaleString()}장</Text>
              </div>
              <Progress
                percent={percent}
                showInfo={false}
                size="small"
                strokeColor="#1677ff"
              />
            </div>
          )
        })
      )}
    </Card>
  )
}

/** head_a × head_b joint_counts 히트맵 테이블. */
function CooccurrenceMatrix({ pair }: { pair: ClassificationCooccurrencePair }) {
  const rowMax = pair.joint_counts.map(row =>
    Math.max(1, ...row),
  )

  return (
    <div>
      <div style={{ marginBottom: 6 }}>
        <Text strong>{pair.head_a}</Text>
        <Text type="secondary"> × </Text>
        <Text strong>{pair.head_b}</Text>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table
          style={{
            borderCollapse: 'collapse',
            fontSize: 12,
            minWidth: 'max-content',
          }}
        >
          <thead>
            <tr>
              <th
                style={{
                  textAlign: 'left',
                  padding: '4px 8px',
                  borderBottom: '1px solid #f0f0f0',
                  color: '#888',
                }}
              >
                {pair.head_a} \ {pair.head_b}
              </th>
              {pair.classes_b.map((className, colIndex) => (
                <th
                  key={colIndex}
                  style={{
                    textAlign: 'right',
                    padding: '4px 8px',
                    borderBottom: '1px solid #f0f0f0',
                    color: '#888',
                  }}
                >
                  {className}
                  <div style={{ fontWeight: 400, fontSize: 10 }}>
                    ({pair.b_counts[colIndex].toLocaleString()})
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pair.classes_a.map((rowName, rowIndex) => (
              <tr key={rowIndex}>
                <td style={{ padding: '4px 8px', borderBottom: '1px solid #fafafa' }}>
                  {rowName}
                  <span style={{ color: '#888', marginLeft: 4 }}>
                    ({pair.a_counts[rowIndex].toLocaleString()})
                  </span>
                </td>
                {pair.classes_b.map((_className, colIndex) => {
                  const count = pair.joint_counts[rowIndex][colIndex]
                  const intensity = rowMax[rowIndex] > 0 ? count / rowMax[rowIndex] : 0
                  // 파란색 계열로 강도 표시. 0이면 흰색 배경.
                  const bg = count === 0
                    ? '#fff'
                    : `rgba(22, 119, 255, ${0.1 + intensity * 0.5})`
                  return (
                    <td
                      key={colIndex}
                      style={{
                        textAlign: 'right',
                        padding: '4px 8px',
                        borderBottom: '1px solid #fafafa',
                        background: bg,
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {count.toLocaleString()}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
