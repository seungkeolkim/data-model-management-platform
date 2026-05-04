import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import koKR from 'antd/locale/ko_KR'
import AppLayout from './components/common/AppLayout'
import DatasetListPage from './pages/DatasetListPage'
import DatasetDetailPage from './pages/DatasetDetailPage'
import DatasetViewerPage from './pages/DatasetViewerPage'
import PipelineEditorPage from './pages/PipelineEditorPage'
import PipelineHistoryPage from './pages/PipelineHistoryPage'
import { PipelineListPage } from './pages/PipelineListPage'
import PipelineVersionDetailPage from './pages/PipelineVersionDetailPage'
import AutomationPage from './pages/AutomationPage'
import AutomationHistoryPage from './pages/AutomationHistoryPage'
import AutomationPipelineDetailPage from './pages/AutomationPipelineDetailPage'
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
          {/* 전체화면 에디터 — AppLayout 밖 (사이드바 없음) */}
          <Route path="/pipelines/editor" element={<PipelineEditorPage />} />

          <Route path="/" element={<AppLayout />}>
            {/* Phase 1 — 데이터셋 관리 */}
            <Route index element={<Navigate to="/datasets" replace />} />
            <Route path="datasets" element={<DatasetListPage />} />
            <Route path="datasets/:groupId" element={<DatasetDetailPage />} />
            <Route path="datasets/:groupId/:datasetId" element={<DatasetViewerPage />} />

            {/* Phase 2 — 파이프라인 (데이터 변형) */}
            {/* v7.10 §9-7 재배선:
                - /pipelines          → PipelineListPage (Pipeline 정적 템플릿 목록 + 실행 버튼)
                - /pipelines/runs     → PipelineHistoryPage (실행 이력)
                (기존 경로 /pipelines 를 쓰던 곳은 /pipelines/runs 로 자동 이동 Alert 필요 — TODO §9-9) */}
            <Route path="pipelines" element={<PipelineListPage />} />
            <Route path="pipelines/runs" element={<PipelineHistoryPage />} />
            <Route
              path="pipeline-versions/:versionId"
              element={<PipelineVersionDetailPage />}
            />

            {/* Automation (목업) — v7.13 baseline 자료구조 (PipelineVersion 단위) */}
            <Route path="automation" element={<AutomationPage />} />
            <Route path="automation/history" element={<AutomationHistoryPage />} />
            <Route
              path="automation/versions/:versionId"
              element={<AutomationPipelineDetailPage />}
            />

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
