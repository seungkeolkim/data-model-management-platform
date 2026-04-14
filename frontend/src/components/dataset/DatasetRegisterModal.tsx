/**
 * 데이터셋 등록 모달 (파일 브라우저 방식)
 *
 * 등록 흐름:
 *   Step 0. 사용 목적(task_types) 선택
 *   Step 1. 이미지 폴더 선택 + 어노테이션 파일 선택 + Split 선택
 *   Step 2. Annotation format 선택 + 그룹 선택(기존 or 신규) → "등록"
 */
import { useState, useEffect } from 'react'
import {
  Modal,
  Form,
  Input,
  Select,
  Button,
  Alert,
  Divider,
  Space,
  Tag,
  Typography,
  Radio,
  Steps,
  Descriptions,
  Spin,
} from 'antd'
import {
  FolderOpenOutlined,
  FileOutlined,
  AppstoreOutlined,
  CloseCircleOutlined,
  PlusOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { datasetGroupsApi, fileBrowserApi } from '../../api/dataset'
import ServerFileBrowser from '../common/ServerFileBrowser'
import type {
  DatasetGroup,
  TaskType,
  AnnotationFormat,
  FormatValidateResponse,
  ClassificationScanResponse,
} from '../../types/dataset'

const { Text } = Typography
const { Option } = Select

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (group: DatasetGroup) => void
  existingGroup?: DatasetGroup | null
}

// ─── 상수 ────────────────────────────────────────────────────────────────────

// 사용 목적 옵션
// - Classification과 Attribute Classification은 '다중 head를 가진 이미지 전체 분류'로 통합됨
//   (예: 객체 상의색상/하의색상 등 여러 속성을 동시에 분류)
const TASK_TYPE_OPTIONS: { value: TaskType; label: string; desc: string }[] = [
  { value: 'DETECTION',      label: 'Object Detection', desc: '바운딩 박스 기반 객체 탐지' },
  { value: 'SEGMENTATION',   label: 'Segmentation',     desc: '픽셀 단위 영역 분할' },
  {
    value: 'CLASSIFICATION',
    label: 'Classification',
    desc: '이미지 전체 분류, Multi-Head 가능 (예시 : 객체 상의색상, 하의색상 등 다중 속성 분류)',
  },
  { value: 'ZERO_SHOT',      label: 'Zero-Shot',        desc: '제로샷 인식' },
]

const ANNOTATION_FORMAT_OPTIONS: { value: AnnotationFormat; label: string; desc: string }[] = [
  { value: 'COCO',       label: 'COCO JSON',     desc: 'instances_*.json, COCO 표준 포맷' },
  { value: 'YOLO',       label: 'YOLO txt',      desc: '클래스별 .txt 라벨 파일' },
  { value: 'ATTR_JSON',  label: 'Attribute JSON', desc: '속성 분류용 커스텀 JSON' },
  { value: 'CLS_FOLDER', label: 'Class Folder',  desc: '폴더명 = 클래스명 구조' },
  { value: 'CUSTOM',     label: 'Custom',        desc: '기타 포맷 (직접 관리)' },
  { value: 'NONE',       label: '미정',          desc: '포맷 미확정 (나중에 설정)' },
]

const FORMAT_TAG_COLOR: Record<string, string> = {
  COCO: 'green', YOLO: 'orange', ATTR_JSON: 'cyan',
  CLS_FOLDER: 'geekblue', CUSTOM: 'purple', NONE: 'default',
}

/** 신규 그룹 생성 옵션의 sentinel 값 */
const NEW_GROUP_SENTINEL = '__NEW_GROUP__'

/** 같은 폴더 내 파일이 이 수를 넘으면 폴더 단위로 축약 표시 */
const FOLDER_COLLAPSE_THRESHOLD = 5

/**
 * 어노테이션 파일 목록을 폴더별로 그룹핑.
 * 같은 폴더의 파일이 FOLDER_COLLAPSE_THRESHOLD 이하면 개별 표시,
 * 초과하면 폴더 단위로 축약 표시.
 */
interface AnnotationDisplayItem {
  /** 'file' = 개별 파일 표시, 'folder' = 폴더 축약 표시 */
  type: 'file' | 'folder'
  /** file: 전체 경로, folder: 폴더 경로 */
  path: string
  /** file: 파일명, folder: 폴더명 */
  displayName: string
  /** folder일 때 포함된 파일 수 */
  fileCount?: number
  /** folder일 때 포함된 파일 경로 목록 (삭제 시 사용) */
  filePaths?: string[]
}

