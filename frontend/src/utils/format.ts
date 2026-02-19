/**
 * 유틸리티 함수들
 */
import dayjs from 'dayjs'

/**
 * 날짜 포맷팅
 */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-'
  return dayjs(dateStr).format('YYYY-MM-DD HH:mm')
}

/**
 * Dataset type 라벨
 */
export function getDatasetTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    RAW: '원본',
    SOURCE: '소스',
    PROCESSED: '가공',
    FUSION: '퓨전',
  }
  return labels[type] ?? type
}

/**
 * Dataset type 색상 (Ant Design tag color)
 */
export function getDatasetTypeColor(type: string): string {
  const colors: Record<string, string> = {
    RAW: 'blue',
    SOURCE: 'green',
    PROCESSED: 'orange',
    FUSION: 'purple',
  }
  return colors[type] ?? 'default'
}

/**
 * Dataset status 색상
 */
export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    PENDING: 'default',
    PROCESSING: 'processing',
    READY: 'success',
    ERROR: 'error',
  }
  return colors[status] ?? 'default'
}

/**
 * Split 라벨
 */
export function getSplitLabel(split: string): string {
  const labels: Record<string, string> = {
    TRAIN: '학습',
    VAL: '검증',
    TEST: '테스트',
    NONE: '미분류',
  }
  return labels[split] ?? split
}

/**
 * 숫자 포맷팅 (천 단위 콤마)
 */
export function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-'
  return n.toLocaleString('ko-KR')
}
