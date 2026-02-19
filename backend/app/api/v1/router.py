"""
API v1 메인 라우터 - 모든 도메인 라우터 통합
"""
from fastapi import APIRouter

from app.api.v1.dataset_groups.router import router as dataset_groups_router
from app.api.v1.datasets.router import router as datasets_router
from app.api.v1.lineage.router import router as lineage_router
from app.api.v1.manipulators.router import router as manipulators_router
from app.api.v1.pipelines.router import router as pipelines_router
from app.api.v1.eda.router import router as eda_router
from app.api.v1.training.router import router as training_router

api_router = APIRouter()

# Phase 1 - 데이터셋 관리
api_router.include_router(dataset_groups_router, prefix="/dataset-groups", tags=["dataset-groups"])
api_router.include_router(datasets_router, prefix="/datasets", tags=["datasets"])

# Phase 2 - 파이프라인 & Manipulator
api_router.include_router(pipelines_router, prefix="/pipelines", tags=["pipelines"])
api_router.include_router(manipulators_router, prefix="/manipulators", tags=["manipulators"])

# Phase 2-a - EDA (라우터 등록만, 구현은 Phase 2-a에서)
api_router.include_router(eda_router, prefix="/eda", tags=["eda"])

# Phase 2-b - Lineage (라우터 등록만, 구현은 Phase 2-b에서)
api_router.include_router(lineage_router, prefix="/lineage", tags=["lineage"])

# 2차 - 학습 관리 (라우터 등록만, 구현은 2차에서)
api_router.include_router(training_router, prefix="/training", tags=["training"])
