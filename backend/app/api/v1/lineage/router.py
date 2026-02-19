"""
Lineage API Router - Phase 2-b에서 구현
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/{dataset_id}/upstream")
async def get_upstream_lineage(dataset_id: str):
    """upstream lineage 전체 조회 (Phase 2-b)"""
    return {"message": "Phase 2-b에서 구현 예정"}


@router.get("/{dataset_id}/downstream")
async def get_downstream_lineage(dataset_id: str):
    """downstream lineage 전체 조회 (Phase 2-b)"""
    return {"message": "Phase 2-b에서 구현 예정"}
