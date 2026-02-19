"""
Manipulators API Router - Phase 2 (현재는 DB 조회 가능)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.all_models import Manipulator
from app.schemas.pipeline import ManipulatorListResponse, ManipulatorResponse

router = APIRouter()


@router.get("", response_model=ManipulatorListResponse)
async def list_manipulators(
    category: str | None = Query(default=None, description="FILTER | AUGMENT | FORMAT_CONVERT | MERGE | SAMPLE | REMAP"),
    scope: str | None = Query(default=None, description="PER_SOURCE | POST_MERGE"),
    status: str = Query(default="ACTIVE"),
    db: AsyncSession = Depends(get_db),
):
    """등록된 Manipulator 목록 조회."""
    query = select(Manipulator).where(Manipulator.status == status)

    if category:
        query = query.where(Manipulator.category == category.upper())

    if scope:
        # JSONB 배열에서 특정 값 포함 여부 검사
        query = query.where(Manipulator.scope.contains([scope.upper()]))

    query = query.order_by(Manipulator.category, Manipulator.name)
    result = await db.execute(query)
    manipulators = list(result.scalars().all())

    return ManipulatorListResponse(items=manipulators, total=len(manipulators))


@router.get("/{manipulator_id}", response_model=ManipulatorResponse)
async def get_manipulator(
    manipulator_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Manipulator 상세 조회."""
    result = await db.execute(
        select(Manipulator).where(Manipulator.id == manipulator_id)
    )
    manipulator = result.scalar_one_or_none()
    if not manipulator:
        raise HTTPException(status_code=404, detail="Manipulator not found")
    return manipulator
