/**
 * 데이터셋 등록 모달
 *
 * 등록 흐름:
 *   Step 0. 사용 목적(task_types) 선택 (드롭다운)
 *   Step 1. NAS 경로 입력 → "경로 확인" → 경로 존재 여부만 검사
 *   Step 2. Annotation format 선택 + 그룹명 입력 → "등록"
 *           └─ "Check Data Validation" 버튼 → 팝업으로 포맷별 검증 결과 표시
 */
import { useState } from 'react'
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
  Table,
  Spin,
} from 'antd'
import {
  FolderOpenOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
  AppstoreOutlined,
  SafetyOutlined,
  CheckOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import { datasetGroupsApi } from '../../api/dataset'
import type { DatasetGroup, DatasetValidateResponse, TaskType, AnnotationFormat } from '../../types/dataset'

const { Text } = Typography
const { Option } = Select

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (group: DatasetGroup) => void
  existingGroup?: DatasetGroup | null
}

type ValidateStatus = 'idle' | 'loading' | 'success' | 'error'

// ─── 상수 ────────────────────────────────────────────────────────────────────

const TASK_TYPE_OPTIONS: { value: TaskType; label: string; desc: string }[] = [
  { value: 'DETECTION',           label: 'Object Detection',        desc: '바운딩 박스 기반 객체 탐지' },
  { value: 'SEGMENTATION',        label: 'Segmentation',            desc: '픽셀 단위 영역 분할' },
  { value: 'CLASSIFICATION',      label: 'Classification',          desc: '이미지 전체 분류' },
  { value: 'ATTR_CLASSIFICATION', label: 'Attribute Classification', desc: '객체별 속성 분류' },
  { value: 'ZERO_SHOT',           label: 'Zero-Shot',               desc: '제로샷 인식' },
]

const ANNOTATION_FORMAT_OPTIONS: { value: AnnotationFormat; label: string; desc: string }[] = [
  { value: 'COCO',       label: 'COCO JSON',     desc: 'instances_*.json, COCO 표준 포맷' },
  { value: 'YOLO',       label: 'YOLO txt',       desc: '클래스별 .txt 라벨 파일' },
  { value: 'ATTR_JSON',  label: 'Attribute JSON', desc: '속성 분류용 커스텀 JSON' },
  { value: 'CLS_FOLDER', label: 'Class Folder',   desc: '폴더명 = 클래스명 구조' },
  { value: 'CUSTOM',     label: 'Custom',         desc: '기타 포맷 (직접 관리)' },
  { value: 'NONE',       label: '미정',           desc: '포맷 미확정 (나중에 설정)' },
]

const FORMAT_TAG_COLOR: Record<string, string> = {
  COCO: 'green', YOLO: 'orange', ATTR_JSON: 'cyan',
  CLS_FOLDER: 'geekblue', CUSTOM: 'purple', NONE: 'default',
}

const SPLIT_OPTIONS = ['TRAIN', 'VAL', 'TEST', 'NONE'] as const

// ─── 컴포넌트 ─────────────────────────────────────────────────────────────────

