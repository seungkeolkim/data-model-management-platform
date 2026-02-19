import { useState } from 'react'
import { Typography, Card, Tag, Button, Space, Descriptions, Alert } from 'antd'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

const { Title } = Typography

interface HealthResponse {
  status: string
  services: {
    database: { ok: boolean; error: string | null }
    storage: { ok: boolean; backend: string; base_path: string; error: string | null }
  }
  version: string
  env: string
}

async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await axios.get('/health')
  return data
}

/**
 * 시스템 상태 페이지 — /health 엔드포인트 연결
 */
export default function SystemStatusPage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>시스템 상태</Title>
        <Button onClick={() => refetch()} loading={isLoading}>새로고침</Button>
      </div>

      {error && (
        <Alert type="error" message="API 서버에 연결할 수 없습니다." style={{ marginBottom: 16 }} />
      )}

      {data && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Card title="전체 상태">
            <Tag color={data.status === 'healthy' ? 'green' : 'orange'} style={{ fontSize: 14 }}>
              {data.status === 'healthy' ? '✅ 정상' : '⚠️ 일부 문제'}
            </Tag>
            <span style={{ marginLeft: 12, color: '#999' }}>버전: {data.version} · 환경: {data.env}</span>
          </Card>

          <Card title="PostgreSQL">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="상태">
                <Tag color={data.services.database.ok ? 'green' : 'red'}>
                  {data.services.database.ok ? '연결됨' : '연결 실패'}
                </Tag>
              </Descriptions.Item>
              {data.services.database.error && (
                <Descriptions.Item label="오류">
                  <code>{data.services.database.error}</code>
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card title="스토리지">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="상태">
                <Tag color={data.services.storage.ok ? 'green' : 'orange'}>
                  {data.services.storage.ok ? '접근 가능' : '경로 없음'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="백엔드">{data.services.storage.backend}</Descriptions.Item>
              <Descriptions.Item label="기본 경로">{data.services.storage.base_path}</Descriptions.Item>
              {data.services.storage.error && (
                <Descriptions.Item label="오류">
                  <code style={{ color: '#faad14' }}>{data.services.storage.error}</code>
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>
        </Space>
      )}
    </div>
  )
}
