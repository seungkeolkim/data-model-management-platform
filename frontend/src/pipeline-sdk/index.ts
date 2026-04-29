/**
 * 파이프라인 노드 SDK 공개 API.
 *
 * 외부에서는 이 파일에서만 import하도록 한다.
 * bootstrap을 1회 import해야 registry가 초기화된다.
 */
export * from './types'
export { getNodeDefinition, getAllNodeDefinitions } from './registry'
export { useNodeData, useSetNodeData } from './hooks/useNodeData'
export { NodeShell } from './components/NodeShell'
export { buildPaletteItems } from './palette'
export { buildNodeTypesFromRegistry } from './nodeTypes'
export {
  graphToPipelineConfig,
  graphToPartialPipelineConfig,
  CURRENT_SCHEMA_VERSION,
} from './engine/graphToConfig'
export {
  pipelineConfigToGraph,
  extractSourceDatasetIdsFromConfig,
  unresolveVersionRefsToSplitRefs,
} from './engine/configToGraph'
export type { DatasetDisplayInfo } from './engine/configToGraph'
export { parseSourceRef, buildSplitSourceRef, buildVersionSourceRef } from './sourceFormat'
export { validateGraphStructure } from './engine/clientValidation'
export { distributeIssuesToNodes } from './engine/issueMapping'
export { showDisabledModal } from './definitions/operatorDefinition'
export {
  CATEGORY_STYLE,
  CATEGORY_ITEM_ORDER,
  DEFAULT_CATEGORY_STYLE,
  getCategoryStyle,
  getManipulatorEmoji,
} from './styles'

// bootstrap — side-effect 등록. 이 파일을 import하면 registry가 채워진다.
import './bootstrap'
