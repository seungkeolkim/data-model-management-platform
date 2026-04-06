import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Typography, Tag } from 'antd'
import {
  DatabaseOutlined,
  BranchesOutlined,
  RocketOutlined,
  SettingOutlined,
  ExperimentOutlined,
  DashboardOutlined,
} from '@ant-design/icons'

const { Header, Sider, Content } = Layout
const { Title } = Typography

const menuItems = [
  {
    key: 'datasets',
    icon: <DatabaseOutlined />,
    label: '데이터셋',
    path: '/datasets',
  },
  {
    key: 'pipelines',
    icon: <BranchesOutlined />,
    label: '데이터 변형',
    path: '/pipelines',
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

  // 현재 경로로 선택된 메뉴 키 결정
  const selectedKey = location.pathname.startsWith('/datasets')
    ? 'datasets'
    : location.pathname.startsWith('/pipelines')
    ? 'pipelines'
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
        style={{
          background: '#fff',
          borderRight: '1px solid #f0f0f0',
        }}
      >
        {/* 로고 — 클릭 시 메인 페이지로 이동 */}
        <div
          style={{ padding: '16px 20px', borderBottom: '1px solid #f0f0f0', cursor: 'pointer' }}
          onClick={() => navigate('/')}
        >
          <Title level={5} style={{ margin: 0, color: '#1677ff' }}>
            🤖 ML Platform
          </Title>
          <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
            v0.1.0 · 데이터 관리
          </div>
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
