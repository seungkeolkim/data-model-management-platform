/**
 * 데이터셋 등록 모달
 *
 * 등록 과정:
 * 1. 사용자가 NAS에 미리 이미지/annotation.json 업로드
 * 2. 이 폼에서 경로, split, 그룹명 입력
 * 3. "경로 검증" 버튼 → COCO annotation 유효성 확인
 * 4. "등록" 버튼 → DB 저장
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
} from '@ant-design/icons'
import { datasetGroupsApi } from '../../api/dataset'
import type { DatasetGroup, DatasetValidateResponse } from '../../types/dataset'

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

const SPLIT_OPTIONS = ['TRAIN', 'VAL', 'TEST', 'NONE'] as const

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

  // 경로 검증
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
      setValidateStatus(res.data.coco_valid ? 'success' : 'error')
      if (res.data.coco_valid) setCurrentStep(1)
    } catch (err: any) {
      setValidateStatus('error')
      setValidateResult(null)
    }
  }

  // 데이터셋 등록
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
        group_id: existingGroup?.id,
        group_name: existingGroup ? undefined : values.group_name,
        dataset_type: 'object_detection' as const,
        annotation_format: 'COCO' as const,
        task_types: ['DETECTION'] as ['DETECTION'],
        modality: 'RGB',
        description: values.description,
        split: values.split,
        storage_uri: values.storage_uri.trim(),
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
                .env의 LOCAL_STORAGE_BASE 기준 상대경로인지 확인하세요.<br />
                예) LOCAL_STORAGE_BASE=./data/my_nas 이면 → <Text code>raw/dataset_name/train/v1.0.0</Text> 형식
              </Text>
            </span>
          }
        />
      )

    if (!validateResult.images_dir_exists)
      return <Alert type="error" message="images/ 디렉토리가 없습니다. 이미지를 images/ 폴더에 넣어주세요." showIcon />

    if (!validateResult.annotation_exists)
      return <Alert type="error" message="annotation.json 파일이 없습니다. COCO 형식 annotation.json을 배치해주세요." showIcon />

    if (!validateResult.coco_valid)
      return (
        <Alert
          type="error"
          showIcon
          message="COCO annotation 검증 실패"
          description={
            validateResult.error
              ? validateResult.error
              : 'annotation.json이 COCO 형식이 아닙니다. (images, annotations, categories 키 필수)'
          }
        />
      )

    return (
      <Alert
        type="success"
        showIcon
        message="경로 검증 완료"
        description={
          <Descriptions size="small" column={2} style={{ marginTop: 8 }}>
            <Descriptions.Item label="이미지 수">{validateResult.image_count.toLocaleString()}장</Descriptions.Item>
            <Descriptions.Item label="Annotation 수">{validateResult.coco_annotation_count.toLocaleString()}개</Descriptions.Item>
            <Descriptions.Item label="클래스 수" span={2}>
              {validateResult.coco_categories.length}개{' '}
              {validateResult.coco_categories.slice(0, 8).map(c => (
                <Tag key={c} color="blue" style={{ marginLeft: 4 }}>{c}</Tag>
              ))}
              {validateResult.coco_categories.length > 8 && (
                <Text type="secondary"> 외 {validateResult.coco_categories.length - 8}개</Text>
              )}
            </Descriptions.Item>
          </Descriptions>
        }
      />
    )
  }

  return (
    <Modal
      title="데이터셋 등록"
      open={open}
      onCancel={handleClose}
      width={640}
      footer={null}
      destroyOnClose
    >
      {/* 안내 메시지 */}
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        message="사전 준비 사항"
        description={
          <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
            <li>
              <Text strong>.env</Text>의 <Text code>LOCAL_STORAGE_BASE</Text> 경로 아래에 데이터 폴더를 배치하세요.
            </li>
            <li>
              폴더 구조:{' '}
              <Text code>{'<storage_uri>/images/'}</Text> 와{' '}
              <Text code>{'<storage_uri>/annotation.json'}</Text>
            </li>
            <li>
              경로 입력 예시: <Text code>LOCAL_STORAGE_BASE</Text>가{' '}
              <Text code>./data/my_nas</Text>이고 실제 경로가{' '}
              <Text code>./data/my_nas/raw/coco/train/v1.0.0</Text>이면{' '}
              <Text code>raw/coco/train/v1.0.0</Text>을 입력
            </li>
            <li>annotation.json은 COCO 형식 (images, annotations, categories 키 필수)</li>
          </ul>
        }
        style={{ marginBottom: 20 }}
      />

      <Steps
        current={currentStep}
        size="small"
        style={{ marginBottom: 24 }}
        items={[
          { title: '경로 입력 & 검증', icon: validateStatus === 'loading' ? <LoadingOutlined /> : undefined },
          { title: '그룹 정보 입력' },
          { title: '등록 완료' },
        ]}
      />

      <Form form={form} layout="vertical">
        {/* Step 0: 경로 입력 */}
        <Form.Item
          label="NAS 경로 (storage_uri)"
          name="storage_uri"
          rules={[{ required: true, message: 'NAS 경로를 입력하세요.' }]}
          extra={
            <Text type="secondary" style={{ fontSize: 12 }}>
              LOCAL_STORAGE_BASE 기준 상대경로 (예: raw/my_dataset/train/v1.0.0)
            </Text>
          }
        >
          <Input
            prefix={<FolderOpenOutlined />}
            placeholder="raw/my_dataset/train/v1.0.0"
            onChange={() => {
              setValidateStatus('idle')
              setValidateResult(null)
              setCurrentStep(0)
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
          경로 검증 (COCO annotation 확인)
        </Button>

        {/* 검증 결과 */}
        <div style={{ marginTop: 12, marginBottom: 4 }}>
          {renderValidateResult()}
        </div>

        {/* Step 1: 그룹 정보 (검증 성공 후) */}
        {validateStatus === 'success' && (
          <>
            <Divider />

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
                extra={<Text type="secondary" style={{ fontSize: 12 }}>같은 데이터셋의 TRAIN/VAL/TEST를 묶는 단위입니다.</Text>}
              >
                <Input placeholder="예: coco2017_detection" />
              </Form.Item>
            )}

            <Form.Item label="설명 (선택)" name="description">
              <Input.TextArea rows={2} placeholder="데이터셋 설명을 입력하세요." />
            </Form.Item>

            {/* 고정값 안내 */}
            <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="데이터셋 유형">
                <Tag color="blue">object_detection</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Annotation 포맷">
                <Tag color="green">COCO</Tag>
              </Descriptions.Item>
            </Descriptions>

            {/* 오류 메시지 */}
            {submitError && (
              <Alert type="error" message={submitError} showIcon style={{ marginBottom: 16 }} />
            )}

            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={handleClose}>취소</Button>
              <Button
                type="primary"
                loading={submitting}
                onClick={handleSubmit}
              >
                데이터셋 등록
              </Button>
            </Space>
          </>
        )}
      </Form>
    </Modal>
  )
}
