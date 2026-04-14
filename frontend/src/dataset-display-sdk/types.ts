/**
 * Dataset Display SDK — 사용 목적(detection / classification / ...)별로 UI를 분화하기 위한 registry.
 *
 * 배경: 같은 DatasetGroup / Dataset이라도 task_types에 따라 "클래스 정보", "포맷", "메타파일"
 * 같은 요소의 표시 방식이 달라진다. 페이지에 if문을 흩뿌리는 대신, kind별 definition을 등록해
 * 페이지는 definition에만 위임한다. 새 kind 추가 = definition 파일 1개 + bootstrap 등록 1줄.
 *
 * 파이프라인 노드 SDK(src/pipeline-sdk)와 동일한 철학. 자세한 사용은 registry.ts / bootstrap.ts 참고.
 */
import type { ReactNode } from 'react'
import type {
  AnnotationFormat,
  DatasetGroup,
  DatasetSummary,
} from '../types/dataset'

/** 지원 kind. 새 종류 추가 시 여기에 리터럴을 더하고 bootstrap / expected 배열도 갱신. */
export type DatasetKind = 'detection' | 'classification'

/** 그룹 상세 페이지의 데이터셋 테이블이 각 셀 render에 전달하는 컨텍스트. */
export interface DatasetListCellContext {
  /** 현재 편집 중인 dataset id (포맷 편집 모드). null이면 편집 중 아님. */
  editingFormatDatasetId: string | null
  /** 편집 모드에서 현재 선택 중인 포맷 값. */
  editingFormatValue: AnnotationFormat
  /** 서비스 호출이 진행 중인 dataset id 목록 (로딩 스피너용). */
  updatingFormatDatasetId: string | null
  validatingDatasetId: string | null
  replacingMetaFileDatasetId: string | null
  /** 포맷 편집 진입. */
  onStartEditFormat: (dataset: DatasetSummary) => void
  /** 편집 중 포맷 값 변경. */
  onChangeEditingFormat: (value: AnnotationFormat) => void
  /** 포맷 변경 확정. */
  onConfirmFormatChange: (datasetId: string) => void
  /** 편집 취소. */
  onCancelEditFormat: () => void
  /** 검증 실행 (detection 전용). */
  onValidateDataset: (dataset: DatasetSummary) => void
  /** 메타 파일 교체 브라우저 열기 (detection 전용). */
  onOpenMetaFileBrowser: (datasetId: string) => void
}

/**
 * Kind별 definition. 현재는 그룹 상세 페이지의 3개 셀만 분화 대상.
 * 나중에 Viewer/EDA 탭 분화 필요 시 이 인터페이스에 viewer 필드를 추가한다.
 */
export interface DatasetKindDefinition {
  /** 내부 식별자. */
  kind: DatasetKind
  /** 사용자에게 보이는 한글 라벨. 디버깅/툴팁에 활용. */
  displayLabel: string
  /**
   * 주어진 그룹이 이 kind에 해당하는지 판정.
   * 판정 우선순위(015 핸드오프 §4): annotation_format === 'CLS_MANIFEST' OR head_schema != null.
   * class_count 유무로 판단 금지.
   */
  matches: (group: DatasetGroup) => boolean
  /** 클래스 정보 컬럼 render. */
  renderClassInfoCell: (
    dataset: DatasetSummary,
    group: DatasetGroup,
    ctx: DatasetListCellContext,
  ) => ReactNode
  /** 포맷 컬럼 render. 편집 허용 여부/옵션 집합은 definition 내부 판단. */
  renderFormatCell: (
    dataset: DatasetSummary,
    group: DatasetGroup,
    ctx: DatasetListCellContext,
  ) => ReactNode
  /** 행 우측의 메타 파일 액션 버튼(들). 비활성/숨김도 이 함수에서 결정. */
  renderMetaFileAction: (
    dataset: DatasetSummary,
    group: DatasetGroup,
    ctx: DatasetListCellContext,
  ) => ReactNode
  /** 데이터셋 상세 페이지의 샘플 뷰어 탭. kind별로 overlay 유무 등 렌더 규칙이 다르다. */
  renderSampleViewer: (datasetId: string) => ReactNode
  /** EDA 탭. kind별 지표 구성이 달라 definition에 위임. */
  renderEdaTab: (datasetId: string) => ReactNode
  /** Lineage 탭. 현재 classification은 placeholder. */
  renderLineageTab: (datasetId: string) => ReactNode
}
