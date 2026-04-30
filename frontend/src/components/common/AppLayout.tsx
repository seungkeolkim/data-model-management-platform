import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Button, Layout, Menu, Typography, Tag } from 'antd'
import {
  DatabaseOutlined,
  BranchesOutlined,
  ThunderboltOutlined,
  RocketOutlined,
  SettingOutlined,
  ExperimentOutlined,
  DashboardOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'

const { Sider, Content } = Layout
const { Title } = Typography

const menuItems = [
  {
    key: 'datasets',
    icon: <DatabaseOutlined />,
    label: '데이터셋',
    path: '/datasets',
  },
  // v7.10 §9-7 재배선: 데이터 변형 메뉴 = 파이프라인 목록 + 실행 이력 2 하위.
  {
    key: 'pipelines',
    icon: <BranchesOutlined />,
    label: '데이터 변형',
    children: [
      {
        key: 'pipelines-list',
        icon: <BranchesOutlined />,
        label: '파이프라인 목록',
        path: '/pipelines',
      },
      {
        key: 'pipelines-runs',
        icon: <BranchesOutlined />,
        label: '실행 이력',
        path: '/pipelines/runs',
      },
    ],
  },
  {
    key: 'automation',
    icon: <ThunderboltOutlined />,
    label: 'Automation',
    path: '/automation',
  },
  {
    key: 'training',
    icon: <RocketOutlined />,
    label: (
      <span>
        모델 학습 <Tag color="default" style={{ fontSize: 10, padding: '0 4px' }}>2차</Tag>
      </span>
    ),
    path: '/training',
  },
  {
    type: 'divider' as const,
  },
  {
    key: 'settings',
    icon: <SettingOutlined />,
    label: '설정',
    children: [
      {
        key: 'settings-manipulators',
        icon: <ExperimentOutlined />,
        label: 'Manipulator 관리',
        path: '/settings/manipulators',
      },
      {
        key: 'settings-system',
        icon: <DashboardOutlined />,
        label: '시스템 상태',
        path: '/settings/system',
      },
    ],
  },
]

export default function AppLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  // 사이드바 접힘 상태. 토글 버튼으로 전환한다.
  const [siderCollapsed, setSiderCollapsed] = useState(false)

  // 현재 경로로 선택된 메뉴 키 결정.
  // /pipelines 서브 경로는 /pipelines/runs 먼저 검사 (더 구체적인 매치를 우선).
  const selectedKey = location.pathname.startsWith('/datasets')
    ? 'datasets'
    : location.pathname.startsWith('/pipelines/runs')
    ? 'pipelines-runs'
    : location.pathname.startsWith('/pipelines')
    ? 'pipelines-list'
    : location.pathname.startsWith('/automation')
    ? 'automation'
    : location.pathname.startsWith('/training')
    ? 'training'
    : location.pathname.startsWith('/settings/manipulators')
    ? 'settings-manipulators'
    : location.pathname.startsWith('/settings/system')
    ? 'settings-system'
    : 'datasets'

  const handleMenuClick = ({ key }: { key: string }) => {
    const flat = menuItems.flatMap((item) =>
      'children' in item ? item.children ?? [] : [item]
    )
    const found = flat.find((item) => 'key' in item && item.key === key)
    if (found && 'path' in found) {
      navigate(found.path as string)
    }
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={220}
        collapsible
        collapsed={siderCollapsed}
        trigger={null}
        collapsedWidth={64}
        style={{
          background: '#fff',
          borderRight: '1px solid #f0f0f0',
        }}
      >
        {/* 로고 영역 — 접힘 상태에선 아이콘만, 펼침 상태에선 타이틀+서브텍스트.
            우측의 토글 버튼으로 사이드바 접힘/펼침 전환. */}
        <div
          style={{
            padding: siderCollapsed ? '16px 0' : '16px 20px',
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: siderCollapsed ? 'center' : 'space-between',
            gap: 8,
          }}
        >
          {!siderCollapsed && (
            <div style={{ cursor: 'pointer', flex: 1 }} onClick={() => navigate('/')}>
              <Title level={5} style={{ margin: 0, color: '#1677ff' }}>
                🤖 ML Platform
              </Title>
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                v0.1.0 · 데이터 관리
              </div>
            </div>
          )}
          <Button
            type="text"
            size="small"
            icon={siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setSiderCollapsed((prev) => !prev)}
          />
        </div>

        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          defaultOpenKeys={['settings']}
          style={{ borderRight: 0, marginTop: 8 }}
          onClick={handleMenuClick}
          items={menuItems.filter((item) => item.type !== 'divider').map((item) => {
            if ('children' in item) {
              return {
                key: item.key,
                icon: item.icon,
                label: item.label,
                children: item.children?.map((child) => ({
                  key: child.key,
                  icon: child.icon,
                  label: child.label,
                })),
              }
            }
            return {
              key: item.key,
              icon: item.icon,
              label: item.label,
            }
          })}
        />
      </Sider>

      <Layout>
        <Content style={{ margin: '24px', minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
