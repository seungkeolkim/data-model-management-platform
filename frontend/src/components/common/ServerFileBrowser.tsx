import { useState, useEffect, useCallback } from 'react'
import {
  Modal,
  Table,
  Breadcrumb,
  Button,
  Input,
  Space,
  Typography,
  Alert,
  Spin,
} from 'antd'
import {
  FolderOutlined,
  FileOutlined,
  ArrowLeftOutlined,
  EnterOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { fileBrowserApi } from '@/api/dataset'
import type { FileBrowserEntry } from '@/types/dataset'

const { Text } = Typography

interface ServerFileBrowserProps {
  open: boolean
  onClose: () => void
  /** 선택 완료 시 호출. 절대경로 배열 반환 */
  onSelect: (paths: string[]) => void
  /** directory: 폴더 선택 모드 / file: 파일 선택 모드 */
  mode: 'directory' | 'file'
  /** file 모드에서 복수 선택 허용 여부 */
  multiple?: boolean
  title?: string
}

export default function ServerFileBrowser({
  open,
  onClose,
  onSelect,
  mode,
  multiple = false,
  title,
}: ServerFileBrowserProps) {
  const [currentPath, setCurrentPath] = useState<string>('')
  const [entries, setEntries] = useState<FileBrowserEntry[]>([])
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [isBrowseRoot, setIsBrowseRoot] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedPaths, setSelectedPaths] = useState<string[]>([])

  // 경로 직접 입력 관련 상태
  const [rootPath, setRootPath] = useState<string>('')
  const [pathInputValue, setPathInputValue] = useState<string>('')

  /** 현재 경로에서 루트를 제거한 상대 경로 반환 */
  const toRelativePath = useCallback((absolutePath: string, root: string): string => {
    if (!root || !absolutePath) return ''
    // 루트 경로 자체이면 빈 문자열
    if (absolutePath === root) return ''
    // 루트 접두사 제거 후 앞쪽 슬래시 제거
    const relative = absolutePath.startsWith(root)
      ? absolutePath.slice(root.length).replace(/^\//, '')
      : absolutePath
    return relative
  }, [])

  const loadDirectory = useCallback(async (path: string) => {
    setLoading(true)
    setError(null)
    setSelectedPaths([])
    try {
      const apiMode = mode === 'directory' ? 'directory' : 'all'
      const res = await fileBrowserApi.list({ path: path || undefined, mode: apiMode })
      const data = res.data
      setCurrentPath(data.current_path)
      setParentPath(data.parent_path)
      setIsBrowseRoot(data.is_browse_root)
      setEntries(data.entries)
      // 루트 경로 저장 (최초 로드 시 is_browse_root=true인 응답에서 취득)
      if (data.is_browse_root) {
        setRootPath(data.current_path)
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const msg = detail ?? (e instanceof Error ? e.message : '디렉토리를 불러올 수 없습니다.')
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [mode])

  // 경로 탐색 결과가 바뀔 때 입력 필드를 현재 상대 경로와 동기화
  useEffect(() => {
    if (rootPath && currentPath) {
      setPathInputValue(toRelativePath(currentPath, rootPath))
    }
  }, [currentPath, rootPath, toRelativePath])

  /** 경로 직접 입력 후 Enter 시 해당 경로로 이동 */
  const handlePathInputSubmit = () => {
    const trimmed = pathInputValue.trim().replace(/^\/+/, '')
    const absolutePath = trimmed ? `${rootPath}/${trimmed}` : rootPath
    loadDirectory(absolutePath)
  }

  useEffect(() => {
    if (open) {
      setCurrentPath('')
      setSelectedPaths([])
      setPathInputValue('')
      loadDirectory('')
    }
  }, [open, loadDirectory])

  const handleEntryClick = (entry: FileBrowserEntry) => {
    if (entry.is_dir) {
      loadDirectory(entry.path)
    }
  }

  const handleBack = () => {
    if (isBrowseRoot) return
    loadDirectory(parentPath ?? '')
  }

  const handleSelectCurrent = () => {
    // directory 모드: 현재 디렉토리를 선택
    onSelect([currentPath])
    onClose()
  }

  const handleSelectFiles = () => {
    // file 모드: 체크된 파일들 선택
    onSelect(selectedPaths)
    onClose()
  }

  // 브레드크럼 경로 파싱
  const breadcrumbItems = () => {
    if (isBrowseRoot || !currentPath) return [{ title: '루트 목록' }]
    const parts = currentPath.split('/').filter(Boolean)
    const items = [{ title: <a onClick={() => loadDirectory('')}>루트</a> }]
    parts.forEach((part, i) => {
      const path = '/' + parts.slice(0, i + 1).join('/')
      if (i === parts.length - 1) {
        items.push({ title: part })
      } else {
        items.push({ title: <a onClick={() => loadDirectory(path)}>{part}</a> })
      }
    })
    return items
  }

  const rowSelection = mode === 'file' ? {
    selectedRowKeys: selectedPaths,
    onChange: (keys: React.Key[]) => setSelectedPaths(keys as string[]),
    type: multiple ? 'checkbox' as const : 'radio' as const,
    getCheckboxProps: (record: FileBrowserEntry) => ({
      disabled: record.is_dir,
    }),
  } : undefined

  const columns: ColumnsType<FileBrowserEntry> = [
    {
      title: '이름',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: FileBrowserEntry) => (
        <Space>
          {record.is_dir
            ? <FolderOutlined style={{ color: '#faad14' }} />
            : <FileOutlined style={{ color: '#8c8c8c' }} />
          }
          {record.is_dir ? (
            <a onClick={() => handleEntryClick(record)}>{name}</a>
          ) : (
            <Text>{name}</Text>
          )}
        </Space>
      ),
    },
    {
      title: '크기',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (size: number | null) =>
        size == null ? '-' : size < 1024 ? `${size} B`
          : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB`
          : `${(size / 1024 / 1024).toFixed(1)} MB`,
    },
    {
      title: '수정일',
      dataIndex: 'modified_at',
      key: 'modified_at',
      width: 160,
      render: (v: string | null) => v ? new Date(v).toLocaleString('ko-KR') : '-',
    },
  ]

  const modalTitle = title ?? (mode === 'directory' ? '이미지 폴더 선택' : '어노테이션 파일 선택')

  const footer = (
    <Space>
      <Button onClick={onClose}>취소</Button>
      {mode === 'directory' && !isBrowseRoot && (
        <Button
          type="primary"
          onClick={handleSelectCurrent}
          disabled={!currentPath}
        >
          현재 폴더 선택: {currentPath.split('/').pop()}
        </Button>
      )}
      {mode === 'file' && (
        <Button
          type="primary"
          onClick={handleSelectFiles}
          disabled={selectedPaths.length === 0}
        >
          선택 ({selectedPaths.length}개)
        </Button>
      )}
    </Space>
  )

  return (
    <Modal
      title={modalTitle}
      open={open}
      onCancel={onClose}
      width={760}
      footer={footer}
      styles={{ body: { padding: '12px 0' } }}
      zIndex={1010}
    >
      <Space direction="vertical" style={{ width: '100%', padding: '0 24px' }}>
        {/* 경로 직접 입력 */}
        <Input
          addonBefore={rootPath ? `${rootPath}/` : '/'}
          placeholder="하위 경로 입력 후 Enter (예: coco2017/images)"
          value={pathInputValue}
          onChange={(e) => setPathInputValue(e.target.value)}
          onPressEnter={handlePathInputSubmit}
          suffix={
            <EnterOutlined
              style={{ color: '#999', cursor: 'pointer' }}
              onClick={handlePathInputSubmit}
              title="이동"
            />
          }
          allowClear
          size="small"
        />

        {/* 네비게이션 */}
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            size="small"
            disabled={isBrowseRoot}
            onClick={handleBack}
          >
            상위로
          </Button>
          <Breadcrumb items={breadcrumbItems()} />
        </Space>

        {error && <Alert type="error" message={error} showIcon closable />}

        <Spin spinning={loading}>
          <Table<FileBrowserEntry>
            dataSource={entries}
            columns={columns}
            rowKey="path"
            rowSelection={rowSelection}
            size="small"
            pagination={{ pageSize: 50, showTotal: (total) => `총 ${total}개`, size: 'small', showSizeChanger: false }}
            scroll={{ y: 400 }}
            locale={{ emptyText: '비어있는 디렉토리입니다.' }}
            onRow={(record) => ({
              onDoubleClick: () => handleEntryClick(record),
              style: { cursor: record.is_dir ? 'pointer' : 'default' },
            })}
          />
        </Spin>
      </Space>
    </Modal>
  )
}
