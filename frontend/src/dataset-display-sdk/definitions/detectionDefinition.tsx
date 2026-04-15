/**
 * Detection (COCO / YOLO / 기타 bbox 계열) 그룹의 데이터셋 목록 셀 렌더러.
 * 기존 DatasetDetailPage.tsx에서 직접 렌더하던 3개 셀(class_info, format, meta action)을 이관했다.
 * 동작은 완전히 동일 — 정리 리팩터만 한 상태.
 */
import { Button, Popover, Select, Space, Tag, Typography } from 'antd'
import {
  CheckCircleOutlined,
  FileOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import type {
  AnnotationFormat,
  DatasetGroup,
  DatasetSummary,
  DetectionClassInfo,
} from '../../types/dataset'
import { isDetectionClassInfo } from '../../types/dataset'
import type { DatasetKindDefinition, DatasetListCellContext } from '../types'
import SampleViewerTab from '../../components/dataset-viewer/SampleViewerTab'
import EdaTab from '../../components/dataset-viewer/EdaTab'
import LineageTab from '../../components/dataset-viewer/LineageTab'

const { Text } = Typography

const DETECTION_FORMAT_COLOR: Record<string, string> = {
  COCO: 'green',
  YOLO: 'orange',
  ATTR_JSON: 'cyan',
  CLS_MANIFEST: 'geekblue',
  CUSTOM: 'purple',
  NONE: 'default',
}

/** detection 그룹의 포맷 편집 드롭다운 옵션 — classification 전용 포맷은 제외 */
const DETECTION_FORMAT_OPTIONS: { value: AnnotationFormat; label: string }[] = [
  { value: 'COCO', label: 'COCO' },
  { value: 'YOLO', label: 'YOLO' },
  { value: 'ATTR_JSON', label: 'ATTR_JSON' },
  { value: 'CUSTOM', label: 'CUSTOM' },
  { value: 'NONE', label: 'NONE' },
]

/** 클래스 매핑 Popover — ID→이름 테이블. */
function ClassMappingContent({ classMapping }: { classMapping: Record<string, string> }) {
  const entries = Object.entries(classMapping).sort(
    ([keyA], [keyB]) => Number(keyA) - Number(keyB),
  )
  return (
    <div style={{ maxHeight: 300, overflowY: 'auto', minWidth: 180 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #f0f0f0' }}>
            <th style={{ textAlign: 'left', padding: '4px 12px 4px 0', color: '#888' }}>ID</th>
            <th style={{ textAlign: 'left', padding: '4px 0', color: '#888' }}>클래스명</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([classId, className]) => (
            <tr key={classId} style={{ borderBottom: '1px solid #fafafa' }}>
              <td style={{ padding: '3px 12px 3px 0', fontFamily: 'monospace' }}>{classId}</td>
              <td style={{ padding: '3px 0' }}>{className}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function renderClassInfoCell(
  dataset: DatasetSummary,
  group: DatasetGroup,
  ctx: DatasetListCellContext,
) {
  const rawClassInfo = dataset.metadata?.class_info
  const detectionClassInfo: DetectionClassInfo | undefined =
    isDetectionClassInfo(rawClassInfo) ? rawClassInfo : undefined

  const classCount = dataset.class_count ?? detectionClassInfo?.class_count
  const classMapping = detectionClassInfo?.class_mapping

  // 클래스 정보 완비 — 개수 + 상세보기 Popover
  if (classCount != null && classMapping) {
    return (
      <Space size={4}>
        <Text>{classCount}개</Text>
        <Popover
          title={`클래스 매핑 (${classCount}개)`}
          content={<ClassMappingContent classMapping={classMapping} />}
          trigger="click"
          placement="left"
        >
          <Button type="link" size="small" icon={<InfoCircleOutlined />} style={{ padding: 0 }}>
            상세보기
          </Button>
        </Popover>
      </Space>
    )
  }

  // 개수만 있는 경우
  if (classCount != null) {
    return <Text>{classCount}개</Text>
  }

  // 정보 없음 → 검증 버튼(포맷이 지정됐을 때만)
  const annotationFormat = dataset.annotation_format || group.annotation_format
  const isValidatable = annotationFormat && annotationFormat !== 'NONE'
  if (isValidatable) {
    return (
      <Button
        type="link"
        size="small"
        icon={<CheckCircleOutlined />}
        loading={ctx.validatingDatasetId === dataset.id}
        onClick={(event) => {
          event.stopPropagation()
          ctx.onValidateDataset(dataset)
        }}
      >
        검증
      </Button>
    )
  }
  return <Text type="secondary">-</Text>
}

function renderFormatCell(
  dataset: DatasetSummary,
  _group: DatasetGroup,
  ctx: DatasetListCellContext,
) {
  const currentFormat = dataset.annotation_format ?? 'NONE'
  const isEditing = ctx.editingFormatDatasetId === dataset.id

  if (isEditing) {
    return (
      <Space size={4} onClick={(event) => event.stopPropagation()}>
        <Select
          size="small"
          value={ctx.editingFormatValue}
          onChange={(value: AnnotationFormat) => ctx.onChangeEditingFormat(value)}
          style={{ width: 110 }}
          options={DETECTION_FORMAT_OPTIONS}
        />
        <Button
          type="primary"
          size="small"
          loading={ctx.updatingFormatDatasetId === dataset.id}
          onClick={() => ctx.onConfirmFormatChange(dataset.id)}
        >
          확인
        </Button>
        <Button size="small" onClick={ctx.onCancelEditFormat}>
          취소
        </Button>
      </Space>
    )
  }

  return (
    <Space size={4}>
      <Tag color={DETECTION_FORMAT_COLOR[currentFormat] ?? 'default'}>{currentFormat}</Tag>
      <Button
        type="link"
        size="small"
        style={{ padding: 0 }}
        onClick={(event) => {
          event.stopPropagation()
          ctx.onStartEditFormat(dataset)
        }}
      >
        변경
      </Button>
    </Space>
  )
}

function renderMetaFileAction(
  dataset: DatasetSummary,
  _group: DatasetGroup,
  ctx: DatasetListCellContext,
) {
  return (
    <Button
      type="text"
      size="small"
      icon={<FileOutlined />}
      loading={ctx.replacingMetaFileDatasetId === dataset.id}
      onClick={(event) => {
        event.stopPropagation()
        ctx.onOpenMetaFileBrowser(dataset.id)
      }}
      title={
        dataset.annotation_meta_file
          ? `메타 파일 교체 (현재: ${dataset.annotation_meta_file})`
          : '메타 파일 추가'
      }
      style={dataset.annotation_meta_file ? { color: '#1677ff' } : undefined}
    />
  )
}

export const detectionDefinition: DatasetKindDefinition = {
  kind: 'detection',
  displayLabel: 'Detection',
  matches: (group) => {
    // classification definition이 먼저 매칭되도록 resolve 순서가 보장되어 있으므로
    // detection은 "classification이 아닌 모든 그룹"을 수용하는 fallback 역할.
    // 여기서는 명시적으로 CLS_MANIFEST / head_schema 가 아닌 경우만 허용.
    return group.annotation_format !== 'CLS_MANIFEST' && !group.head_schema
  },
  renderClassInfoCell,
  renderFormatCell,
  renderMetaFileAction,
  renderSampleViewer: (datasetId) => <SampleViewerTab datasetId={datasetId} />,
  renderEdaTab: (datasetId) => <EdaTab datasetId={datasetId} />,
  renderLineageTab: (datasetId) => <LineageTab datasetId={datasetId} />,
}
