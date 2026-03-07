/**
 * 데이터셋 등록 모달
 *
 * 등록 흐름:
 *   Step 0. 사용 목적(task_types) 선택 (드롭다운)
 *   Step 1. NAS 경로 입력 → "경로 확인" → 경로 존재 여부만 검사
 *   Step 2. 그룹명 + annotation format 선택 → "등록"
 *
 * 주의: annotation 정합성 체크는 이 단계에서 수행하지 않음.
 *       추후 별도 단계에서 포맷별로 수행 예정.
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
} from 'antd'
import {
  FolderOpenOutlined,
  CheckCircleOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
  AppstoreOutlined,
} from '@ant-design/icons'
import { datasetGroupsApi } from '../../api/dataset'
import type { DatasetGroup, DatasetValidateResponse, TaskType, AnnotationFormat } from '../../types/dataset'

const { Text } = Typography
const { Option } = Select

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: (group: DatasetGroup) => void
  /** 기존 그룹에 split 추가 시 지정 */
  existingGroup?: DatasetGroup | null
}

type ValidateStatus = 'idle' | 'loading' | 'success' | 'error'

// ─── 상수 정의 ────────────────────────────────────────────────────────────────

const TASK_TYPE_OPTIONS: { value: TaskType; label: string; desc: string }[] = [
  { value: 'DETECTION',           label: 'Object Detection',       desc: '바운딩 박스 기반 객체 탐지' },
  { value: 'SEGMENTATION',        label: 'Segmentation',           desc: '픽셀 단위 영역 분할' },
  { value: 'CLASSIFICATION',      label: 'Classification',         desc: '이미지 전체 분류' },
  { value: 'ATTR_CLASSIFICATION', label: 'Attribute Classification', desc: '객체별 속성 분류' },
  { value: 'ZERO_SHOT',           label: 'Zero-Shot',              desc: '제로샷 인식' },
]

const ANNOTATION_FORMAT_OPTIONS: { value: AnnotationFormat; label: string; desc: string }[] = [
  { value: 'COCO',       label: 'COCO JSON',      desc: 'instances_*.json, COCO 표준 포맷' },
  { value: 'YOLO',       label: 'YOLO txt',        desc: '클래스별 .txt 라벨 파일' },
  { value: 'ATTR_JSON',  label: 'Attribute JSON',  desc: '속성 분류용 커스텀 JSON' },
  { value: 'CLS_FOLDER', label: 'Class Folder',    desc: '폴더명 = 클래스명 구조' },
  { value: 'CUSTOM',     label: 'Custom',          desc: '기타 포맷 (직접 관리)' },
  { value: 'NONE',       label: '미정',            desc: '포맷 미확정 (나중에 설정)' },
]

const SPLIT_OPTIONS = ['TRAIN', 'VAL', 'TEST', 'NONE'] as const

// ─── 컴포넌트 ─────────────────────────────────────────────────────────────────

