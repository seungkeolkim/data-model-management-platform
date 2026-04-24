import { useLocation, useNavigate } from 'react-router-dom'
import { Segmented } from 'antd'

/**
 * Automation 섹션 내부 탭 (관리 ↔ 실행 이력).
 *
 * 023 §6-3 의 "실행 이력 페이지 개편" 은 /pipelines 이력과 동일한 UI 의도를 가지지만,
 * /pipelines 는 실 백엔드 API 를 호출하고 있어 목업 automation 필드와 섞이면 데이터 출처가
 * 혼재된다. 목업에서는 Automation 메뉴 하위에 별도 경로 (/automation/history) 를 두고,
 * 섹션 간 전환은 이 Segmented 로만 한다. 실 구현 진입 시 두 이력 뷰의 통합 여부는 그때 재결정.
 */
export default function AutomationSectionNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const current = location.pathname.startsWith('/automation/history') ? 'history' : 'dashboard'

  return (
    <Segmented
      value={current}
      onChange={(value) => {
        if (value === 'dashboard') navigate('/automation')
        else navigate('/automation/history')
      }}
      options={[
        { label: '관리', value: 'dashboard' },
        { label: '실행 이력', value: 'history' },
      ]}
      style={{ marginBottom: 16 }}
    />
  )
}
