"""
Pipelines API Router - Phase 2에서 구현
"""
from fastapi import APIRouter

router = APIRouter()


@router.post("/execute")
async def execute_pipeline():
    """파이프라인 실행 (Phase 2)"""
    return {"message": "Phase 2에서 구현 예정", "endpoint": "POST /pipelines/execute"}


@router.get("/{execution_id}/status")
async def get_pipeline_status(execution_id: str):
    """파이프라인 실행 상태 조회 (Phase 2)"""
    return {"message": "Phase 2에서 구현 예정", "endpoint": f"GET /pipelines/{execution_id}/status"}


@router.get("")
async def list_pipeline_executions():
    """파이프라인 실행 이력 목록 (Phase 2)"""
    return {"message": "Phase 2에서 구현 예정", "endpoint": "GET /pipelines"}
