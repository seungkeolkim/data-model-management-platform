"""
EDA Celery Tasks - Phase 2-a에서 구현
현재는 뼈대만 정의
"""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="app.tasks.eda_tasks.run_eda",
    queue="eda",
)
def run_eda(self, dataset_id: str) -> dict:
    """
    데이터셋 EDA 자동 실행 (Phase 2-a에서 구현).

    Args:
        dataset_id: Dataset.id

    Returns:
        EDA 결과 summary dict
    """
    # Phase 2-a에서 구현:
    # 1. dataset_id로 annotation.json 로드
    # 2. 클래스 분포, BBox 통계, 해상도 분포 등 계산
    # 3. 샘플 이미지 생성 (BBox 오버레이)
    # 4. 결과를 NAS eda/{dataset_id}/ 에 저장
    # 5. datasets.metadata JSONB 업데이트
    raise NotImplementedError("Phase 2-a에서 구현 예정")
