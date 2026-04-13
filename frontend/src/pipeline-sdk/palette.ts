/**
 * 팔레트 항목 구성.
 *
 * 1. 특수 노드(dataLoad/merge/save)는 정의의 palette.createDefaultData로부터 고정 항목 생성
 * 2. operator는 manipulator API 응답을 operatorDefinition.paletteFromManipulators로 확장
 *
 * 노드 타입별 분기 없이 registry 순회 + 각 definition의 hook 호출.
 */
import type { Manipulator } from '@/types/dataset'
import { getAllNodeDefinitions } from './registry'
import type { CreateContext, PaletteItem, NodeKind } from './types'

export function buildPaletteItems(
  manipulators: Manipulator[],
  ctx: CreateContext,
): PaletteItem[] {
  const items: PaletteItem[] = []
  for (const definition of getAllNodeDefinitions()) {
    if (definition.palette) {
      items.push({
        key: definition.kind,
        section: definition.palette.section,
        label: definition.palette.label,
        description: definition.palette.description,
        color: definition.palette.color,
        emoji: definition.palette.emoji,
        kind: definition.kind as NodeKind,
        disabled: null,
        createData: () => definition.palette!.createDefaultData(ctx) as never,
      })
    }
    if (definition.paletteFromManipulators) {
      items.push(...definition.paletteFromManipulators(manipulators, ctx) as PaletteItem[])
    }
  }
  // palette.order가 있으면 우선 그 순서대로 basic 섹션 내 정렬
  items.sort((a, b) => {
    if (a.section !== b.section) return a.section === 'basic' ? -1 : 1
    return 0
  })
  return items
}
