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
} from '@ant-design/icons'
import { datasetGroupsApi } from '../../api/dataset'
import ServerFileBrowser from '../common/ServerFileBrowser'
import type { DatasetGroup, TaskType, AnnotationFormat } from '../../types/dataset'

const { Text } = Typography
const { Option } = Select

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (group: DatasetGroup) => void
  existingGroup?: DatasetGroup | null
}

// ─── 상수 ────────────────────────────────────────────────────────────────────

const TASK_TYPE_OPTIONS: { value: TaskType; label: string; desc: string }[] = [
  { value: 'DETECTION',           label: 'Object Detection',         desc: '바운딩 박스 기반 객체 탐지' },
  { value: 'SEGMENTATION',        label: 'Segmentation',             desc: '픽셀 단위 영역 분할' },
  { value: 'CLASSIFICATION',      label: 'Classification',           desc: '이미지 전체 분류' },
  { value: 'ATTR_CLASSIFICATION', label: 'Attribute Classification', desc: '객체별 속성 분류' },
  { value: 'ZERO_SHOT',           label: 'Zero-Shot',                desc: '제로샷 인식' },
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

const SPLIT_OPTIONS = ['TRAIN', 'VAL', 'TEST', 'NONE'] as const

// ─── 컴포넌트 ─────────────────────────────────────────────────────────────────

export default function DatasetRegisterModal({ open, onClose, onSuccess, existingGroup }: Props) {
  const [form] = Form.useForm()
  const [currentStep, setCurrentStep] = useState(0)
  const [selectedTaskTypes, setSelectedTaskTypes] = useState<TaskType[]>([])
  const [selectedFormat, setSelectedFormat] = useState<AnnotationFormat>('NONE')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 파일 선택 상태
  const [imageDir, setImageDir] = useState<string | null>(null)
  const [annotationFiles, setAnnotationFiles] = useState<string[]>([])

  // 파일 브라우저 열림 상태
  const [imageBrowserOpen, setImageBrowserOpen] = useState(false)
  const [annotationBrowserOpen, setAnnotationBrowserOpen] = useState(false)

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

  const isStep1Ready = imageDir !== null && annotationFiles.length > 0
  const isNewGroup = selectedGroupOption === NEW_GROUP_SENTINEL

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
      const payload = {
        group_id:                resolvedGroupId,
        group_name:              resolvedGroupName,
        task_types:              values.task_types as TaskType[],
        annotation_format:       (values.annotation_format ?? 'NONE') as AnnotationFormat,
        modality:                'RGB' as const,
        description:             values.description,
        split:                   values.split,
        source_image_dir:        imageDir,
        source_annotation_files: annotationFiles,
      }
      const res = await datasetGroupsApi.register(payload)
      onSuccess(res.data)
      handleClose()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setSubmitError(typeof detail === 'string' ? detail : '등록 중 오류가 발생했습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    form.resetFields()
    setCurrentStep(0)
    setSelectedTaskTypes([])
    setSelectedFormat('NONE')
    setSubmitError(null)
    setImageDir(null)
    setAnnotationFiles([])
    setSelectedGroupOption(NEW_GROUP_SENTINEL)
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

          {/* ── Step 0: 사용 목적 선택 ── */}
          <Form.Item
            label={
              <Space>
                <Text strong>사용 목적 (Task Type)</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>필수 · 복수 선택 가능</Text>
              </Space>
            }
            name="task_types"
            rules={[{ required: true, message: '사용 목적을 하나 이상 선택하세요.' }]}
          >
            <Select
              mode="multiple"
              placeholder="사용 목적을 선택하세요"
              onChange={(values: TaskType[]) => {
                setSelectedTaskTypes(values)
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
            disabled={selectedTaskTypes.length === 0}
            onClick={() => {
              form.validateFields(['task_types']).then(() => setCurrentStep(1)).catch(() => {})
            }}
            style={{ marginBottom: 20 }}
          >
            다음 단계 →
          </Button>

          {/* ── Step 1: 파일 선택 ── */}
          {currentStep >= 1 && (
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
                      {annotationFiles.map(f => (
                        <Tag
                          key={f}
                          closable
                          onClose={() => setAnnotationFiles(prev => prev.filter(x => x !== f))}
                          icon={<FileOutlined />}
                        >
                          {f.split('/').pop()}
                        </Tag>
                      ))}
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

              {/* Split */}
              <Form.Item label="Split" name="split" initialValue="NONE" rules={[{ required: true }]}>
                <Radio.Group>
                  {SPLIT_OPTIONS.map(s => <Radio.Button key={s} value={s}>{s}</Radio.Button>)}
                </Radio.Group>
              </Form.Item>

              <Button
                type="primary"
                block
                disabled={!isStep1Ready}
                onClick={() => setCurrentStep(2)}
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
                  onChange={(v: AnnotationFormat) => setSelectedFormat(v)}
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
                  <Space wrap size={4}>
                    {selectedTaskTypes.map(t => <Tag key={t} color="purple">{t}</Tag>)}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="이미지 폴더">
                  <Text code style={{ fontSize: 11 }}>{imageDir}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="어노테이션 파일">
                  <Space wrap size={4}>
                    {annotationFiles.map(f => (
                      <Tag key={f} icon={<FileOutlined />}>{f.split('/').pop()}</Tag>
                    ))}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="Annotation Format">
                  <Tag color={FORMAT_TAG_COLOR[selectedFormat] ?? 'default'}>{selectedFormat}</Tag>
                </Descriptions.Item>
              </Descriptions>

              {submitError && (
                <Alert type="error" message={submitError} showIcon style={{ marginBottom: 16 }} />
              )}

              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Button onClick={handleClose}>취소</Button>
                <Button type="primary" loading={submitting} onClick={handleSubmit}>
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
    </>
  )
}
