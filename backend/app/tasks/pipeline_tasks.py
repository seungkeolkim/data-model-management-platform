"""
Pipeline Celery Tasks - Phase 2에서 구현
현재는 뼈대만 정의
"""
from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="app.tasks.pipeline_tasks.run_pipeline",
    queue="pipeline",
    max_retries=0,  # 파이프라인은 재시도 없음 (멱등성 보장 어려움)
)
def run_pipeline(self, execution_id: str, pipeline_config: dict) -> dict:
    """
    데이터셋 파이프라인 실행 (Phase 2에서 구현).

    Args:
        execution_id: PipelineExecution.id
        pipeline_config: PipelineConfig 스냅샷

    Returns:
        실행 결과 dict
    """
    # Phase 2에서 구현:
    # 1. execution_id로 DB에서 PipelineExecution 조회
    # 2. PipelineExecutor.run(config) 실행
    # 3. 진행률 업데이트 (pipeline_executions 테이블)
    # 4. 완료/실패 시 datasets.status 업데이트
    # 5. EDA task 체이닝 (Phase 2-a 구현 시)
    raise NotImplementedError("Phase 2에서 구현 예정")
