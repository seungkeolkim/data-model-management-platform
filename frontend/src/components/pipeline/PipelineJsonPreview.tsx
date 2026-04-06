/**
 * PipelineJsonPreview — JSON 프리뷰 디버그 패널
 *
 * 현재 그래프 상태를 PipelineConfig JSON으로 변환하여 표시한다.
 * 디버깅 및 사용자 확인용.
 */

import { Typography } from 'antd'

const { Text } = Typography

interface PipelineJsonPreviewProps {
  jsonString: string
  error?: string | null
}

export default function PipelineJsonPreview({ jsonString, error }: PipelineJsonPreviewProps) {
  return (
    <div
      style={{
        width: 360,
        background: '#1e1e1e',
        borderLeft: '1px solid #333',
        height: '100%',
        overflowY: 'auto',
        padding: '12px',
      }}
    >
      <Text style={{ color: '#ccc', fontSize: 13, fontWeight: 600 }}>
        PipelineConfig JSON
      </Text>

      {error && (
        <div style={{ marginTop: 8, padding: 8, background: '#3d1e1e', borderRadius: 4 }}>
          <Text style={{ color: '#ff6b6b', fontSize: 12 }}>{error}</Text>
        </div>
      )}

      <pre
        style={{
          marginTop: 8,
          color: '#d4d4d4',
          fontSize: 11,
          fontFamily: 'monospace',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.5,
        }}
      >
        {jsonString}
      </pre>
    </div>
  )
}
