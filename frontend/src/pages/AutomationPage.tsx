import { useState } from 'react'
import { Row, Col, Typography, Alert } from 'antd'
import AutomationPipelineList from '@/components/automation/AutomationPipelineList'
import AutomationChainingDag from '@/components/automation/AutomationChainingDag'
import AutomationSectionNav from '@/components/automation/AutomationSectionNav'

const { Title, Text } = Typography

/**
 * Automation 관리 페이지 (목업, 023 §6-2).
 *
 * 레이아웃: 좌측 파이프라인 목록 + 우측 chaining DAG.
 * 데이터 출처는 `frontend/src/mocks/automation.ts` — 현 단계에서 백엔드 통신 없음 (§9-1 A 안).
 *
 * master-detail UX: 좌측 행 클릭 = **선택** (우측 DAG 에서 해당 노드 강조 + 이웃 외 흐리게).
 * 상세 페이지 이동은 목록 행 끝의 "상세 →" 버튼으로만 — 사용자가 여러 파이프라인을 돌려 보며
 * DAG 구성을 비교할 수 있게 한다.
 */
export default function AutomationPage() {
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null)

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>
          Automation
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          파이프라인 자동화 관리 (목업) — 데이터는 mock fixture
        </Text>
      </div>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="이 페이지는 목업입니다"
        description="자동화 로직 / 상태 변경은 프론트 세션 메모리에만 반영됩니다. 새로고침 시 초기화됩니다."
      />
      <AutomationSectionNav />
      <Row gutter={16}>
        <Col xs={24} xl={14}>
          <AutomationPipelineList
            selectedPipelineId={selectedPipelineId}
            onSelectPipeline={setSelectedPipelineId}
          />
        </Col>
        <Col xs={24} xl={10}>
          <AutomationChainingDag selectedPipelineId={selectedPipelineId} />
        </Col>
      </Row>
    </div>
  )
}
