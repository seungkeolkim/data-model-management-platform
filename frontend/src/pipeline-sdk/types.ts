/**
 * 파이프라인 노드 SDK — 공통 타입
 *
 * NodeDefinition 중심의 아키텍처. 새 특수 노드 추가 시 수정 지점은
 *   1) definitions/<name>.tsx 에 NodeDefinition 객체 정의
 *   2) NodeDataByKind 테이블에 1줄 추가
 * 두 곳뿐이다.
 */

import type { ComponentType } from 'react'
import type { Edge, Node, NodeProps } from '@xyflow/react'
import type {
  ClientValidationError,
  DataLoadNodeData,
  MergeNodeData,
  OperatorNodeData,
  PipelineConfig,
  PipelineValidationIssue,
  SaveNodeData,
  TaskConfig,
} from '@/types/pipeline'
import type { Manipulator } from '@/types/dataset'

// =============================================================================
// Placeholder 노드 데이터 — registry에 없는 operator 복원 시 사용
// =============================================================================

export interface PlaceholderNodeData {
  type: 'placeholder'
  originalOperator: string                 // 원본 config의 operator 이름
  originalParams: Record<string, unknown>  // 원본 params (열람용)
  originalInputs: string[]                 // 원본 inputs 참조 (source:... / task_...)
  reason: string                           // "registry에 등록되지 않음" 등
  validationIssues?: PipelineValidationIssue[]
  [key: string]: unknown
}

// =============================================================================
// 노드 종류 ↔ 데이터 타입 매핑 테이블
// =============================================================================

/**
 * 노드 kind → 데이터 타입 매핑. 새 특수 노드 추가 시 1줄만 추가하면 된다.
 * registry 키 집합은 이 테이블의 키 집합과 반드시 일치해야 한다(부팅 시 assert).
 */
export interface NodeDataByKind {
  dataLoad: DataLoadNodeData
  operator: OperatorNodeData
  merge: MergeNodeData
  save: SaveNodeData
  placeholder: PlaceholderNodeData
}

export type NodeKind = keyof NodeDataByKind
export type AnyNodeData = NodeDataByKind[NodeKind]

// =============================================================================
// 팔레트 / 생성 컨텍스트
// =============================================================================

export type PaletteSection = 'basic' | 'manipulator'

/** 노드 생성 시 SDK가 전달하는 컨텍스트 */
export interface CreateContext {
  /** 현재 에디터에서 선택된 task type (예: 'DETECTION') */
  taskType: string
  /** operator definition이 manipulator 메타를 요구할 때 주입 */
  manipulator?: Manipulator
}

/** 팔레트에 노출되는 항목. operator의 경우 manipulator 당 1개씩 동적 생성된다. */
export interface PaletteItem<K extends NodeKind = NodeKind> {
  key: string                          // manipulator name 또는 특수 노드 키
  section: PaletteSection
  label: string
  description?: string
  color: string
  emoji: string
  kind: K
  disabled?: { reason: string; modalTitle?: string } | null
  /** 추가 전 확인 모달을 띄울 경고. disabled 와 달리 확인 시 노드가 추가된다. */
  confirmWarning?: { title: string; content: string } | null
  createData: () => NodeDataByKind[K]
}

// =============================================================================
// 그래프 ↔ Config 변환 컨텍스트
// =============================================================================

/** toConfigContribution 호출 시 주입되는 컨텍스트 */
export interface ConvertContext {
  nodeId: string
  incomingEdges: Edge[]
  /** sourceNodeId → nodeData 매핑 헬퍼 */
  getNodeData: (nodeId: string) => AnyNodeData | undefined
}

