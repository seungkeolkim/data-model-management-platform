import { useState } from 'react'
import { Typography, Alert, Button, Drawer } from 'antd'
import { ApartmentOutlined } from '@ant-design/icons'
import AutomationPipelineList from '@/components/automation/AutomationPipelineList'
import AutomationChainingDag from '@/components/automation/AutomationChainingDag'
import AutomationSectionNav from '@/components/automation/AutomationSectionNav'

const { Title, Text } = Typography

/**
 * Automation 관리 페이지 (목업, v7.13 baseline).
 *
 * 레이아웃: 전폭 Automation 목록. "의존 그래프" 는 상단 버튼으로 우측 Drawer 슬라이드.
 *
 * master-detail UX: 목록 의 expand 안 version 행 클릭 = **선택** (Drawer 내부 DAG 에서 해당 version
 * 노드 강조, 이웃 외 흐리게). concept 행 클릭은 expand 토글만 — DAG 가 version 단위라 concept 단위
 * 선택은 의미가 모호하다. 상세 페이지 이동은 version 행 끝의 "상세 →" 버튼으로만.
 */
export default function AutomationPage() {
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)
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
        selectedVersionId={selectedVersionId}
        onSelectVersion={setSelectedVersionId}
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
        <AutomationChainingDag selectedVersionId={selectedVersionId} />
      </Drawer>
    </div>
  )
}
