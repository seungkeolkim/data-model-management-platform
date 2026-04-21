/**
 * Classification (CLS_MANIFEST) 그룹의 데이터셋 목록 셀 렌더러.
 *
 * 분화 포인트:
 * - 클래스 정보: class_count 대신 metadata.class_info.heads[] 를 head별 summary + Popover로 표시.
 *   헤드 내 class 목록 + (있으면) per_class_image_count / multi_label 을 함께 보여준다.
 * - 포맷: CLS_MANIFEST 고정, 변경 버튼 비활성.
 * - 메타 파일: 교체 대신 추후 viewer 구현 예정(015 §3-6). 지금은 비활성 버튼 + 안내 툴팁.
 *
 * 데이터 소스는 Dataset.metadata.class_info 만 사용한다 — 그룹의 head_schema는 SSOT지만
 * split별 실제 수록 class(중복 충돌 SKIP 등)는 dataset 개별 값이 정확하므로(사용자 결정).
 */
import { Button, Popover, Space, Tag, Tooltip, Typography } from 'antd'
import { FileTextOutlined, InfoCircleOutlined } from '@ant-design/icons'
import ClassificationSampleViewerTab from '../../components/dataset-viewer/classification/ClassificationSampleViewerTab'
import ClassificationEdaTab from '../../components/dataset-viewer/classification/ClassificationEdaTab'
import LineageTab from '../../components/dataset-viewer/LineageTab'
import type {
  DatasetGroup,
  DatasetSummary,
  ClassificationClassInfo,
  ClassificationHeadInfo,
} from '../../types/dataset'
import { isClassificationClassInfo } from '../../types/dataset'
import type { DatasetKindDefinition, DatasetListCellContext } from '../types'

const { Text } = Typography

/** head별 class 목록 + per_class_image_count 표시 Popover. */
function HeadDetailContent({ heads }: { heads: ClassificationHeadInfo[] }) {
  return (
    <div style={{ maxHeight: 360, overflowY: 'auto', minWidth: 260 }}>
      {heads.map((head) => {
        // classes는 class_mapping 인덱스 순서대로 복원 — 출력 index 계약과 일치
        const classEntries = Object.entries(head.class_mapping).sort(
          ([indexA], [indexB]) => Number(indexA) - Number(indexB),
        )
        return (
          <div key={head.name} style={{ marginBottom: 12 }}>
            <div style={{ marginBottom: 4 }}>
              <Text strong>{head.name}</Text>
              <Tag
                color={head.multi_label ? 'gold' : 'blue'}
                style={{ marginLeft: 8, fontSize: 11 }}
              >
                {head.multi_label ? 'multi-label' : 'single-label'}
              </Tag>
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 4 }}>
                {classEntries.length}개
              </Text>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <th style={{ textAlign: 'left', padding: '3px 10px 3px 0', color: '#888', width: 40 }}>
                    idx
                  </th>
                  <th style={{ textAlign: 'left', padding: '3px 10px 3px 0', color: '#888' }}>
                    class
                  </th>
                  <th style={{ textAlign: 'right', padding: '3px 0', color: '#888' }}>이미지</th>
                </tr>
              </thead>
              <tbody>
                {classEntries.map(([index, className]) => {
                  const perClassCount = head.per_class_image_count?.[className]
                  return (
                    <tr key={`${head.name}:${index}`} style={{ borderBottom: '1px solid #fafafa' }}>
                      <td style={{ padding: '2px 10px 2px 0', fontFamily: 'monospace' }}>{index}</td>
                      <td style={{ padding: '2px 10px 2px 0' }}>{className}</td>
                      <td style={{ padding: '2px 0', textAlign: 'right' }}>
                        {perClassCount != null ? perClassCount.toLocaleString() : '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      })}
    </div>
  )
}

function renderClassInfoCell(
  dataset: DatasetSummary,
  _group: DatasetGroup,
  _ctx: DatasetListCellContext,
) {
  const rawClassInfo = dataset.metadata?.class_info
  const classificationInfo: ClassificationClassInfo | undefined =
    isClassificationClassInfo(rawClassInfo) ? rawClassInfo : undefined

  if (!classificationInfo || classificationInfo.heads.length === 0) {
    return <Text type="secondary">-</Text>
  }

  const headCount = classificationInfo.heads.length
  const totalClassCount = classificationInfo.heads.reduce(
    (sum, head) => sum + Object.keys(head.class_mapping).length,
    0,
  )

  return (
    <Space size={4}>
      <Text>
        {headCount} head / {totalClassCount} class
      </Text>
      <Popover
        title={`Head 상세 (${headCount}개)`}
        content={<HeadDetailContent heads={classificationInfo.heads} />}
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

function renderFormatCell(
  _dataset: DatasetSummary,
  _group: DatasetGroup,
  _ctx: DatasetListCellContext,
) {
  // classification 그룹은 CLS_MANIFEST 고정 — 변경 불가
  return (
    <Space size={4}>
      <Tag color="geekblue">CLS_MANIFEST</Tag>
      <Tooltip title="Classification 데이터셋의 포맷은 CLS_MANIFEST로 고정입니다.">
        <Text type="secondary" style={{ fontSize: 12 }}>
          고정
        </Text>
      </Tooltip>
    </Space>
  )
}

function renderMetaFileAction(
  _dataset: DatasetSummary,
  _group: DatasetGroup,
  _ctx: DatasetListCellContext,
) {
  // manifest.jsonl viewer는 추후 구현(015 §3-6). 현재는 비활성 + 안내.
  return (
    <Tooltip title="manifest.jsonl 뷰어는 추후 제공 예정입니다.">
      <Button
        type="text"
        size="small"
        icon={<FileTextOutlined />}
        disabled
        onClick={(event) => event.stopPropagation()}
      />
    </Tooltip>
  )
}

export const classificationDefinition: DatasetKindDefinition = {
  kind: 'classification',
  displayLabel: 'Classification',
  matches: (group) => {
    // 015 §4 분기 키: CLS_MANIFEST 포맷 또는 head_schema 존재 (둘 중 하나라도 true면 classification)
    return group.annotation_format === 'CLS_MANIFEST' || !!group.head_schema
  },
  renderClassInfoCell,
  renderFormatCell,
  renderMetaFileAction,
  renderSampleViewer: (datasetId) => <ClassificationSampleViewerTab datasetId={datasetId} />,
  renderEdaTab: (datasetId) => <ClassificationEdaTab datasetId={datasetId} />,
  // Classification 도 detection 과 동일한 lineage 그래프(DatasetLineage 엣지 + transform_config.tasks)
  // 를 사용한다. dag_executor 가 task prefix(det_/cls_) 무관하게 동일하게 엣지를 기록하므로
  // LineageTab 을 그대로 재사용한다.
  renderLineageTab: (datasetId) => <LineageTab datasetId={datasetId} />,
}
