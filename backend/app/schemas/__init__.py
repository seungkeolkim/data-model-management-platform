"""
schemas 패키지 - Pydantic 스키마 정의
"""
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupUpdate,
    DatasetGroupResponse,
    DatasetGroupListResponse,
    DatasetSummary,
    DatasetCreate,
    DatasetRegisterRequest,
    DatasetResponse,
    LineageCreate,
    LineageResponse,
    LineageGraphResponse,
    MessageResponse,
    ErrorResponse,
)
from app.schemas.pipeline import (
    ManipulatorResponse,
    ManipulatorListResponse,
    PipelineConfig,
    TaskConfig,
    OutputConfig,
    PipelineRunResponse,
    PipelineSubmitResponse,
    # Pipeline 엔티티 (v7.10 027 §2-1)
    PipelineResponse,
    PipelineListItemResponse,
    PipelineListPageResponse,
    PipelineUpdateRequest,
    PipelineRunSubmitRequest,
    # Automation (v7.10 027 §2-3)
    PipelineAutomationResponse,
    PipelineAutomationUpsertRequest,
    PipelineAutomationRerunRequest,
    EDAResult,
    HealthResponse,
)

__all__ = [
    # dataset
    "DatasetGroupCreate",
    "DatasetGroupUpdate",
    "DatasetGroupResponse",
    "DatasetGroupListResponse",
    "DatasetSummary",
    "DatasetCreate",
    "DatasetRegisterRequest",
    "DatasetResponse",
    "LineageCreate",
    "LineageResponse",
    "LineageGraphResponse",
    "MessageResponse",
    "ErrorResponse",
    # pipeline
    "ManipulatorResponse",
    "ManipulatorListResponse",
    "PipelineConfig",
    "TaskConfig",
    "OutputConfig",
    "PipelineRunResponse",
    "PipelineSubmitResponse",
    "PipelineResponse",
    "PipelineListItemResponse",
    "PipelineListPageResponse",
    "PipelineUpdateRequest",
    "PipelineRunSubmitRequest",
    "PipelineAutomationResponse",
    "PipelineAutomationUpsertRequest",
    "PipelineAutomationRerunRequest",
    "EDAResult",
    "HealthResponse",
]