export default function DatasetRegisterModal({ open, onClose, onSuccess, existingGroup }: Props) {
  const [form] = Form.useForm()
  const [currentStep, setCurrentStep] = useState(0)
  const [validateStatus, setValidateStatus] = useState<ValidateStatus>('idle')
  const [validateResult, setValidateResult] = useState<DatasetValidateResponse | null>(null)
  const [selectedTaskTypes, setSelectedTaskTypes] = useState<TaskType[]>([])
  const [selectedFormat, setSelectedFormat] = useState<AnnotationFormat>('NONE')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // validation 팝업 state
  const [validationModalOpen, setValidationModalOpen] = useState(false)
  const [validationLoading, setValidationLoading] = useState(false)
  const [validationData, setValidationData] = useState<DatasetValidateResponse | null>(null)

  // ── Step 1: 경로 존재 확인 ────────────────────────────────────────────────
  const handleValidate = async () => {
    const storageUri = form.getFieldValue('storage_uri')
    if (!storageUri?.trim()) {
      form.setFields([{ name: 'storage_uri', errors: ['NAS 경로를 입력하세요.'] }])
      return
    }
    setValidateStatus('loading')
    setValidateResult(null)
    try {
      const res = await datasetGroupsApi.validatePath({ storage_uri: storageUri.trim() })
      setValidateResult(res.data)
      if (res.data.path_exists) {
        setValidateStatus('success')
        setCurrentStep(2)
      } else {
        setValidateStatus('error')
      }
    } catch {
      setValidateStatus('error')
      setValidateResult(null)
    }
  }

  // ── Check Data Validation 팝업 ───────────────────────────────────────────
  const handleCheckValidation = async () => {
    const storageUri = form.getFieldValue('storage_uri')
    if (!storageUri?.trim()) return

    setValidationModalOpen(true)
    setValidationLoading(true)
    setValidationData(null)

    try {
      const res = await datasetGroupsApi.validatePath({ storage_uri: storageUri.trim() })
      setValidationData(res.data)
    } catch {
      setValidationData(null)
    } finally {
      setValidationLoading(false)
    }
  }

  // ── Step 2: 등록 ─────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    try {
      await form.validateFields()
    } catch {
      return
    }
    const values = form.getFieldsValue()
    setSubmitting(true)
    setSubmitError(null)
    try {
      const payload = {
        group_id:          existingGroup?.id,
        group_name:        existingGroup ? undefined : values.group_name,
        task_types:        values.task_types as TaskType[],
        annotation_format: (values.annotation_format ?? 'NONE') as AnnotationFormat,
        modality:          'RGB',
        description:       values.description,
        split:             values.split,
        storage_uri:       values.storage_uri.trim(),
      }
      const res = await datasetGroupsApi.register(payload)
      onSuccess(res.data)
      handleClose()
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setSubmitError(typeof detail === 'string' ? detail : '등록 중 오류가 발생했습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    form.resetFields()
    setCurrentStep(0)
    setValidateStatus('idle')
    setValidateResult(null)
    setSelectedTaskTypes([])
    setSelectedFormat('NONE')
    setSubmitError(null)
    setValidationData(null)
    onClose()
  }

  // ── 경로 확인 결과 렌더링 ─────────────────────────────────────────────────
  const renderValidateResult = () => {
    if (!validateResult) return null
    if (!validateResult.path_exists)
      return (
        <Alert
          type="error" showIcon
          message="경로를 찾을 수 없습니다"
          description={
            <span>
              <Text code>{validateResult.storage_uri}</Text> 경로가 존재하지 않습니다.<br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                .env의 <Text code>LOCAL_STORAGE_BASE</Text> 기준 상대경로인지 확인하세요.
              </Text>
            </span>
          }
        />
      )
    return (
      <Alert
        type="success" showIcon
        message="경로 확인 완료"
        description={
          <Space direction="vertical" size={2} style={{ marginTop: 4 }}>
            <Text>
              이미지: <Text strong>{validateResult.image_count.toLocaleString()}장</Text>
              {!validateResult.images_dir_exists && (
                <Text type="secondary"> (images/ 폴더 없음)</Text>
              )}
            </Text>
            <Text>
              annotation.json:{' '}
              {validateResult.annotation_exists
                ? <Text strong style={{ color: '#52c41a' }}>존재</Text>
                : <Text type="secondary">없음</Text>
              }
            </Text>
          </Space>
        }
      />
    )
  }

  // ── Validation 팝업 컨텐츠 ───────────────────────────────────────────────
  const renderValidationModalContent = () => {
    if (validationLoading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div>
    if (!validationData) return <Alert type="error" message="검증 중 오류가 발생했습니다." showIcon />

    const d = validationData
    const fmt = selectedFormat

    // 공통 체크 항목
    const commonChecks = [
      { key: 'path',        label: '경로 존재',          ok: d.path_exists },
      { key: 'images_dir',  label: 'images/ 폴더',       ok: d.images_dir_exists },
      { key: 'annotation',  label: 'annotation.json',    ok: d.annotation_exists },
    ]

    // 포맷별 추가 체크
    const formatChecks: { key: string; label: string; ok: boolean; desc?: string }[] = []
    if (fmt === 'COCO') {
      formatChecks.push(
        { key: 'coco_valid', label: 'COCO 포맷 정합성', ok: d.coco_valid, desc: d.error ?? undefined },
      )
    }

    const allChecks = [...commonChecks, ...formatChecks]

    return (
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 체크 테이블 */}
        <Table
          dataSource={allChecks}
          rowKey="key"
          pagination={false}
          size="small"
          columns={[
            {
              title: '항목',
              dataIndex: 'label',
              render: (label: string) => <Text strong>{label}</Text>,
            },
            {
              title: '결과',
              dataIndex: 'ok',
              width: 80,
              align: 'center' as const,
              render: (ok: boolean) => ok
                ? <CheckOutlined style={{ color: '#52c41a', fontSize: 16 }} />
                : <CloseOutlined style={{ color: '#ff4d4f', fontSize: 16 }} />,
            },
            {
              title: '비고',
              dataIndex: 'desc',
              render: (desc: string | undefined, row: any) => {
                if (!row.ok && desc) return <Text type="danger" style={{ fontSize: 12 }}>{desc}</Text>
                if (!row.ok) return <Text type="secondary" style={{ fontSize: 12 }}>미충족</Text>
                return <Text type="secondary" style={{ fontSize: 12 }}>OK</Text>
              },
            },
          ]}
        />

        {/* 이미지 통계 */}
        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="이미지 수">
            {d.image_count.toLocaleString()}장
          </Descriptions.Item>
          <Descriptions.Item label="annotation.json">
            {d.annotation_exists ? '있음' : '없음'}
          </Descriptions.Item>
          {fmt === 'COCO' && d.annotation_exists && (
            <>
              <Descriptions.Item label="Annotation 수">
                {d.coco_annotation_count.toLocaleString()}개
              </Descriptions.Item>
              <Descriptions.Item label="클래스 수">
                {d.coco_categories.length}개
              </Descriptions.Item>
              {d.coco_categories.length > 0 && (
                <Descriptions.Item label="클래스 목록" span={2}>
                  <Space wrap size={4}>
                    {d.coco_categories.slice(0, 12).map(c => (
                      <Tag key={c} color="blue">{c}</Tag>
                    ))}
                    {d.coco_categories.length > 12 && (
                      <Text type="secondary">외 {d.coco_categories.length - 12}개</Text>
                    )}
                  </Space>
                </Descriptions.Item>
              )}
            </>
          )}
        </Descriptions>

        {/* 포맷별 안내 */}
        {fmt !== 'COCO' && fmt !== 'NONE' && (
          <Alert
            type="info" showIcon
            message={`${fmt} 포맷 정합성 체크`}
            description={`${fmt} 포맷 전용 검증은 추후 지원 예정입니다. 현재는 경로 및 파일 존재 여부만 확인합니다.`}
          />
        )}
        {fmt === 'NONE' && (
          <Alert
            type="warning" showIcon
            message="포맷 미지정"
            description="Annotation Format을 지정하면 포맷별 정합성 체크를 수행할 수 있습니다."
          />
        )}
      </Space>
    )
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
            { title: '경로 확인', icon: validateStatus === 'loading' ? <LoadingOutlined /> : undefined },
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
                if (currentStep > 0) {
                  setCurrentStep(1)
                  setValidateStatus('idle')
                  setValidateResult(null)
                }
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

          {/* ── Step 1: NAS 경로 입력 ── */}
          {currentStep >= 1 && (
            <>
              <Divider style={{ margin: '4px 0 16px' }} />

              <Alert
                type="info" showIcon
                icon={<InfoCircleOutlined />}
                message="경로 입력 안내"
                description={
                  <ul style={{ margin: '4px 0', paddingLeft: 20, fontSize: 12 }}>
                    <li>.env의 <Text code>LOCAL_STORAGE_BASE</Text> 기준 <Text strong>상대경로</Text>를 입력하세요.</li>
                    <li>예) BASE=./data/my_nas, 실제 경로 <Text code>./data/my_nas/raw/coco/train/v1.0.0</Text> → <Text code>raw/coco/train/v1.0.0</Text></li>
                  </ul>
                }
                style={{ marginBottom: 16 }}
              />

              <Form.Item
                label="NAS 경로 (storage_uri)"
                name="storage_uri"
                rules={[{ required: true, message: 'NAS 경로를 입력하세요.' }]}
                extra={<Text type="secondary" style={{ fontSize: 12 }}>LOCAL_STORAGE_BASE 기준 상대경로</Text>}
              >
                <Input
                  prefix={<FolderOpenOutlined />}
                  placeholder="raw/my_dataset/train/v1.0.0"
                  onChange={() => {
                    setValidateStatus('idle')
                    setValidateResult(null)
                    if (currentStep > 1) setCurrentStep(1)
                  }}
                />
              </Form.Item>

              <Form.Item label="Split" name="split" initialValue="NONE" rules={[{ required: true }]}>
                <Radio.Group>
                  {SPLIT_OPTIONS.map(s => <Radio.Button key={s} value={s}>{s}</Radio.Button>)}
                </Radio.Group>
              </Form.Item>

              <Button
                type="default"
                icon={validateStatus === 'loading' ? <LoadingOutlined /> : <CheckCircleOutlined />}
                loading={validateStatus === 'loading'}
                onClick={handleValidate}
                block
              >
                경로 확인
              </Button>

              <div style={{ marginTop: 12, marginBottom: 4 }}>
                {renderValidateResult()}
              </div>
            </>
          )}

          {/* ── Step 2: Annotation format + 그룹 정보 ── */}
          {validateStatus === 'success' && (
            <>
              <Divider style={{ margin: '16px 0' }} />

              {/* Annotation Format 선택 */}
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

              {/* 그룹 정보 */}
              {existingGroup ? (
                <Alert
                  type="info"
                  message={`기존 그룹에 추가: "${existingGroup.name}"`}
                  style={{ marginBottom: 16 }}
                />
              ) : (
                <Form.Item
                  label="데이터셋 그룹명"
                  name="group_name"
                  rules={[{ required: !existingGroup, message: '그룹명을 입력하세요.' }]}
                  extra={<Text type="secondary" style={{ fontSize: 12 }}>같은 데이터셋의 TRAIN/VAL/TEST를 묶는 단위</Text>}
                >
                  <Input placeholder="예: my_dataset_2024" />
                </Form.Item>
              )}

              <Form.Item label="설명 (선택)" name="description">
                <Input.TextArea rows={2} placeholder="데이터셋 설명을 입력하세요." />
              </Form.Item>

              {/* 선택 요약 */}
              <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
                <Descriptions.Item label="사용 목적">
                  <Space wrap size={4}>
                    {selectedTaskTypes.map(t => <Tag key={t} color="purple">{t}</Tag>)}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="Annotation Format">
                  <Tag color={FORMAT_TAG_COLOR[selectedFormat] ?? 'default'}>
                    {selectedFormat}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>

              {submitError && (
                <Alert type="error" message={submitError} showIcon style={{ marginBottom: 16 }} />
              )}

              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Button onClick={handleClose}>취소</Button>
                <Button
                  icon={<SafetyOutlined />}
                  onClick={handleCheckValidation}
                >
                  Check Data Validation
                </Button>
                <Button type="primary" loading={submitting} onClick={handleSubmit}>
                  데이터셋 등록
                </Button>
              </Space>
            </>
          )}
        </Form>
      </Modal>

      {/* ── Check Data Validation 팝업 ── */}
      <Modal
        title={
          <Space>
            <SafetyOutlined />
            <span>Data Validation</span>
            <Tag color={FORMAT_TAG_COLOR[selectedFormat] ?? 'default'}>{selectedFormat}</Tag>
          </Space>
        }
        open={validationModalOpen}
        onCancel={() => setValidationModalOpen(false)}
        footer={
          <Button type="primary" onClick={() => setValidationModalOpen(false)}>확인</Button>
        }
        width={580}
        destroyOnClose={false}
      >
        {renderValidationModalContent()}
      </Modal>
    </>
  )
}
