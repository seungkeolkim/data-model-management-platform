/**
 * NodeShell — 모든 커스텀 노드의 공통 UI 껍데기.
 *
 * 제공 내용:
 *   - 헤더(색상 배경 + 이모지 + 라벨)
 *   - 테두리 색상(검증 이슈에 따라 빨강/노랑/기본)
 *   - 입력/출력 Handle
 *   - 본문 슬롯 (children)
 *   - 검증 이슈 Tag 목록 (푸터)
 *
 * 노드 컴포넌트는 헤더/Handle/border/Tag를 다시 작성하지 않고 이 쉘을 감싼다.
 */
import type { ReactNode } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Tag } from 'antd'
import type { PipelineValidationIssue } from '@/types/pipeline'

interface NodeShellProps {
  color: string
  emoji: string
  headerLabel: string
  /** 입력 핸들 설정. 여러 개(min/max 형태)면 handles 직접 렌더 */
  inputs: { count: number } | { customRender: () => ReactNode } | 'none'
  outputs: 'single' | 'none'
  issues?: PipelineValidationIssue[]
  minWidth?: number
  children: ReactNode
}

export function NodeShell({
  color,
  emoji,
  headerLabel,
  inputs,
  outputs,
  issues = [],
  minWidth = 200,
  children,
}: NodeShellProps) {
  const hasErrors = issues.some((i) => i.severity === 'error')
  const hasWarnings = issues.some((i) => i.severity === 'warning')
  const borderColor = hasErrors ? '#ff4d4f' : hasWarnings ? '#faad14' : color

  return (
    <div
      style={{
        background: '#fff',
        border: `2px solid ${borderColor}`,
        borderRadius: 8,
        minWidth,
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
      }}
    >
      {/* 입력 핸들 */}
      {inputs === 'none' ? null : 'customRender' in inputs ? (
        inputs.customRender()
      ) : (
        Array.from({ length: inputs.count }).map((_, idx) => (
          <Handle
            key={`input-${idx}`}
            type="target"
            position={Position.Left}
            id={inputs.count === 1 ? undefined : `input-${idx}`}
            style={{
              width: 10,
              height: 10,
              background: color,
              border: '2px solid #fff',
              ...(inputs.count > 1
                ? { top: `${((idx + 1) / (inputs.count + 1)) * 100}%` }
                : {}),
            }}
          />
        ))
      )}

      {/* 헤더 */}
      <div
        style={{
          background: color,
          color: '#fff',
          padding: '6px 12px',
          borderRadius: '6px 6px 0 0',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        <span>{emoji}</span>
        {headerLabel}
      </div>

      {/* 본문 */}
      <div style={{ padding: '8px 12px' }}>{children}</div>

      {/* 검증 이슈 */}
      {issues.length > 0 && (
        <div style={{ padding: '0 12px 8px' }}>
          {issues.map((issue, idx) => (
            <Tag
              key={idx}
              color={issue.severity === 'error' ? 'error' : 'warning'}
              style={{ fontSize: 10, marginTop: 2 }}
            >
              {issue.message}
            </Tag>
          ))}
        </div>
      )}

      {/* 출력 핸들 */}
      {outputs === 'single' && (
        <Handle
          type="source"
          position={Position.Right}
          style={{
            width: 10,
            height: 10,
            background: color,
            border: '2px solid #fff',
          }}
        />
      )}
    </div>
  )
}