export default function DatasetRegisterModal({
  open,
  onClose,
  onSuccess,
  existingGroup,
}: Props) {
  const [form] = Form.useForm()
  const [currentStep, setCurrentStep] = useState(0)
  const [validateStatus, setValidateStatus] = useState<ValidateStatus>('idle')
  const [validateResult, setValidateResult] = useState<DatasetValidateResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // ── Step 1: 경로 존재 여부만 확인 (정합성 체크 없음) ──────────────────────
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

  // ── Step 2: 등록 ──────────────────────────────────────────────────────────
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
    setSubmitError(null)
    onClose()
  }

  // ── 경로 검증 결과 렌더링 ──────────────────────────────────────────────────
  const renderValidateResult = () => {
    if (!validateResult) return null

    if (!validateResult.path_exists)
      return (
        <Alert
          type="error"
          showIcon
          message="경로를 찾을 수 없습니다"
          description={
            <span>
              <Text code>{validateResult.storage_uri}</Text> 경로가 존재하지 않습니다.<br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                .env의 <Text code>LOCAL_STORAGE_BASE</Text> 기준 상대경로인지 확인하세요.<br />
                예) LOCAL_STORAGE_BASE=./data/my_nas 이면 → <Text code>raw/dataset_name/train/v1.0.0</Text> 형식
              </Text>
            </span>
          }
        />
      )

    // 경로 존재 → 추가 정보 표시 (images/, annotation.json 존재 여부는 참고용)
    return (
      <Alert
        type="success"
        showIcon
        message="경로 확인 완료"
        description={
          <Space direction="vertical" size={2} style={{ marginTop: 4 }}>
            <Text>
              이미지:{' '}
              <Text strong>{validateResult.image_count.toLocaleString()}장</Text>
              {!validateResult.images_dir_exists && (
                <Text type="secondary"> (images/ 폴더 없음 — 나중에 추가 가능)</Text>
              )}
            </Text>
            <Text>
              annotation.json:{' '}
              {validateResult.annotation_exists
                ? <Text strong style={{ color: '#52c41a' }}>존재</Text>
                : <Text type="secondary">없음 (나중에 추가 가능)</Text>
              }
            </Text>
          </Space>
        }
      />
    )
  }

  return (
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
          { title: '경로 입력 & 확인', icon: validateStatus === 'loading' ? <LoadingOutlined /> : undefined },
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
            onChange={() => {
              // task_types 변경 시 이후 스텝 초기화
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
          type="default"
          block
          disabled={!form.getFieldValue('task_types')?.length}
          onClick={() => {
            form.validateFields(['task_types']).then(() => setCurrentStep(1)).catch(() => {})
          }}
          style={{ marginBottom: 20 }}
        >
          다음 단계 →
        </Button>

        {/* ── Step 1: NAS 경로 입력 (task_types 선택 후 표시) ── */}
        {currentStep >= 1 && (
          <>
            <Divider style={{ margin: '4px 0 16px' }} />

            <Alert
              type="info"
              showIcon
              icon={<InfoCircleOutlined />}
              message="경로 입력 안내"
              description={
                <ul style={{ margin: '4px 0', paddingLeft: 20, fontSize: 12 }}>
                  <li>.env의 <Text code>LOCAL_STORAGE_BASE</Text> 기준 <Text strong>상대경로</Text>를 입력하세요.</li>
                  <li>폴더 구조: <Text code>{'<경로>/images/'}</Text> 와 <Text code>{'<경로>/annotation.json'}</Text></li>
                  <li>예) LOCAL_STORAGE_BASE=./data/my_nas 이고 실제 경로가 <Text code>./data/my_nas/raw/coco/train/v1.0.0</Text> 이면 → <Text code>raw/coco/train/v1.0.0</Text> 입력</li>
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

            <Form.Item label="Split (데이터 분할)" name="split" initialValue="NONE" rules={[{ required: true }]}>
              <Radio.Group>
                {SPLIT_OPTIONS.map(s => (
                  <Radio.Button key={s} value={s}>{s}</Radio.Button>
                ))}
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

        {/* ── Step 2: Annotation format + 그룹 정보 (경로 확인 성공 후) ── */}
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
              <Select placeholder="포맷을 선택하세요">
                {ANNOTATION_FORMAT_OPTIONS.map(opt => (
                  <Option key={opt.value} value={opt.value}>
                    <Space>
                      <Tag color={opt.value === 'NONE' ? 'default' : 'blue'} style={{ margin: 0 }}>
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
                <Input placeholder="예: coco2017_detection" />
              </Form.Item>
            )}

            <Form.Item label="설명 (선택)" name="description">
              <Input.TextArea rows={2} placeholder="데이터셋 설명을 입력하세요." />
            </Form.Item>

            {/* 선택 요약 */}
            <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="사용 목적">
                <Space wrap size={4}>
                  {(form.getFieldValue('task_types') ?? []).map((t: string) => (
                    <Tag key={t} color="purple">{t}</Tag>
                  ))}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="데이터 유형">
                <Tag color="blue">RAW</Tag>
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
  )
}
