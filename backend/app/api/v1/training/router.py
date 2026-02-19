"""
Training API Router - 2차에서 구현
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/objectives")
async def list_objectives():
    """Objective 목록 조회 (2차)"""
    return {"message": "2차에서 구현 예정"}


@router.get("/recipes")
async def list_recipes():
    """Recipe 목록 조회 (2차)"""
    return {"message": "2차에서 구현 예정"}


@router.get("/solutions")
async def list_solutions():
    """Solution 목록 조회 (2차)"""
    return {"message": "2차에서 구현 예정"}


@router.post("/solution-versions/{version_id}/submit")
async def submit_training_job(version_id: str):
    """학습 job 제출 (2차)"""
    return {"message": "2차에서 구현 예정"}
