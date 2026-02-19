"""
EDA API Router - Phase 2-a에서 구현
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/{dataset_id}")
async def get_eda_result(dataset_id: str):
    """EDA 결과 조회 (Phase 2-a)"""
    return {"message": "Phase 2-a에서 구현 예정"}


@router.post("/{dataset_id}/run")
async def run_eda(dataset_id: str):
    """EDA 수동 재실행 (Phase 2-a)"""
    return {"message": "Phase 2-a에서 구현 예정"}
