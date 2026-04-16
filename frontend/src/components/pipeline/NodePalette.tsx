/**
 * NodePalette — SDK registry 기반 팔레트.
 *
 * buildPaletteItems가 등록된 NodeDefinition과 manipulator API 응답을 합쳐
 * 팔레트 항목 리스트를 반환한다. 이 컴포넌트는 그 리스트를 렌더링만 한다.
 *
 * 새 특수 노드 / 새 manipulator 추가 시 이 파일 수정 불요.
 */
import { Typography, Collapse, Button, Spin, Badge, Tooltip } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { manipulatorsApi } from '@/api/pipeline'
import type { PipelineNodeData } from '@/types/pipeline'
import {
  buildPaletteItems,
  CATEGORY_STYLE,
  CATEGORY_ITEM_ORDER,
  DEFAULT_CATEGORY_STYLE,
  getCategoryStyle,
  showDisabledModal,
} from '@/pipeline-sdk'

const { Text } = Typography

interface NodePaletteProps {
  onAddNode: (data: PipelineNodeData) => void
  taskType: string
}

export default function NodePalette({ onAddNode, taskType }: NodePaletteProps) {
  const { data: manipulatorResponse, isLoading } = useQuery({
    queryKey: ['manipulators-for-palette'],
    queryFn: () => manipulatorsApi.list({ status: 'ACTIVE' }).then((r) => r.data),
    staleTime: 60_000,
  })

  const manipulators = (manipulatorResponse?.items ?? []).filter((m) => {
    if (!m.compatible_task_types || m.compatible_task_types.length === 0) return true
    return m.compatible_task_types.includes(taskType as never)
  })

  const paletteItems = buildPaletteItems(manipulators, { taskType })

  // basic 섹션(특수 노드)과 manipulator 섹션 분리
  const basicItems = paletteItems.filter((item) => item.section === 'basic')
  const manipulatorItems = paletteItems.filter((item) => item.section === 'manipulator')

  // manipulator 섹션은 category별로 그룹핑
  const groupedByCategory: Record<string, typeof manipulatorItems> = {}
  for (const item of manipulatorItems) {
    // kind='operator' 항목의 category를 상대적으로 알려면 원본 manipulator 조회
    const manipulator = manipulators.find((m) => m.name === item.key)
    const category = manipulator?.category ?? 'UNKNOWN'
    if (!groupedByCategory[category]) groupedByCategory[category] = []
    groupedByCategory[category].push(item)
  }

  const categoryOrder = Object.keys(CATEGORY_STYLE)
  const sortedCategories = Object.entries(groupedByCategory).sort(([a], [b]) => {
    const idxA = categoryOrder.indexOf(a)
    const idxB = categoryOrder.indexOf(b)
    return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB)
  })

  // 카테고리별로 CATEGORY_ITEM_ORDER 에 명시된 항목을 앞쪽 지정 순서로,
  // 나머지는 기존 순서(API 응답 = name asc) 그대로 뒤에 붙인다.
  for (const [category, items] of sortedCategories) {
    const explicitOrder = CATEGORY_ITEM_ORDER[category]
    if (!explicitOrder || explicitOrder.length === 0) continue
    items.sort((a, b) => {
      const idxA = explicitOrder.indexOf(a.key)
      const idxB = explicitOrder.indexOf(b.key)
      const rankA = idxA === -1 ? explicitOrder.length : idxA
      const rankB = idxB === -1 ? explicitOrder.length : idxB
      if (rankA !== rankB) return rankA - rankB
      // 명시 순서 밖 항목끼리는 이름 알파벳 순 (기존 기본값 유지).
      return a.key.localeCompare(b.key)
    })
  }

  const collapseItems = sortedCategories.map(([category, items]) => {
    const meta = CATEGORY_STYLE[category] ?? DEFAULT_CATEGORY_STYLE
    return {
      key: category,
      label: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>{meta.emoji}</span>
          <span>{meta.label}</span>
          <Badge count={items.length} style={{ backgroundColor: meta.color }} size="small" />
        </span>
      ),
      children: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {items.map((item) => {
            const categoryStyle = getCategoryStyle(category)
            const tooltipText = item.description && item.description !== item.label
              ? extractTooltip(item.description)
              : null

            const handleClick = () => {
              if (item.disabled) {
                showDisabledModal({
                  label: item.label,
                  disabled: item.disabled,
                })
                return
              }
              onAddNode(item.createData() as PipelineNodeData)
            }

            const button = (
              <Button
                size="small"
                block
                style={{
                  textAlign: 'left',
                  fontSize: 12,
                  borderColor: item.disabled ? '#d9d9d9' : categoryStyle.color,
                  color: item.disabled ? '#bfbfbf' : categoryStyle.color,
                  pointerEvents: item.disabled ? 'none' : undefined,
                }}
                onClick={item.disabled ? undefined : handleClick}
              >
                {item.emoji} {item.label}
              </Button>
            )

            const wrappedButton = item.disabled ? (
              <div key={item.key} onClick={handleClick} style={{ cursor: 'pointer' }}>
                {button}
              </div>
            ) : (
              <span key={item.key}>{button}</span>
            )

            return tooltipText ? (
              <Tooltip key={item.key} title={tooltipText} placement="right" mouseEnterDelay={0.3}>
                {wrappedButton}
              </Tooltip>
            ) : (
              wrappedButton
            )
          })}
        </div>
      ),
    }
  })

  return (
    <div
      style={{
        width: 240,
        background: '#fafafa',
        borderRight: '1px solid #f0f0f0',
        height: '100%',
        overflowY: 'auto',
        padding: '12px 8px',
      }}
    >
      <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 12 }}>
        노드 팔레트
      </Text>

      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
          기본 노드
        </Text>
        {basicItems.map((item) => (
          <Button
            key={item.key}
            size="small"
            block
            style={{
              textAlign: 'left',
              marginBottom: 4,
              borderColor: item.color,
              color: item.color,
            }}
            onClick={() => onAddNode(item.createData() as PipelineNodeData)}
          >
            {item.emoji} {item.label}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <Spin size="small" />
        </div>
      ) : (
        <Collapse
          size="small"
          ghost
          items={collapseItems}
          defaultActiveKey={Object.keys(groupedByCategory)}
        />
      )}
    </div>
  )
}

/** "버튼 텍스트 (도움말)" 패턴에서 괄호 안 도움말 추출 */
function extractTooltip(description: string): string | null {
  const match = description.match(/^(.+?)\s*\((.+)\)\s*$/)
  return match ? match[2] : null
}