/** 각 노드가 PipelineConfig에 기여하는 부분 */
export interface ConfigContribution {
  /** tasks[key]로 병합될 항목. 노드가 task를 발생시키지 않으면 빈 객체. */
  tasks?: Record<string, TaskConfig>
  /** PipelineConfig 루트에 병합될 필드. SaveNode가 name/output/description 을 기여하며,
   *  Load→Save 직결(tasks 비어있음)일 때 passthrough_source_split_id 도 추가한다. */
  root?: Partial<Pick<PipelineConfig, 'name' | 'description' | 'output' | 'passthrough_source_split_id'>>
  /** 다른 노드가 이 노드를 inputs에서 참조할 때 사용할 토큰. 없으면 이 노드는 edge 대상으로 참조 불가. */
  outputRef?: string
}

/** matchFromConfig 반환값 — 복원된 노드가 점유한 task/source ownership 명시 */
export interface RestoredContribution<TData> {
  nodeId: string
  data: TData
  ownedTaskKeys: string[]
  ownedSourceDatasetIds?: string[]
}

export interface MatchContext {
  config: PipelineConfig
  manipulatorMap: Record<string, Manipulator>
  datasetDisplayMap: Record<string, {
    datasetId: string
    groupId: string
    groupName: string
    split: string
    version: string
  }>
  /** 이미 다른 definition이 점유한 task key. 중복 점유 방지용. */
  claimedTaskKeys: Set<string>
  claimedSourceDatasetIds: Set<string>
}

// =============================================================================
// 검증 컨텍스트
// =============================================================================

export interface GraphContext {
  nodes: Node<AnyNodeData>[]
  edges: Edge[]
  nodeDataMap: Record<string, AnyNodeData>
}

// =============================================================================
// NodeDefinition — 노드의 모든 관심사 통합
// =============================================================================

export interface NodeDefinition<K extends NodeKind = NodeKind> {
  /** React Flow 노드 타입 키. NodeDataByKind의 키와 일치. */
  kind: K

  /** 팔레트 표현. operator 계열은 manipulator 당 동적 항목을 paletteFromManipulators로 생성. */
  palette?: {
    section: PaletteSection
    label: string
    description?: string
    color: string
    emoji: string
    order?: number
    createDefaultData: (ctx: CreateContext) => NodeDataByKind[K]
  }

  /**
   * manipulator API 응답을 받아 팔레트 항목 리스트로 확장하는 훅.
   * kind='operator' 용. 호출되지 않으면 palette 객체만 사용.
   */
  paletteFromManipulators?: (
    manipulators: Manipulator[],
    ctx: CreateContext,
  ) => PaletteItem<K>[]

  /** 캔버스에 렌더되는 React Flow 노드 컴포넌트. NodeShell 기반. */
  NodeComponent: ComponentType<NodeProps>

  /** 우측 PropertiesPanel 본문. 없으면 기본 설명만 표시. */
  PropertiesComponent?: ComponentType<{ nodeId: string; data: NodeDataByKind[K] }>

  /** 클라이언트 사전 검증. 반환된 에러는 즉시 사용자에게 표시. */
  validate?(data: NodeDataByKind[K], ctx: GraphContext & { nodeId: string }): ClientValidationError[]

  /** 그래프 → Config 변환 시 이 노드가 기여하는 부분을 반환. */
  toConfigContribution?(
    data: NodeDataByKind[K],
    ctx: ConvertContext,
  ): ConfigContribution | null

  /**
   * Config → 그래프 역변환. 이 definition이 맡을 task / source를 식별하여 복원.
   * - DataLoadDefinition: source:<id> 토큰을 점유
   * - OperatorDefinition: MANIPULATOR_REGISTRY에 등록된 operator task를 점유
   * - MergeDefinition: operator ∈ {det_merge_datasets, cls_merge_datasets} task를 점유
   * - SaveDefinition: PipelineConfig.output/name으로부터 단일 인스턴스 생성
   * - PlaceholderDefinition: 남은(미점유) task를 placeholder로 점유
   */
  matchFromConfig?(ctx: MatchContext): RestoredContribution<NodeDataByKind[K]>[]

  /** 서버 검증 결과의 issue.field가 이 노드에 매핑되는지 판정 */
  matchIssueField?(issue: PipelineValidationIssue, data: NodeDataByKind[K], nodeId: string): boolean
}
