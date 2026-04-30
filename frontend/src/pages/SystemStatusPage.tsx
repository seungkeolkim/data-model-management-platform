/**
 * SystemStatusPage — 매우 단순한 placeholder.
 *
 * 호스트에 마운트된 디렉토리 (LOCAL_STORAGE_BASE / LOCAL_UPLOAD_BASE) 의 디스크
 * 사용량을 한두 줄로 표시. 나중에 갈아엎을 예정이라 의도적으로 minimal.
 */
import { Typography, Card, Button, Space, Alert, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import api from '@/api'

const { Title, Text } = Typography

interface StorageUsageItem {
  label: string
  path: string
  exists: boolean
  total_bytes: number | null
  used_bytes: number | null
  free_bytes: number | null
  error: string | null
}

interface StorageUsageResponse {
  items: StorageUsageItem[]
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(value < 10 ? 2 : 1)} ${units[unitIndex]}`
}

export default function SystemStatusPage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['system-storage-usage'],
    queryFn: () =>
      api.get<StorageUsageResponse>('/system/storage-usage').then((r) => r.data),
    refetchInterval: 30_000,
  })

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
        }}
      >
        <Title level={3} style={{ margin: 0 }}>
          시스템 상태
        </Title>
        <Button onClick={() => refetch()} loading={isLoading}>
          새로고침
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          message="API 호출 실패"
          description={(error as Error).message}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card title="마운트 디스크 사용량">
        {isLoading && <Spin />}
        {data && (
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            {data.items.map((item) => (
              <div key={item.label}>
                <Text strong style={{ marginRight: 8 }}>
                  {item.label}
                </Text>
                <Text code style={{ marginRight: 12 }}>
                  {item.path}
                </Text>
                {!item.exists ? (
                  <Text type="warning">경로 없음</Text>
                ) : item.error ? (
                  <Text type="danger">오류: {item.error}</Text>
                ) : (
                  <Text type="secondary">
                    used {formatBytes(item.used_bytes)} / total{' '}
                    {formatBytes(item.total_bytes)} (free{' '}
                    {formatBytes(item.free_bytes)})
                  </Text>
                )}
              </div>
            ))}
          </Space>
        )}
      </Card>
    </div>
  )
}