function groupAnnotationFilesForDisplay(filePaths: string[]): AnnotationDisplayItem[] {
  // 폴더별로 파일 그룹핑
  const folderMap = new Map<string, string[]>()
  for (const filePath of filePaths) {
    const lastSlashIndex = filePath.lastIndexOf('/')
    const folderPath = lastSlashIndex >= 0 ? filePath.substring(0, lastSlashIndex) : ''
    const existing = folderMap.get(folderPath)
    if (existing) {
      existing.push(filePath)
    } else {
      folderMap.set(folderPath, [filePath])
    }
  }

  const result: AnnotationDisplayItem[] = []
  for (const [folderPath, files] of folderMap) {
    if (files.length > FOLDER_COLLAPSE_THRESHOLD) {
      // 폴더 단위 축약 표시
      const folderName = folderPath.split('/').pop() || folderPath
      result.push({
        type: 'folder',
        path: folderPath,
        displayName: folderName,
        fileCount: files.length,
        filePaths: files,
      })
    } else {
      // 개별 파일 표시
      for (const filePath of files) {
        result.push({
          type: 'file',
          path: filePath,
          displayName: filePath.split('/').pop() || filePath,
        })
      }
    }
  }
  return result
}

const SPLIT_OPTIONS = ['TRAIN', 'VAL', 'TEST', 'NONE'] as const

// ─── 컴포넌트 ─────────────────────────────────────────────────────────────────

