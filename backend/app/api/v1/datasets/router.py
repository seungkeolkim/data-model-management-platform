"""
Datasets API Router (individual dataset operations)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.all_models import Dataset, DatasetGroup, DatasetLineage
from app.schemas.dataset import (
    DatasetMetaFileReplaceRequest,
    DatasetResponse,
    DatasetUpdate,
    DatasetValidateRequest,
    EdaStatsResponse,
    FormatValidateResponse,
    LineageGraphResponse,
    LineageNodeResponse,
    LineageEdgeResponse,
    MessageResponse,
    SampleListResponse,
)
from app.services.dataset_service import DatasetGroupService

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("", response_model=list[DatasetResponse])
async def list_datasets(
    group_id: str | None = Query(default=None),
    split: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Dataset 목록 조회. 소프트 삭제된 데이터셋은 제외."""
    logger.info("데이터셋 목록 조회", group_id=group_id, split=split, status=status)
    query = select(Dataset).where(Dataset.deleted_at.is_(None))
    if group_id:
        query = query.where(Dataset.group_id == group_id)
    if split:
        query = query.where(Dataset.split == split.upper())
    if status:
        query = query.where(Dataset.status == status.upper())
    query = query.order_by(Dataset.created_at.desc())
    result = await db.execute(query)
    datasets = list(result.scalars().all())
    logger.info("데이터셋 목록 조회 완료", count=len(datasets))
    return datasets


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dataset 단건 조회."""
    logger.info("데이터셋 상세 조회", dataset_id=dataset_id)
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        logger.warning("데이터셋 조회 실패", dataset_id=dataset_id)
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


@router.patch("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset(
    dataset_id: str,
    data: DatasetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Dataset 개별 수정 (annotation_format 등)."""
    logger.info("데이터셋 수정 요청", dataset_id=dataset_id, data=data.model_dump(exclude_unset=True))
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    updated = await svc.update_dataset(dataset, data)
    logger.info("데이터셋 수정 완료", dataset_id=dataset_id)
    return updated


