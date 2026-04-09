/**
 * NodePalette — 좌측 노드 팔레트
 *
 * API에서 manipulator 목록을 조회하여 카테고리별로 그룹핑하고,
 * 클릭 시 캔버스에 노드를 추가한다.
 * 특수 노드(DataLoad, Save)도 팔레트 상단에 표시한다.
 *
 * UDM 확장: manipulatorsApi가 반환하는 모든 카테고리를 동적으로 표시하므로,
 * 새로운 카테고리(UDM 등)가 추가되면 자동으로 팔레트에 나타난다.
 */

import { Typography, Collapse, Button, Spin, Badge, Tooltip, Modal } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { manipulatorsApi } from '@/api/pipeline'
import type { Manipulator } from '@/types/dataset'
import type { PipelineNodeData } from '@/types/pipeline'
import { CATEGORY_STYLE, DEFAULT_CATEGORY_STYLE, SPECIAL_NODE_STYLE, getManipulatorEmoji } from './nodeStyles'

const { Text } = Typography

interface NodePaletteProps {
  onAddNode: (data: PipelineNodeData) => void
  /** 현재 에디터의 태스크 타입 — 호환되는 manipulator만 표시 */
  taskType: string
}

export default function NodePalette({ onAddNode, taskType }: NodePaletteProps) {
  const { data: manipulatorResponse, isLoading } = useQuery({
    queryKey: ['manipulators-for-palette'],
    queryFn: () => manipulatorsApi.list({ status: 'ACTIVE' }).then((r) => r.data),
    staleTime: 60_000,
  })

  // taskType에 호환되는 manipulator만 필터링
  // compatible_task_types가 null이면 모든 타입에 호환 (범용 manipulator)
  const manipulators = (manipulatorResponse?.items ?? []).filter((m) => {
    if (!m.compatible_task_types || m.compatible_task_types.length === 0) return true
    return m.compatible_task_types.includes(taskType as never)
  })

  // 카테고리별 그룹핑
  const groupedByCategory = manipulators.reduce<Record<string, Manipulator[]>>((acc, m) => {
    const cat = m.category
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(m)
    return acc
  }, {})

  // merge_datasets는 별도 MergeNode로 처리하므로 MERGE 카테고리에서 제외
  // (특수 노드 섹션에 별도 배치)
  if (groupedByCategory['MERGE']) {
    groupedByCategory['MERGE'] = groupedByCategory['MERGE'].filter(
      (m) => m.name !== 'merge_datasets',
    )
    if (groupedByCategory['MERGE'].length === 0) {
      delete groupedByCategory['MERGE']
    }
  }

  /** description에서 괄호 부분을 제거한 짧은 라벨을 반환 */
  const extractShortLabel = (desc: string): string => {
    const match = desc.match(/^(.+?)\s*\((.+)\)\s*$/)
    return match ? match[1] : desc
  }

  /** params_schema에 default가 있는 필드를 추출하여 초기 params를 구성 */
  const buildDefaultParams = (schema: Record<string, unknown> | null): Record<string, unknown> => {
    if (!schema) return {}
    const defaults: Record<string, unknown> = {}
    for (const [key, field] of Object.entries(schema)) {
      const fieldDef = field as { default?: unknown }
      if (fieldDef.default !== undefined) {
        defaults[key] = fieldDef.default
      }
    }
    return defaults
  }

  /** Operator 노드 데이터 생성 */
  const createOperatorNodeData = (m: Manipulator): PipelineNodeData => {
    const paramsSchema = m.params_schema as Record<string, unknown> | null
    return {
      type: 'operator',
      operator: m.name,
      category: m.category,
      label: extractShortLabel(m.description ?? m.name),
      params: buildDefaultParams(paramsSchema),
      paramsSchema,
    }
  }

  // Collapse 패널 아이템 구성 — CATEGORY_STYLE 정의 순서대로 정렬
  const categoryOrder = Object.keys(CATEGORY_STYLE)
  const sortedCategories = Object.entries(groupedByCategory).sort(([a], [b]) => {
    const idxA = categoryOrder.indexOf(a)
    const idxB = categoryOrder.indexOf(b)
    return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB)
  })
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
          {items.map((m) => {
            const desc = m.description ?? m.name
            // "버튼 텍스트 (도움말)" 패턴이면 괄호 안 내용을 툴팁으로 분리
            const parenMatch = desc.match(/^(.+?)\s*\((.+)\)\s*$/)
            const buttonLabel = parenMatch ? parenMatch[1] : desc
            const tooltipText = parenMatch ? parenMatch[2] : null

            // FORMAT_CONVERT 카테고리는 비활성화 — 통일포맷에서 자동 처리됨
            const isFormatConvert = category === 'FORMAT_CONVERT'

            const handleClick = isFormatConvert
              ? () => {
                  Modal.info({
                    title: '포맷 변환은 자동으로 처리됩니다',
                    content: (
                      <div>
                        <p>통일포맷 도입으로 포맷 변환이 파이프라인 저장 시 자동으로 수행됩니다.</p>
                        <p>Save 노드의 <b>출력 포맷</b>(COCO / YOLO) 설정만으로 원하는 포맷의 데이터셋이 생성되므로, 사용자가 명시적으로 포맷 변환 노드를 추가할 필요가 없습니다.</p>
                      </div>
                    ),
                    okText: '확인',
                  })
                }
              : () => onAddNode(createOperatorNodeData(m))

            const button = (
              <Button
                key={m.name}
                size="small"
                block
                style={{
                  textAlign: 'left',
                  fontSize: 12,
                  borderColor: isFormatConvert ? '#d9d9d9' : meta.color,
                  color: isFormatConvert ? '#bfbfbf' : meta.color,
                  pointerEvents: isFormatConvert ? 'none' : undefined,
                }}
                onClick={isFormatConvert ? undefined : handleClick}
              >
                {getManipulatorEmoji(m.name, category)} {buttonLabel}
              </Button>
            )

            // FORMAT_CONVERT: 버튼은 비활성 스타일이지만, 감싼 div에서 클릭을 받아 모달 표시
            const wrappedButton = isFormatConvert ? (
              <div key={m.name} onClick={handleClick} style={{ cursor: 'pointer' }}>
                {button}
              </div>
            ) : (
              <span key={m.name}>{button}</span>
            )

            return tooltipText ? (
              <Tooltip key={m.name} title={tooltipText} placement="right" mouseEnterDelay={0.3}>
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

  const dl = SPECIAL_NODE_STYLE.DATA_LOAD
  const mg = SPECIAL_NODE_STYLE.MERGE
  const sv = SPECIAL_NODE_STYLE.SAVE

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

      {/* 특수 노드 — 항상 상단 고정 */}
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
          기본 노드
        </Text>

        <Button
          size="small"
          block
          style={{ textAlign: 'left', marginBottom: 4, borderColor: dl.color, color: dl.color }}
          onClick={() =>
            onAddNode({
              type: 'dataLoad',
              groupId: null,
              groupName: '',
              split: null,
              datasetId: null,
              version: null,
              datasetLabel: '',
            })
          }
        >
          {dl.emoji} Data Load
        </Button>

        <Button
          size="small"
          block
          style={{ textAlign: 'left', marginBottom: 4, borderColor: mg.color, color: mg.color }}
          onClick={() =>
            onAddNode({
              type: 'merge',
              operator: 'merge_datasets',
              params: {},
              inputCount: 2,
            })
          }
        >
          {mg.emoji} Merge (병합)
        </Button>

        <Button
          size="small"
          block
          style={{ textAlign: 'left', borderColor: sv.color, color: sv.color }}
          onClick={() =>
            onAddNode({
              type: 'save',
              name: '',
              description: '',
              datasetType: 'PROCESSED',
              annotationFormat: 'COCO',
              split: 'NONE',
            })
          }
        >
          {sv.emoji} Save (출력 설정)
        </Button>
      </div>

      {/* Manipulator 카테고리별 */}
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