export default function DatasetRegisterModal({ open, onClose, onSuccess, existingGroup }: Props) {
  const [form] = Form.useForm()
  const [currentStep, setCurrentStep] = useState(0)
  // 사용 목적은 단일 선택 (Step 0). 선택 전까진 null.
  const [selectedTaskType, setSelectedTaskType] = useState<TaskType | null>(null)
  const [selectedFormat, setSelectedFormat] = useState<AnnotationFormat>('NONE')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 파일 선택 상태
  const [imageDir, setImageDir] = useState<string | null>(null)
  const [annotationFiles, setAnnotationFiles] = useState<string[]>([])
  const [annotationMetaFile, setAnnotationMetaFile] = useState<string | null>(null)

  // Classification 전용: 데이터셋 루트 + 2레벨 스캔 결과
  const [classificationRootDir, setClassificationRootDir] = useState<string | null>(null)
  const [classificationScan, setClassificationScan] = useState<ClassificationScanResponse | null>(null)
  const [classificationScanLoading, setClassificationScanLoading] = useState(false)
  const [classificationScanError, setClassificationScanError] = useState<string | null>(null)
  const [classificationRootBrowserOpen, setClassificationRootBrowserOpen] = useState(false)

  // 파일 브라우저 열림 상태
  const [imageBrowserOpen, setImageBrowserOpen] = useState(false)
  const [annotationBrowserOpen, setAnnotationBrowserOpen] = useState(false)
  const [metaFileBrowserOpen, setMetaFileBrowserOpen] = useState(false)

  // CLASSIFICATION이면 이미지/어노테이션 입력 대신 단일 루트 폴더 방식으로 전환한다.
  // 현재는 폴더 구조를 긁어와 읽기 전용으로 표시하는 단계까지만 제공하며,
  // 클래스 순서 지정·manifest 생성 등 후속 로직은 UI 확정 후 추가한다.
  const isClassification = selectedTaskType === 'CLASSIFICATION'

  // 포맷 검증 상태
  const [formatValidating, setFormatValidating] = useState(false)
  const [formatValidationResult, setFormatValidationResult] = useState<FormatValidateResponse | null>(null)

  // 버전 미리보기
  const [nextVersion, setNextVersion] = useState<string>('1.0')

  // 기존 그룹 목록 (드롭다운용)
  const [existingGroupList, setExistingGroupList] = useState<DatasetGroup[]>([])
  const [groupListLoading, setGroupListLoading] = useState(false)
  // 그룹 선택 상태: sentinel이면 신규 생성, group_id면 기존 그룹 선택
  const [selectedGroupOption, setSelectedGroupOption] = useState<string>(NEW_GROUP_SENTINEL)

  // 모달 열릴 때 기존 그룹 목록 fetch
  useEffect(() => {
    if (!open) return
    if (existingGroup) return  // "Split 추가" 버튼으로 열린 경우 fetch 불필요
    setGroupListLoading(true)
    datasetGroupsApi
      .list({ page: 1, page_size: 200 })
      .then(res => {
        const sorted = [...res.data.items].sort((a, b) => a.name.localeCompare(b.name))
        setExistingGroupList(sorted)
      })
      .catch(() => setExistingGroupList([]))
      .finally(() => setGroupListLoading(false))
  }, [open, existingGroup])

  // CLASSIFICATION은 루트 폴더 + 스캔 결과 1개 이상이면 다음 단계 진행 가능.
  // 그 외(Detection 등)는 기존처럼 이미지 폴더 + 어노테이션 파일이 필요하다.
  const isStep1Ready = isClassification
    ? classificationRootDir !== null && classificationScan !== null && classificationScan.heads.length > 0
    : imageDir !== null && annotationFiles.length > 0
  const isNewGroup = selectedGroupOption === NEW_GROUP_SENTINEL

  /** 선택된 루트 폴더를 백엔드에 스캔 요청. 결과는 읽기 전용으로 표시. */
  const runClassificationScan = async (rootPath: string) => {
    setClassificationScanLoading(true)
    setClassificationScanError(null)
    setClassificationScan(null)
    try {
      const res = await fileBrowserApi.classificationScan(rootPath)
      setClassificationScan(res.data)
      if (res.data.heads.length === 0) {
        setClassificationScanError('루트 아래에서 Head 폴더를 찾을 수 없습니다.')
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setClassificationScanError(
        typeof detail === 'string' ? detail : '폴더 스캔 중 오류가 발생했습니다.',
      )
    } finally {
      setClassificationScanLoading(false)
    }
  }

  /** 그룹+split 조합이 바뀔 때 다음 버전 조회 */
  const fetchNextVersion = (groupId: string | null, split: string) => {
    if (!groupId) {
      // 신규 그룹이면 항상 1.0
      setNextVersion('1.0')
      return
    }
    datasetGroupsApi
      .nextVersion(groupId, split)
      .then(res => setNextVersion(res.data.version))
      .catch(() => setNextVersion('1.0'))
  }

  // ── 등록 ─────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    try {
      await form.validateFields()
    } catch {
      return
    }
    if (!imageDir || annotationFiles.length === 0) {
      setSubmitError('이미지 폴더와 어노테이션 파일을 선택하세요.')
      return
    }
    const values = form.getFieldsValue()
    setSubmitting(true)
    setSubmitError(null)
    try {
      // 그룹 ID 결정: existingGroup prop > 드롭다운 기존 그룹 선택 > 신규 생성
      let resolvedGroupId: string | undefined = existingGroup?.id
      let resolvedGroupName: string | undefined
      if (!existingGroup) {
        if (isNewGroup) {
          resolvedGroupName = values.group_name
        } else {
          resolvedGroupId = selectedGroupOption
        }
      }

      // 복사 대상 경로 (안내 메시지용)
      const displayGroupName = existingGroup?.name
        ?? resolvedGroupName
        ?? existingGroupList.find(g => g.id === resolvedGroupId)?.name
        ?? '?'
      const splitDir = (values.split as string).toLowerCase()
      const destPath = `raw/${displayGroupName}/${splitDir}/${nextVersion}`

      // 사용 목적은 UI상 단일 선택이지만, 백엔드 스키마(task_types: list[str])는 유지하여
      // 단일 원소 리스트로 전달한다. 추후 "추가 지원 용도" 멀티선택을 도입할 경우에도
      // 동일 필드를 재사용할 수 있다.
      const singleTaskType = values.task_type as TaskType
      const payload = {
        group_id:                resolvedGroupId,
        group_name:              resolvedGroupName,
        task_types:              [singleTaskType],
        annotation_format:       (values.annotation_format ?? 'NONE') as AnnotationFormat,
        modality:                'RGB' as const,
        description:             values.description,
        split:                   values.split,
        source_image_dir:        imageDir,
        source_annotation_files: annotationFiles,
        source_annotation_meta_file: annotationMetaFile ?? undefined,
      }

      // 백엔드가 즉시 응답 (202) — 파일 복사는 Celery에서 비동기 수행
      const res = await datasetGroupsApi.register(payload)
      onSuccess(res.data)

      // 안내 모달 표시 후 닫기
      Modal.info({
        title: '데이터셋 등록 접수 완료',
        content: (
          <div>
            <p>파일 복사가 진행 중입니다. 완료까지 시간이 걸릴 수 있습니다.</p>
            <p>데이터셋 목록에서 상태를 확인하세요.</p>
            <p style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
              복사 대상: <code>{destPath}</code>
              <br />
              <code>ls {destPath}</code> 로 진행 상황을 확인할 수 있습니다.
            </p>
          </div>
        ),
        okText: '확인',
      })
      handleClose()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setSubmitError(typeof detail === 'string' ? detail : '등록 중 오류가 발생했습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  // ── 포맷 검증 ────────────────────────────────────────────────────────────
  const handleFormatValidation = async () => {
    if (annotationFiles.length === 0) return
    setFormatValidating(true)
    setFormatValidationResult(null)
    try {
      const res = await datasetGroupsApi.validateFormat({
        annotation_format: selectedFormat,
        annotation_files: annotationFiles,
        annotation_meta_file: annotationMetaFile ?? undefined,
      })
      setFormatValidationResult(res.data)
    } catch {
      setFormatValidationResult({
        valid: false,
        errors: ['검증 요청 중 오류가 발생했습니다.'],
        summary: null,
      })
    } finally {
      setFormatValidating(false)
    }
  }

  /** COCO/YOLO만 자동 검증 지원 */
  const isFormatValidatable = selectedFormat === 'COCO' || selectedFormat === 'YOLO'

  const handleClose = () => {
    form.resetFields()
    setCurrentStep(0)
    setSelectedTaskType(null)
    setSelectedFormat('NONE')
    setSubmitError(null)
    setImageDir(null)
    setAnnotationFiles([])
    setAnnotationMetaFile(null)
    setClassificationRootDir(null)
    setClassificationScan(null)
    setClassificationScanError(null)
    setClassificationScanLoading(false)
    setSelectedGroupOption(NEW_GROUP_SENTINEL)
    setFormatValidationResult(null)
    setNextVersion('1.0')
    onClose()
  }

  return (
    <>
      <Modal
        title="데이터셋 등록"
        open={open}
        onCancel={handleClose}
        width={660}
        footer={null}
        destroyOnClose
      >
        <Steps
          current={currentStep}
          size="small"
          style={{ marginBottom: 24 }}
          items={[
            { title: '사용 목적 선택', icon: <AppstoreOutlined /> },
            { title: '파일 선택' },
            { title: '포맷 & 등록' },
          ]}
        />

        <Form form={form} layout="vertical">

          {/* ── Step 0: 사용 목적 선택 (단일 선택) ── */}
          <Form.Item
            label={
              <Space>
                <Text strong>사용 목적 (Task Type)</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>필수 · 1개 선택</Text>
              </Space>
            }
            name="task_type"
            rules={[{ required: true, message: '사용 목적을 선택하세요.' }]}
          >
            <Select
              placeholder="사용 목적을 선택하세요"
              onChange={(value: TaskType) => {
                setSelectedTaskType(value)
                if (currentStep > 0) setCurrentStep(1)
              }}
            >
              {TASK_TYPE_OPTIONS.map(opt => (
                <Option key={opt.value} value={opt.value}>
                  <Space>
                    <Text strong>{opt.label}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>— {opt.desc}</Text>
                  </Space>
                </Option>
              ))}
            </Select>
          </Form.Item>

          <Button
            type="primary"
            block
            disabled={selectedTaskType === null}
            onClick={() => {
              form.validateFields(['task_type']).then(() => setCurrentStep(1)).catch(() => {})
            }}
            style={{ marginBottom: 20 }}
          >
            다음 단계 →
          </Button>

          {/* ── Step 1: 파일 선택 ── */}
          {currentStep >= 1 && isClassification && (
            <>
              <Divider style={{ margin: '4px 0 16px' }} />

              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message="Classification 데이터셋"
                description={
                  <Text style={{ fontSize: 12 }}>
                    데이터셋 루트를 선택하면 <code>&lt;head&gt;/&lt;class&gt;/&lt;이미지&gt;</code> 2레벨 구조로
                    폴더를 스캔합니다. 폴더명 규약은 해석하지 않고 구조만 그대로 읽어옵니다.
                  </Text>
                }
              />

              {/* 데이터셋 루트 폴더 선택 */}
              <Form.Item label={<Text strong>데이터셋 루트 폴더</Text>} required>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    icon={<FolderOpenOutlined />}
                    onClick={() => setClassificationRootBrowserOpen(true)}
                  >
                    폴더 선택
                  </Button>
                  {classificationRootDir && (
                    <Tag
                      color="blue"
                      closable
                      onClose={() => {
                        setClassificationRootDir(null)
                        setClassificationScan(null)
                        setClassificationScanError(null)
                      }}
                      icon={<FolderOpenOutlined />}
                      style={{ maxWidth: 560 }}
                    >
                      {classificationRootDir}
                    </Tag>
                  )}
                </Space>
              </Form.Item>

              {/* 스캔 진행 / 오류 표시 */}
              {classificationScanLoading && (
                <div style={{ marginBottom: 12 }}>
                  <Spin size="small" /> <Text type="secondary" style={{ fontSize: 12 }}>폴더 구조 분석 중...</Text>
                </div>
              )}
              {classificationScanError && !classificationScanLoading && (
                <Alert
                  type="warning"
                  showIcon
                  message={classificationScanError}
                  style={{ marginBottom: 12 }}
                />
              )}

              {/* 스캔 결과 (읽기 전용 트리) */}
              {classificationScan && classificationScan.heads.length > 0 && !classificationScanLoading && (
                <div style={{ marginBottom: 16 }}>
                  <Text strong style={{ fontSize: 13 }}>발견된 구조</Text>
                  <div
                    style={{
                      marginTop: 6,
                      border: '1px solid #f0f0f0',
                      borderRadius: 6,
                      padding: '10px 12px',
                      background: '#fafafa',
                      maxHeight: 260,
                      overflowY: 'auto',
                    }}
                  >
                    {classificationScan.heads.map((head) => (
                      <div key={head.path} style={{ marginBottom: 10 }}>
                        <Space size={6}>
                          <FolderOpenOutlined style={{ color: '#1677ff' }} />
                          <Text strong>{head.name}</Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            (class {head.classes.length}개)
                          </Text>
                        </Space>
                        <div style={{ marginLeft: 22, marginTop: 4 }}>
                          {head.classes.length === 0 ? (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              하위 class 폴더가 없습니다.
                            </Text>
                          ) : (
                            head.classes.map((cls) => (
                              <div key={cls.path} style={{ fontSize: 12 }}>
                                <Space size={6}>
                                  <Text>{cls.name}</Text>
                                  <Text type="secondary" style={{ fontSize: 11 }}>
                                    {cls.image_count.toLocaleString()}장
                                  </Text>
                                </Space>
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Split */}
              <Form.Item label="Split" name="split" initialValue="NONE" rules={[{ required: true }]}>
                <Radio.Group
                  onChange={(e) => {
                    const newSplit = e.target.value
                    const groupId = existingGroup?.id
                      ?? (selectedGroupOption !== NEW_GROUP_SENTINEL ? selectedGroupOption : null)
                    fetchNextVersion(groupId, newSplit)
                  }}
                >
                  {SPLIT_OPTIONS.map(s => <Radio.Button key={s} value={s}>{s}</Radio.Button>)}
                </Radio.Group>
              </Form.Item>

              <Button
                type="primary"
                block
                disabled={!isStep1Ready}
                onClick={() => {
                  setCurrentStep(2)
                  const currentSplit = form.getFieldValue('split') || 'NONE'
                  if (existingGroup) {
                    fetchNextVersion(existingGroup.id, currentSplit)
                  } else if (selectedGroupOption !== NEW_GROUP_SENTINEL) {
                    fetchNextVersion(selectedGroupOption, currentSplit)
                  } else {
                    setNextVersion('1.0')
                  }
                }}
                style={{ marginBottom: 4 }}
              >
                다음 단계 →
              </Button>
              {!isStep1Ready && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  데이터셋 루트 폴더를 선택하고 스캔 결과를 확인해야 합니다.
                </Text>
              )}
            </>
          )}

          {currentStep >= 1 && !isClassification && (
            <>
              <Divider style={{ margin: '4px 0 16px' }} />

              {/* 이미지 폴더 선택 */}
              <Form.Item
                label={<Text strong>이미지 폴더</Text>}
                required
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    icon={<FolderOpenOutlined />}
                    onClick={() => setImageBrowserOpen(true)}
                  >
                    폴더 선택
                  </Button>
                  {imageDir && (
                    <Space>
                      <Tag
                        color="blue"
                        closable
                        onClose={() => setImageDir(null)}
                        icon={<FolderOpenOutlined />}
                        style={{ maxWidth: 500, overflow: 'hidden', textOverflow: 'ellipsis' }}
                      >
                        {imageDir}
                      </Tag>
                    </Space>
                  )}
                </Space>
              </Form.Item>

              {/* 어노테이션 파일 선택 */}
              <Form.Item
                label={
                  <Space>
                    <Text strong>어노테이션 파일</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>복수 선택 가능</Text>
                  </Space>
                }
                required
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    icon={<FileOutlined />}
                    onClick={() => setAnnotationBrowserOpen(true)}
                  >
                    파일 선택
                  </Button>
                  {annotationFiles.length > 0 && (
                    <Space wrap size={4}>
                      {groupAnnotationFilesForDisplay(annotationFiles).map(item =>
                        item.type === 'folder' ? (
                          <Tag
                            key={`folder:${item.path}`}
                            color="gold"
                            closable
                            onClose={() =>
                              setAnnotationFiles(prev =>
                                prev.filter(f => !item.filePaths?.includes(f))
                              )
                            }
                            icon={<FolderOpenOutlined />}
                          >
                            {item.displayName}/ ({item.fileCount?.toLocaleString()}개 파일)
                          </Tag>
                        ) : (
                          <Tag
                            key={item.path}
                            closable
                            onClose={() => setAnnotationFiles(prev => prev.filter(x => x !== item.path))}
                            icon={<FileOutlined />}
                          >
                            {item.displayName}
                          </Tag>
                        )
                      )}
                      <Button
                        size="small"
                        type="link"
                        danger
                        icon={<CloseCircleOutlined />}
                        onClick={() => setAnnotationFiles([])}
                      >
                        전체 삭제
                      </Button>
                    </Space>
                  )}
                </Space>
              </Form.Item>

              {/* 어노테이션 메타 파일 (선택사항) */}
              <Form.Item
                label={
                  <Space>
                    <Text strong>어노테이션 메타 파일</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>선택사항 (예: data.yaml)</Text>
                  </Space>
                }
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    icon={<FileOutlined />}
                    onClick={() => setMetaFileBrowserOpen(true)}
                  >
                    파일 선택
                  </Button>
                  {annotationMetaFile && (
                    <Tag
                      closable
                      onClose={() => setAnnotationMetaFile(null)}
                      icon={<FileOutlined />}
                    >
                      {annotationMetaFile.split('/').pop()}
                    </Tag>
                  )}
                </Space>
              </Form.Item>

              {/* Split */}
              <Form.Item label="Split" name="split" initialValue="NONE" rules={[{ required: true }]}>
                <Radio.Group
                  onChange={(e) => {
                    // Split 변경 시 버전 미리보기 갱신
                    const newSplit = e.target.value
                    const groupId = existingGroup?.id
                      ?? (selectedGroupOption !== NEW_GROUP_SENTINEL ? selectedGroupOption : null)
                    fetchNextVersion(groupId, newSplit)
                  }}
                >
                  {SPLIT_OPTIONS.map(s => <Radio.Button key={s} value={s}>{s}</Radio.Button>)}
                </Radio.Group>
              </Form.Item>

              <Button
                type="primary"
                block
                disabled={!isStep1Ready}
                onClick={() => {
                  setCurrentStep(2)
                  // Step 2 진입 시 버전 미리보기 조회
                  const currentSplit = form.getFieldValue('split') || 'NONE'
                  if (existingGroup) {
                    fetchNextVersion(existingGroup.id, currentSplit)
                  } else if (selectedGroupOption !== NEW_GROUP_SENTINEL) {
                    fetchNextVersion(selectedGroupOption, currentSplit)
                  } else {
                    setNextVersion('1.0')
                  }
                }}
                style={{ marginBottom: 4 }}
              >
                다음 단계 →
              </Button>
              {!isStep1Ready && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  이미지 폴더와 어노테이션 파일을 모두 선택해야 합니다.
                </Text>
              )}
            </>
          )}

          {/* ── Step 2: Annotation format + 그룹 정보 ── */}
          {currentStep >= 2 && (
            <>
              <Divider style={{ margin: '16px 0' }} />

              {/* Classification은 어노테이션 파일 대신 폴더 구조로 라벨이 결정되므로
                  이 단계에서 포맷을 고르지 않는다. 추후 CLS_FOLDER/manifest 저장이
                  확정되면 여기 정보를 다시 노출할 수 있다. */}
              {!isClassification && (
              <>
              <Form.Item
                label={
                  <Space>
                    <Text strong>Annotation Format</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>미정이면 "미정(NONE)" 선택 가능</Text>
                  </Space>
                }
                name="annotation_format"
                initialValue="NONE"
                rules={[{ required: true, message: 'Annotation 포맷을 선택하세요.' }]}
              >
                <Select
                  placeholder="포맷을 선택하세요"
                  onChange={(v: AnnotationFormat) => {
                    setSelectedFormat(v)
                    setFormatValidationResult(null)
                  }}
                >
                  {ANNOTATION_FORMAT_OPTIONS.map(opt => (
                    <Option key={opt.value} value={opt.value}>
                      <Space>
                        <Tag color={FORMAT_TAG_COLOR[opt.value]} style={{ margin: 0 }}>
                          {opt.value}
                        </Tag>
                        <Text type="secondary" style={{ fontSize: 12 }}>{opt.desc}</Text>
                      </Space>
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              {/* 포맷 검증 버튼 + 결과 */}
              {isFormatValidatable && annotationFiles.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <Button
                    icon={<SafetyCertificateOutlined />}
                    loading={formatValidating}
                    onClick={handleFormatValidation}
                    style={{ marginBottom: 8 }}
                  >
                    포맷 검증
                  </Button>

                  {formatValidationResult && (
                    formatValidationResult.valid ? (
                      <Alert
                        type="success"
                        showIcon
                        icon={<CheckCircleOutlined />}
                        message="포맷 검증 통과"
                        description={
                          formatValidationResult.summary && (
                            <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
                              {formatValidationResult.summary.total_image_count != null && (
                                <Descriptions.Item label="이미지 수">
                                  {(formatValidationResult.summary.total_image_count as number).toLocaleString()}장
                                </Descriptions.Item>
                              )}
                              {formatValidationResult.summary.total_annotation_count != null && (
                                <Descriptions.Item label="어노테이션 수">
                                  {(formatValidationResult.summary.total_annotation_count as number).toLocaleString()}개
                                </Descriptions.Item>
                              )}
                              {formatValidationResult.summary.total_file_count != null && (
                                <Descriptions.Item label="검사 파일">
                                  {formatValidationResult.summary.is_sampled
                                    ? `${(formatValidationResult.summary.sampled_file_count as number).toLocaleString()}개 샘플 / 전체 ${(formatValidationResult.summary.total_file_count as number).toLocaleString()}개`
                                    : `${(formatValidationResult.summary.total_file_count as number).toLocaleString()}개`
                                  }
                                </Descriptions.Item>
                              )}
                              {formatValidationResult.summary.total_label_count != null && (
                                <Descriptions.Item label="라벨 수">
                                  {(formatValidationResult.summary.total_label_count as number).toLocaleString()}개
                                  {formatValidationResult.summary.is_sampled && (
                                    <Text type="secondary" style={{ fontSize: 11 }}> (샘플 기준)</Text>
                                  )}
                                </Descriptions.Item>
                              )}
                              {formatValidationResult.summary.categories != null && (
                                <Descriptions.Item label="카테고리">
                                  <Space wrap size={4}>
                                    {(formatValidationResult.summary.categories as string[]).map(
                                      (cat) => <Tag key={cat}>{cat}</Tag>
                                    )}
                                  </Space>
                                </Descriptions.Item>
                              )}
                              {formatValidationResult.summary.class_count != null &&
                                formatValidationResult.summary.unique_class_ids != null && (
                                <Descriptions.Item label="클래스">
                                  {formatValidationResult.summary.class_count as number}개
                                  (ID: {(formatValidationResult.summary.unique_class_ids as number[]).join(', ')})
                                </Descriptions.Item>
                              )}
                            </Descriptions>
                          )
                        }
                        closable
                        onClose={() => setFormatValidationResult(null)}
                      />
                    ) : (
                      <Alert
                        type="warning"
                        showIcon
                        message="포맷 검증 실패"
                        description={
                          <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
                            {formatValidationResult.errors.map((err, idx) => (
                              <li key={idx}><Text type="danger" style={{ fontSize: 12 }}>{err}</Text></li>
                            ))}
                          </ul>
                        }
                        closable
                        onClose={() => setFormatValidationResult(null)}
                      />
                    )
                  )}
                </div>
              )}
              </>
              )}

              <Divider dashed style={{ margin: '12px 0' }} />

              {existingGroup ? (
                <Alert
                  type="info"
                  message={`기존 그룹에 추가: "${existingGroup.name}"`}
                  style={{ marginBottom: 16 }}
                />
              ) : (
                <>
                  <Form.Item
                    label="데이터셋 그룹"
                    required
                    extra={<Text type="secondary" style={{ fontSize: 12 }}>같은 데이터셋의 TRAIN/VAL/TEST를 묶는 단위</Text>}
                  >
                    <Spin spinning={groupListLoading} size="small">
                      <Select
                        showSearch
                        value={selectedGroupOption}
                        onChange={(value: string) => {
                          setSelectedGroupOption(value)
                          // 기존 그룹 선택 시 group_name 필드 초기화
                          if (value !== NEW_GROUP_SENTINEL) {
                            form.setFieldValue('group_name', undefined)
                          }
                          // 그룹 변경 시 버전 미리보기 갱신
                          const currentSplit = form.getFieldValue('split') || 'NONE'
                          fetchNextVersion(
                            value === NEW_GROUP_SENTINEL ? null : value,
                            currentSplit,
                          )
                        }}
                        optionFilterProp="label"
                        placeholder="기존 그룹 선택 또는 새로 만들기"
                      >
                        <Option key={NEW_GROUP_SENTINEL} value={NEW_GROUP_SENTINEL} label="새 그룹 만들기">
                          <Space>
                            <PlusOutlined style={{ color: '#1677ff' }} />
                            <Text strong style={{ color: '#1677ff' }}>새 그룹 만들기</Text>
                          </Space>
                        </Option>
                        {existingGroupList.map(group => (
                          <Option key={group.id} value={group.id} label={group.name}>
                            <Space>
                              <Text>{group.name}</Text>
                              <Text type="secondary" style={{ fontSize: 11 }}>
                                ({group.datasets.length}개 split)
                              </Text>
                            </Space>
                          </Option>
                        ))}
                      </Select>
                    </Spin>
                  </Form.Item>
                  <Form.Item
                    label="새 그룹명"
                    name="group_name"
                    rules={[{ required: isNewGroup, message: '그룹명을 입력하세요.' }]}
                  >
                    <Input
                      placeholder={isNewGroup ? '예: my_dataset_2024' : '위 드롭다운에서 "새 그룹 만들기"를 선택하세요'}
                      disabled={!isNewGroup}
                    />
                  </Form.Item>
                </>
              )}

              <Form.Item label="설명 (선택)" name="description">
                <Input.TextArea rows={2} placeholder="데이터셋 설명을 입력하세요." />
              </Form.Item>

              {/* 선택 요약 */}
              <Descriptions size="small" bordered column={1} style={{ marginBottom: 16 }}>
                <Descriptions.Item label="사용 목적">
                  {selectedTaskType && <Tag color="purple">{selectedTaskType}</Tag>}
                </Descriptions.Item>
                {isClassification ? (
                  <>
                    <Descriptions.Item label="데이터셋 루트">
                      <Text code style={{ fontSize: 11 }}>{classificationRootDir}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="스캔 결과">
                      {classificationScan && (
                        <Space direction="vertical" size={2}>
                          {classificationScan.heads.map((head) => (
                            <Text key={head.path} style={{ fontSize: 12 }}>
                              <Text strong>{head.name}</Text>
                              <Text type="secondary"> — class {head.classes.length}개 / 이미지 </Text>
                              {head.classes.reduce((sum, cls) => sum + cls.image_count, 0).toLocaleString()}장
                            </Text>
                          ))}
                        </Space>
                      )}
                    </Descriptions.Item>
                  </>
                ) : (
                  <>
                    <Descriptions.Item label="이미지 폴더">
                      <Text code style={{ fontSize: 11 }}>{imageDir}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="어노테이션 파일">
                      <Space wrap size={4}>
                        {groupAnnotationFilesForDisplay(annotationFiles).map(item =>
                          item.type === 'folder' ? (
                            <Tag key={`folder:${item.path}`} icon={<FolderOpenOutlined />} color="gold">
                              {item.displayName}/ ({item.fileCount?.toLocaleString()}개)
                            </Tag>
                          ) : (
                            <Tag key={item.path} icon={<FileOutlined />}>{item.displayName}</Tag>
                          )
                        )}
                      </Space>
                    </Descriptions.Item>
                    {annotationMetaFile && (
                      <Descriptions.Item label="어노테이션 메타 파일">
                        <Tag icon={<FileOutlined />} color="geekblue">
                          {annotationMetaFile.split('/').pop()}
                        </Tag>
                      </Descriptions.Item>
                    )}
                    <Descriptions.Item label="Annotation Format">
                      <Tag color={FORMAT_TAG_COLOR[selectedFormat] ?? 'default'}>{selectedFormat}</Tag>
                    </Descriptions.Item>
                  </>
                )}
                <Descriptions.Item label="버전">
                  <Tag color="blue">{nextVersion}</Tag>
                  <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>자동 생성</Text>
                </Descriptions.Item>
              </Descriptions>

              {submitError && (
                <Alert type="error" message={submitError} showIcon style={{ marginBottom: 16 }} />
              )}

              {isClassification && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="Classification 등록 로직은 아직 연결되지 않았습니다"
                  description={
                    <Text style={{ fontSize: 12 }}>
                      현재는 폴더 구조 스캔 결과를 확인하는 단계까지만 제공합니다.
                      클래스 순서 확정, 이미지 중복 처리, manifest 생성 등 등록 파이프라인은
                      UI 확정 후 추가될 예정입니다.
                    </Text>
                  }
                />
              )}

              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Button onClick={handleClose} disabled={submitting}>취소</Button>
                <Button
                  type="primary"
                  loading={submitting}
                  onClick={handleSubmit}
                  disabled={isClassification}
                >
                  데이터셋 등록
                </Button>
              </Space>
            </>
          )}
        </Form>
      </Modal>

      {/* ── 이미지 폴더 브라우저 ── */}
      <ServerFileBrowser
        open={imageBrowserOpen}
        onClose={() => setImageBrowserOpen(false)}
        onSelect={(paths) => setImageDir(paths[0])}
        mode="directory"
        title="이미지 폴더 선택"
      />

      {/* ── 어노테이션 파일 브라우저 ── */}
      <ServerFileBrowser
        open={annotationBrowserOpen}
        onClose={() => setAnnotationBrowserOpen(false)}
        onSelect={(paths) => setAnnotationFiles(prev => {
          const merged = [...new Set([...prev, ...paths])]
          return merged
        })}
        mode="file"
        multiple
        title="어노테이션 파일 선택"
      />

      {/* ── 어노테이션 메타 파일 브라우저 ── */}
      <ServerFileBrowser
        open={metaFileBrowserOpen}
        onClose={() => setMetaFileBrowserOpen(false)}
        onSelect={(paths) => setAnnotationMetaFile(paths[0])}
        mode="file"
        title="어노테이션 메타 파일 선택 (예: data.yaml)"
      />

      {/* ── Classification 루트 폴더 브라우저 ── */}
      <ServerFileBrowser
        open={classificationRootBrowserOpen}
        onClose={() => setClassificationRootBrowserOpen(false)}
        onSelect={(paths) => {
          const picked = paths[0]
          setClassificationRootDir(picked)
          // 폴더 선택 즉시 스캔 실행 (결과는 읽기 전용으로 표시만 함)
          void runClassificationScan(picked)
        }}
        mode="directory"
        title="Classification 데이터셋 루트 폴더 선택"
      />
    </>
  )
}