@router.put("/{dataset_id}/meta-file", response_model=DatasetResponse)
async def replace_meta_file(
    dataset_id: str,
    req: DatasetMetaFileReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    """어노테이션 메타 파일 교체 (업로드 경로에서 관리 스토리지로 복사)."""
    logger.info("메타 파일 교체 요청", dataset_id=dataset_id, source=req.source_annotation_meta_file)
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        updated = await svc.replace_annotation_meta_file(dataset, req.source_annotation_meta_file)
    except ValueError as replace_error:
        raise HTTPException(status_code=400, detail=str(replace_error))
    logger.info("메타 파일 교체 완료", dataset_id=dataset_id, file=updated.annotation_meta_file)
    return updated


@router.post("/{dataset_id}/validate", response_model=FormatValidateResponse)
async def validate_dataset(
    dataset_id: str,
    req: DatasetValidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    이미 등록된 데이터셋의 어노테이션 검증 + 클래스 정보 DB 저장.

    관리 스토리지에 저장된 파일을 읽어 검증하고,
    성공 시 class_count, metadata(class_mapping)를 업데이트.
    """
    logger.info("데이터셋 검증 요청", dataset_id=dataset_id, annotation_format=req.annotation_format)
    svc = DatasetGroupService(db)
    try:
        result = await svc.validate_and_persist_class_info(dataset_id, req.annotation_format)
    except ValueError as validation_error:
        raise HTTPException(status_code=400, detail=str(validation_error))
    logger.info("데이터셋 검증 완료", dataset_id=dataset_id, valid=result.valid)
    return result


@router.delete("/{dataset_id}", response_model=MessageResponse)
async def delete_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dataset 소프트 삭제. 버전 이력은 보존된다."""
    logger.info("데이터셋 삭제 요청", dataset_id=dataset_id)
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    await svc.delete_dataset(dataset)
    logger.info(
        "데이터셋 소프트 삭제 완료",
        dataset_id=dataset_id,
        split=dataset.split,
        version=dataset.version,
    )
    return MessageResponse(message=f"Dataset {dataset.split}/{dataset.version} 삭제 완료")


# ─────────────────────────────────────────────────────────────────
# 데이터셋 뷰어 API
# ─────────────────────────────────────────────────────────────────


@router.get("/{dataset_id}/samples", response_model=SampleListResponse)
async def get_dataset_samples(
    dataset_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    데이터셋 이미지 + annotation 목록 조회 (페이지네이션).
    이미지 URL은 nginx static 서빙 경로로 반환된다.
    """
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return svc.get_sample_list(dataset, page=page, page_size=page_size)


@router.get("/{dataset_id}/eda", response_model=EdaStatsResponse)
async def get_dataset_eda(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    데이터셋 EDA 통계 조회.
    클래스 분포, bbox 크기 분포, 이미지 해상도 범위 등 자동 분석 결과.
    """
    svc = DatasetGroupService(db)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return svc.get_eda_stats(dataset)


@router.get("/{dataset_id}/lineage", response_model=LineageGraphResponse)
async def get_dataset_lineage(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    데이터셋 lineage 그래프 조회.
    현재 데이터셋의 upstream(부모) 전체를 재귀적으로 탐색하여
    React Flow 형식(nodes + edges)으로 반환한다.
    """
    # 대상 데이터셋 존재 확인
    target_result = await db.execute(
        select(Dataset)
        .where(Dataset.id == dataset_id, Dataset.deleted_at.is_(None))
        .options(selectinload(Dataset.group))
    )
    target_dataset = target_result.scalar_one_or_none()
    if not target_dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # BFS로 upstream lineage 탐색
    visited_dataset_ids: set[str] = set()
    queue = [dataset_id]
    lineage_edges: list[DatasetLineage] = []
    dataset_map: dict[str, Dataset] = {dataset_id: target_dataset}

    while queue:
        current_id = queue.pop(0)
        if current_id in visited_dataset_ids:
            continue
        visited_dataset_ids.add(current_id)

        # 이 데이터셋이 child인 lineage 엣지 조회 (= 부모 찾기)
        edge_result = await db.execute(
            select(DatasetLineage)
            .where(DatasetLineage.child_id == current_id)
            .options(
                selectinload(DatasetLineage.parent).selectinload(Dataset.group)
            )
        )
        edges = list(edge_result.scalars().all())

        for edge in edges:
            lineage_edges.append(edge)
            parent = edge.parent
            if parent and parent.id not in dataset_map:
                dataset_map[parent.id] = parent
                queue.append(parent.id)

    # 또한 이 데이터셋이 parent인 엣지도 조회 (= 자식, downstream 1단계만)
    downstream_result = await db.execute(
        select(DatasetLineage)
        .where(DatasetLineage.parent_id == dataset_id)
        .options(
            selectinload(DatasetLineage.child).selectinload(Dataset.group)
        )
    )
    downstream_edges = list(downstream_result.scalars().all())
    for edge in downstream_edges:
        lineage_edges.append(edge)
        child = edge.child
        if child and child.id not in dataset_map:
            dataset_map[child.id] = child

    # pipeline.png 존재 여부 확인을 위한 storage 클라이언트
    from app.core.storage import get_storage_client
    storage = get_storage_client()

    # React Flow 형식으로 변환
    nodes = []
    for ds in dataset_map.values():
        group = ds.group
        # pipeline.png가 존재하면 서빙 URL 포함
        pipeline_image_url = None
        if ds.storage_uri:
            png_path = storage.resolve_path(ds.storage_uri) / "pipeline.png"
            if png_path.exists():
                pipeline_image_url = storage.get_image_serve_url(
                    f"{ds.storage_uri}/pipeline.png"
                )

        nodes.append(LineageNodeResponse(
            id=ds.id,
            dataset_id=ds.id,
            group_name=group.name if group else "Unknown",
            split=ds.split,
            version=ds.version,
            dataset_type=group.dataset_type if group else "UNKNOWN",
            status=ds.status,
            image_count=ds.image_count,
            pipeline_image_url=pipeline_image_url,
        ))

    edges = []
    seen_edge_ids: set[str] = set()
    for edge in lineage_edges:
        if edge.id not in seen_edge_ids:
            seen_edge_ids.add(edge.id)

            # transform_config에서 manipulator 요약 생성
            pipeline_summary = _build_pipeline_summary(edge.transform_config)

            edges.append(LineageEdgeResponse(
                id=edge.id,
                source=edge.parent_id,
                target=edge.child_id,
                transform_config=edge.transform_config,
                pipeline_summary=pipeline_summary,
            ))

    return LineageGraphResponse(nodes=nodes, edges=edges)


def _build_pipeline_summary(transform_config: dict | None) -> str | None:
    """
    transform_config(PipelineConfig dict)에서 태스크 목록을 요약 문자열로 반환.
    예: "format_convert_to_coco → filter_final_classes"
    파싱 실패 시 None.
    """
    if not transform_config:
        return None
    try:
        tasks = transform_config.get("tasks", {})
        if not tasks:
            return None

        # topological order가 없으므로, 간단히 operator 이름을 나열
        operators = [
            task_conf.get("operator", "?")
            for task_conf in tasks.values()
        ]
        return " → ".join(operators)
    except Exception:
        return None
