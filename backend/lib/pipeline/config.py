"""
파이프라인 실행 설정 스키마.

Pydantic BaseModel로 정의하되, DB/FastAPI에 의존하지 않는 순수 설정.
app/schemas/pipeline.py에서 re-export하여 API 레이어에서도 사용한다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ManipulatorConfig(BaseModel):
    """파이프라인 내 하나의 Manipulator 설정."""
    manipulator_name: str = Field(..., description="Manipulator.name")
    params: dict[str, Any] = Field(default_factory=dict)


class SourceConfig(BaseModel):
    """파이프라인 소스 데이터셋 설정."""
    dataset_id: str
    manipulators: list[ManipulatorConfig] = Field(default_factory=list)


class PipelineConfig(BaseModel):
    """파이프라인 실행 전체 설정."""
    sources: list[SourceConfig] = Field(..., min_length=1)
    post_merge_manipulators: list[ManipulatorConfig] = Field(default_factory=list)
    output_group_name: str
    output_dataset_type: str = Field(default="PROCESSED")
    output_annotation_format: str | None = None
    output_splits: list[str] = Field(default=["NONE"])
    description: str | None = None
