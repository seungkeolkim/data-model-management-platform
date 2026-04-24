import { useState } from 'react'
import { Typography, Alert, Button, Drawer } from 'antd'
import { ApartmentOutlined } from '@ant-design/icons'
import AutomationPipelineList from '@/components/automation/AutomationPipelineList'
import AutomationChainingDag from '@/components/automation/AutomationChainingDag'
import AutomationSectionNav from '@/components/automation/AutomationSectionNav'

const { Title, Text } = Typography

/**
 * Automation 관리 페이지 (목업, 023 §6-2).
 *
 * 레이아웃 (2026-04-23 변경): 전폭 Automation 목록. "의존 그래프" 는 상단 버튼으로 우측 Drawer 슬라이드.
 * 이전 (2-column 좌우 분할) 에서는 목록 컬럼이 많아질 때 공간이 빠듯해져 사용자 요청으로 전환.
 *
 * master-detail UX: 목록 행 클릭 = **선택** (Drawer 내부 DAG 에서 해당 노드 강조, 이웃 외 흐리게).
 * 상세 페이지 이동은 목록 행 끝의 "상세 →" 버튼으로만.
 */
export default function AutomationPage() {
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null)
  const [isDagOpen, setIsDagOpen] = useState(false)

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 16,
          gap: 16,
        }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            Automation
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            파이프라인 자동화 관리 (목업) — 데이터는 mock fixture
          </Text>
        </div>
        <Button
          type={isDagOpen ? 'primary' : 'default'}
          icon={<ApartmentOutlined />}
          onClick={() => setIsDagOpen((prev) => !prev)}
        >
          의존 그래프 {isDagOpen ? '닫기' : '보기'}
        </Button>
      </div>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="이 페이지는 목업입니다"
        description="자동화 로직 / 상태 변경은 프론트 세션 메모리에만 반영됩니다. 새로고침 시 초기화됩니다."
      />
      <AutomationSectionNav />
      <AutomationPipelineList
        selectedPipelineId={selectedPipelineId}
        onSelectPipeline={setSelectedPipelineId}
      />
      {/*
        mask={false} 로 배경 overlay 제거 — 메인 목록이 disable 되지 않고 계속 조작 가능.
        열림/닫힘은 상단 "의존 그래프 보기/닫기" 토글 버튼 또는 Drawer 내부 X 로 제어.
      */}
      <Drawer
        title="파이프라인 의존 그래프"
        placement="right"
        width={720}
        open={isDagOpen}
        onClose={() => setIsDagOpen(false)}
        mask={false}
        destroyOnClose={false}
      >
        <AutomationChainingDag selectedPipelineId={selectedPipelineId} />
      </Drawer>
    </div>
  )
}
