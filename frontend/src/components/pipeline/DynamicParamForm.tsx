/**
 * DynamicParamForm — params_schema 기반 동적 폼 렌더러
 *
 * Manipulator의 params_schema (JSONB)를 읽어 Ant Design 폼 필드를 자동 생성한다.
 * 지원 타입: multiselect, select, textarea, slider, color, number, key_value
 */

import { Form, Select, Input, InputNumber, Slider, ColorPicker, Button, Space } from 'antd'
import { PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'

interface ParamFieldSchema {
  type: 'multiselect' | 'select' | 'textarea' | 'slider' | 'color' | 'number' | 'key_value'
  label: string
  required?: boolean
  default?: unknown
  options?: string[]
  min?: number
  max?: number
  key_label?: string
  value_label?: string
}

interface DynamicParamFormProps {
  paramsSchema: Record<string, ParamFieldSchema> | null
  params: Record<string, unknown>
  onChange: (params: Record<string, unknown>) => void
}

export default function DynamicParamForm({
  paramsSchema,
  params,
  onChange,
}: DynamicParamFormProps) {
  if (!paramsSchema || Object.keys(paramsSchema).length === 0) {
    return (
      <div style={{ color: '#8c8c8c', fontSize: 12, padding: '8px 0' }}>
        이 operator는 추가 설정이 필요하지 않습니다.
      </div>
    )
  }

  const updateParam = (key: string, value: unknown) => {
    onChange({ ...params, [key]: value })
  }

  return (
    <Form layout="vertical" size="small" style={{ marginTop: 8 }}>
      {Object.entries(paramsSchema).map(([paramKey, schema]) => {
        const currentValue = params[paramKey] ?? schema.default

        switch (schema.type) {
          case 'select':
            return (
              <Form.Item
                key={paramKey}
                label={schema.label}
                required={schema.required}
              >
                <Select
                  value={currentValue as string}
                  options={(schema.options ?? []).map((opt) => ({
                    value: opt,
                    label: opt,
                  }))}
                  onChange={(val) => updateParam(paramKey, val)}
                  allowClear={!schema.required}
                />
              </Form.Item>
            )

          case 'multiselect':
            return (
              <Form.Item
                key={paramKey}
                label={schema.label}
                required={schema.required}
              >
                <Select
                  mode="multiple"
                  value={(currentValue as string[]) ?? []}
                  options={(schema.options ?? []).map((opt) => ({
                    value: opt,
                    label: opt,
                  }))}
                  onChange={(val) => updateParam(paramKey, val)}
                  allowClear
                />
              </Form.Item>
            )

          case 'textarea':
            return (
              <Form.Item
                key={paramKey}
                label={schema.label}
                required={schema.required}
              >
                <Input.TextArea
                  rows={3}
                  value={(currentValue as string) ?? ''}
                  onChange={(e) => updateParam(paramKey, e.target.value)}
                />
              </Form.Item>
            )

          case 'number':
            return (
              <Form.Item
                key={paramKey}
                label={schema.label}
                required={schema.required}
              >
                <InputNumber
                  value={currentValue as number}
                  min={schema.min}
                  max={schema.max}
                  style={{ width: '100%' }}
                  onChange={(val) => updateParam(paramKey, val)}
                />
              </Form.Item>
            )

          case 'slider':
            return (
              <Form.Item
                key={paramKey}
                label={`${schema.label}: ${currentValue ?? schema.default ?? schema.min ?? 0}`}
                required={schema.required}
              >
                <Slider
                  value={(currentValue as number) ?? schema.default ?? schema.min ?? 0}
                  min={schema.min ?? 0}
                  max={schema.max ?? 100}
                  onChange={(val) => updateParam(paramKey, val)}
                />
              </Form.Item>
            )

          case 'color':
            return (
              <Form.Item
                key={paramKey}
                label={schema.label}
                required={schema.required}
              >
                <ColorPicker
                  value={(currentValue as string) ?? schema.default ?? '#000000'}
                  onChange={(_, hex) => updateParam(paramKey, hex)}
                />
              </Form.Item>
            )

          case 'key_value':
            return (
              <Form.Item
                key={paramKey}
                label={schema.label}
                required={schema.required}
              >
                <KeyValueEditor
                  value={(currentValue as Record<string, string>) ?? {}}
                  keyLabel={schema.key_label ?? '키'}
                  valueLabel={schema.value_label ?? '값'}
                  onChange={(val) => updateParam(paramKey, val)}
                />
              </Form.Item>
            )

          default:
            return (
              <Form.Item key={paramKey} label={schema.label}>
                <Input
                  value={String(currentValue ?? '')}
                  onChange={(e) => updateParam(paramKey, e.target.value)}
                />
              </Form.Item>
            )
        }
      })}
    </Form>
  )
}

// =============================================================================
// KeyValueEditor — key_value 타입 전용 서브 컴포넌트
// =============================================================================

function KeyValueEditor({
  value,
  keyLabel,
  valueLabel,
  onChange,
}: {
  value: Record<string, string>
  keyLabel: string
  valueLabel: string
  onChange: (val: Record<string, string>) => void
}) {
  const entries = Object.entries(value)

  const addEntry = () => {
    onChange({ ...value, '': '' })
  }

  const removeEntry = (oldKey: string) => {
    const updated = { ...value }
    delete updated[oldKey]
    onChange(updated)
  }

  const updateEntry = (oldKey: string, newKey: string, newVal: string) => {
    const updated: Record<string, string> = {}
    for (const [k, v] of Object.entries(value)) {
      if (k === oldKey) {
        updated[newKey] = newVal
      } else {
        updated[k] = v
      }
    }
    onChange(updated)
  }

  return (
    <div>
      {entries.map(([entryKey, entryVal], idx) => (
        <Space key={idx} style={{ display: 'flex', marginBottom: 4 }} align="center">
          <Input
            size="small"
            placeholder={keyLabel}
            value={entryKey}
            style={{ width: 120 }}
            onChange={(e) => updateEntry(entryKey, e.target.value, entryVal)}
          />
          <span style={{ color: '#8c8c8c' }}>&rarr;</span>
          <Input
            size="small"
            placeholder={valueLabel}
            value={entryVal}
            style={{ width: 120 }}
            onChange={(e) => updateEntry(entryKey, entryKey, e.target.value)}
          />
          <MinusCircleOutlined
            style={{ color: '#ff4d4f', cursor: 'pointer' }}
            onClick={() => removeEntry(entryKey)}
          />
        </Space>
      ))}
      <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={addEntry}>
        추가
      </Button>
    </div>
  )
}
