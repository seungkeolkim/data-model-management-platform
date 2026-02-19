import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import koKR from 'antd/locale/ko_KR'
import AppLayout from './components/common/AppLayout'
import DatasetListPage from './pages/DatasetListPage'
import DatasetDetailPage from './pages/DatasetDetailPage'
import ManipulatorListPage from './pages/ManipulatorListPage'
import SystemStatusPage from './pages/SystemStatusPage'
import ComingSoonPage from './pages/ComingSoonPage'

export default function App() {
  return (
    <ConfigProvider
      locale={koKR}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            {/* Phase 1 — 데이터셋 관리 */}
            <Route index element={<Navigate to="/datasets" replace />} />
            <Route path="datasets" element={<DatasetListPage />} />
            <Route path="datasets/:groupId" element={<DatasetDetailPage />} />

            {/* Phase 2 이후 — 비활성 슬롯 */}
            <Route path="training/*" element={<ComingSoonPage title="모델 학습" phase="2차" />} />

            {/* 설정 */}
            <Route path="settings/manipulators" element={<ManipulatorListPage />} />
            <Route path="settings/system" element={<SystemStatusPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}
