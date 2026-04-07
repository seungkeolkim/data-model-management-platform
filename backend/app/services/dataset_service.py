"""
DatasetGroup 비즈니스 로직 서비스
"""
from __future__ import annotations

import json
import random
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import app_config, settings
from app.core.storage import get_storage_client
from app.models.all_models import Dataset, DatasetGroup
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupUpdate,
    DatasetRegisterRequest,
    DatasetUpdate,
    FormatValidateRequest,
    FormatValidateResponse,
)

logger = structlog.get_logger(__name__)


class DatasetGroupService:
    """DatasetGroup CRUD + 비즈니스 로직."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.storage = get_storage_client()

    # -------------------------------------------------------------------------
    # 목록 조회
    # -------------------------------------------------------------------------

    async def list_groups(
        self,
        page: int = 1,
        page_size: int = 20,
        dataset_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[DatasetGroup], int]:
        """데이터셋 그룹 목록 조회 (페이지네이션). 소프트 삭제된 그룹은 제외."""
        query = (
            select(DatasetGroup)
            .where(DatasetGroup.deleted_at.is_(None))
            .options(
                selectinload(DatasetGroup.datasets.and_(Dataset.deleted_at.is_(None)))
            )
        )

        if dataset_type:
            query = query.where(DatasetGroup.dataset_type == dataset_type.upper())
        if search:
            query = query.where(DatasetGroup.name.ilike(f"%{search}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        query = query.offset((page - 1) * page_size).limit(page_size)
        query = query.order_by(DatasetGroup.updated_at.desc())

        result = await self.db.execute(query)
        groups = list(result.scalars().all())
        return groups, total

    # -------------------------------------------------------------------------
    # 단건 조회
    # -------------------------------------------------------------------------

    async def get_group(self, group_id: str) -> DatasetGroup | None:
        """단건 DatasetGroup 조회 (datasets 포함). 소프트 삭제된 그룹은 제외."""
        result = await self.db.execute(
            select(DatasetGroup)
            .where(DatasetGroup.id == group_id, DatasetGroup.deleted_at.is_(None))
            .options(
                selectinload(DatasetGroup.datasets.and_(Dataset.deleted_at.is_(None)))
            )
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # 생성
    # -------------------------------------------------------------------------

    async def create_group(self, data: DatasetGroupCreate) -> DatasetGroup:
        """DatasetGroup 생성. 활성 그룹 중 동일 이름이 있으면 거부."""
        existing = await self.db.execute(
            select(DatasetGroup).where(
                DatasetGroup.name == data.name,
                DatasetGroup.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"동일한 이름의 데이터셋 그룹이 이미 존재합니다: '{data.name}'")

        group = DatasetGroup(
            id=str(uuid.uuid4()),
            **data.model_dump(),
        )
        self.db.add(group)
        await self.db.flush()
        await self.db.refresh(group, ["datasets"])
        return group

    # -------------------------------------------------------------------------
    # 수정
    # -------------------------------------------------------------------------

    async def update_group(self, group: DatasetGroup, data: DatasetGroupUpdate) -> DatasetGroup:
        """DatasetGroup 수정."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(group, field, value)
        await self.db.flush()
        await self.db.refresh(group)
        return group

    # -------------------------------------------------------------------------
    # 삭제
    # -------------------------------------------------------------------------

    async def delete_group(self, group: DatasetGroup) -> int:
        """
        DatasetGroup 소프트 삭제.
        하위 활성 데이터셋의 스토리지 파일을 먼저 삭제한 뒤 DB를 소프트 삭제한다.
        삭제된 레코드의 버전 이력은 보존되어 다음 버전 자동 계산에 반영된다.
        반환값: 함께 삭제된 데이터셋 수.
        """
        # 하위 활성 데이터셋의 스토리지 파일 삭제
        active_datasets_result = await self.db.execute(
            select(Dataset)
            .where(Dataset.group_id == group.id, Dataset.deleted_at.is_(None))
        )
        active_datasets = list(active_datasets_result.scalars().all())

        for dataset in active_datasets:
            self._delete_dataset_storage(dataset.storage_uri)

        # DB 소프트 삭제
        now = datetime.utcnow()
        group.deleted_at = now

        await self.db.execute(
            update(Dataset)
            .where(Dataset.group_id == group.id, Dataset.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        await self.db.flush()
        return len(active_datasets)

    async def delete_dataset(self, dataset: Dataset) -> None:
        """
        Dataset 개별 소프트 삭제.
        스토리지 파일을 먼저 삭제한 뒤 DB를 소프트 삭제한다.
        삭제된 레코드의 버전 이력은 보존되어 다음 버전 자동 계산에 반영된다.
        """
        self._delete_dataset_storage(dataset.storage_uri)
        dataset.deleted_at = datetime.utcnow()
        await self.db.flush()

    def _delete_dataset_storage(self, storage_uri: str) -> None:
        """데이터셋의 스토리지 디렉토리 삭제. 실패해도 예외를 전파하지 않는다."""
        try:
            self.storage.delete_dataset_directory(storage_uri)
        except Exception as storage_error:
            logger.error(
                "스토리지 파일 삭제 실패 (DB 삭제는 계속 진행)",
                storage_uri=storage_uri,
                error=str(storage_error),
            )

    # -------------------------------------------------------------------------
    # GUI 등록 (파일 브라우저 방식)
    # -------------------------------------------------------------------------

    async def register_dataset(self, req: DatasetRegisterRequest) -> tuple[DatasetGroup, Dataset]:
        """
        GUI Dataset 등록 (파일 브라우저 방식).

        1. source_image_dir, source_annotation_files 경로 검증
        2. DatasetGroup 신규 생성 또는 기존 그룹에 추가
        3. 버전 자동 생성
        4. Dataset DB 즉시 저장 (status=PROCESSING)
        5. Celery 태스크로 파일 복사 dispatch

        원본 파일은 복사(copy)하며 삭제하지 않음.
        파일 복사는 Celery worker에서 비동기로 수행된다.
        """
        from app.tasks.register_tasks import register_dataset as register_dataset_task

        # ------------------------------------------------------------------
        # 소스 경로 검증
        # ------------------------------------------------------------------
        logger.info("소스 경로 검증 시작", image_dir=req.source_image_dir, annotation_count=len(req.source_annotation_files))
        image_dir = self._validate_browse_path(req.source_image_dir, expect_dir=True)
        annotation_paths = [
            self._validate_browse_path(p, expect_dir=False)
            for p in req.source_annotation_files
        ]
        # 어노테이션 메타 파일 경로 검증 (선택사항)
        annotation_meta_path: Path | None = None
        if req.source_annotation_meta_file:
            annotation_meta_path = self._validate_browse_path(
                req.source_annotation_meta_file, expect_dir=False
            )
        logger.info("소스 경로 검증 완료")

        # 어노테이션 파일명 중복 검사
        filenames = [p.name for p in annotation_paths]
        if len(filenames) != len(set(filenames)):
            raise ValueError("어노테이션 파일명이 중복됩니다. 파일명이 다른 파일을 선택하세요.")

        # ------------------------------------------------------------------
        # 그룹 처리
        # ------------------------------------------------------------------
        if req.group_id:
            logger.info("기존 그룹에 추가", group_id=req.group_id)
            result = await self.db.execute(
                select(DatasetGroup).where(DatasetGroup.id == req.group_id)
            )
            group = result.scalar_one_or_none()
            if not group:
                raise ValueError(f"DatasetGroup을 찾을 수 없습니다: {req.group_id}")
            logger.info("기존 그룹 확인됨", group_name=group.name)
        else:
            existing = await self.db.execute(
                select(DatasetGroup).where(
                    DatasetGroup.name == req.group_name,
                    DatasetGroup.deleted_at.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError(
                    f"동일한 이름의 데이터셋 그룹이 이미 존재합니다: '{req.group_name}'\n"
                    f"기존 그룹에 추가하려면 group_id를 지정하세요."
                )
            logger.info("신규 그룹 생성", group_name=req.group_name)
            group = DatasetGroup(
                id=str(uuid.uuid4()),
                name=req.group_name,
                dataset_type="RAW",
                annotation_format=req.annotation_format,
                task_types=req.task_types,
                modality=req.modality,
                source_origin=req.source_origin,
                description=req.description,
            )
            self.db.add(group)
            await self.db.flush()
            logger.info("신규 그룹 DB 저장 완료", group_id=group.id)

        # ------------------------------------------------------------------
        # 버전 자동 생성
        # ------------------------------------------------------------------
        version = await self._next_version(group.id, req.split)
        logger.info("버전 자동 생성", version=version, split=req.split)

        dup = await self.db.execute(
            select(Dataset).where(
                Dataset.group_id == group.id,
                Dataset.split == req.split.upper(),
                Dataset.version == version,
                Dataset.deleted_at.is_(None),
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(
                f"동일한 split/version 데이터셋이 이미 존재합니다: "
                f"split={req.split}, version={version}"
            )

        # ------------------------------------------------------------------
        # storage_uri 결정 + Dataset 즉시 생성 (PROCESSING)
        # ------------------------------------------------------------------
        group_name = group.name
        storage_uri = self.storage.build_dataset_uri("RAW", group_name, req.split, version)

        dataset = Dataset(
            id=str(uuid.uuid4()),
            group_id=group.id,
            split=req.split.upper(),
            version=version,
            annotation_format=req.annotation_format,
            storage_uri=storage_uri,
            status="PROCESSING",
            image_count=None,
            class_count=None,
            annotation_files=None,
            annotation_meta_file=None,
        )
        self.db.add(dataset)
        await self.db.flush()
        logger.info("Dataset DB 저장 완료 (PROCESSING)", dataset_id=dataset.id)

        # ------------------------------------------------------------------
        # Celery 태스크 dispatch — 파일 복사는 worker에서 비동기 수행
        # ------------------------------------------------------------------
        register_dataset_task.delay(
            dataset_id=dataset.id,
            storage_uri=storage_uri,
            source_image_dir=str(image_dir),
            source_annotation_files=[str(p) for p in annotation_paths],
            source_annotation_meta_file=str(annotation_meta_path) if annotation_meta_path else None,
            annotation_format=req.annotation_format,
        )
        logger.info("Celery 파일 복사 태스크 dispatch 완료", dataset_id=dataset.id)

        return group, dataset

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _validate_browse_path(self, path_str: str, expect_dir: bool) -> Path:
        """
        경로 존재 여부 및 타입 확인.
        docker-compose에서 LOCAL_UPLOAD_BASE만 마운트하므로 별도 경로 제한 불필요.
        expect_dir=True이면 디렉토리, False이면 파일이어야 함.
        """
        validated_path = Path(path_str)

        if not validated_path.exists():
            raise ValueError(f"경로가 존재하지 않습니다: {path_str}")

        if expect_dir and not validated_path.is_dir():
            raise ValueError(f"디렉토리가 아닙니다: {path_str}")

        if not expect_dir and not validated_path.is_file():
            raise ValueError(f"파일이 아닙니다: {path_str}")

        return validated_path

    # -------------------------------------------------------------------------
    # 포맷 검증
    # -------------------------------------------------------------------------

    def validate_annotation_format(self, req: FormatValidateRequest) -> FormatValidateResponse:
        """
        어노테이션 파일이 지정된 포맷에 맞는지 사전 검증.

        COCO: JSON 파싱 → images, annotations, categories 키 존재 + 요약 정보 반환
        YOLO: .txt 파일 → 각 라인이 'class_id x y w h' 형식인지 샘플 검사
        """
        format_name = req.annotation_format.upper()
        if format_name == "COCO":
            return self._validate_coco_format(req.annotation_files)
        elif format_name == "YOLO":
            return self._validate_yolo_format(
                req.annotation_files,
                annotation_meta_file=req.annotation_meta_file,
            )
        else:
            return FormatValidateResponse(
                valid=True,
                errors=[],
                summary={"message": f"{format_name} 포맷은 자동 검증을 지원하지 않습니다."},
            )

    def _validate_coco_format(self, annotation_file_paths: list[str]) -> FormatValidateResponse:
        """
        COCO JSON 포맷 검증.

        각 파일에 대해:
        1. JSON 파싱 가능 여부
        2. 필수 키 (images, annotations, categories) 존재 여부
        3. 데이터 요약 (이미지 수, 어노테이션 수, 카테고리 목록)
        """
        errors: list[str] = []
        total_image_count = 0
        total_annotation_count = 0
        all_category_names: list[str] = []
        file_summaries: list[dict] = []

        required_keys = {"images", "annotations", "categories"}

        for file_path_str in annotation_file_paths:
            file_path = Path(file_path_str)
            filename = file_path.name

            if not file_path.exists():
                errors.append(f"[{filename}] 파일이 존재하지 않습니다: {file_path_str}")
                continue

            if not file_path.suffix.lower() == ".json":
                errors.append(f"[{filename}] COCO 포맷은 .json 파일이어야 합니다.")
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as json_file:
                    data = json.load(json_file)
            except json.JSONDecodeError as json_error:
                errors.append(f"[{filename}] JSON 파싱 실패: {json_error}")
                continue
            except Exception as read_error:
                errors.append(f"[{filename}] 파일 읽기 실패: {read_error}")
                continue

            if not isinstance(data, dict):
                errors.append(f"[{filename}] 최상위 구조가 JSON 객체가 아닙니다.")
                continue

            # 필수 키 확인
            missing_keys = required_keys - set(data.keys())
            if missing_keys:
                errors.append(
                    f"[{filename}] 필수 키가 누락되었습니다: {', '.join(sorted(missing_keys))}"
                )
                continue

            # 타입 확인
            if not isinstance(data["images"], list):
                errors.append(f"[{filename}] 'images'가 배열이 아닙니다.")
                continue
            if not isinstance(data["annotations"], list):
                errors.append(f"[{filename}] 'annotations'가 배열이 아닙니다.")
                continue
            if not isinstance(data["categories"], list):
                errors.append(f"[{filename}] 'categories'가 배열이 아닙니다.")
                continue

            # 요약 정보 수집
            image_count = len(data["images"])
            annotation_count = len(data["annotations"])
            category_names = [
                cat.get("name", f"id={cat.get('id', '?')}")
                for cat in data["categories"]
            ]
            # 클래스 매핑 (id → name) 추출
            category_mapping = {
                str(cat.get("id", "?")): cat.get("name", f"id={cat.get('id', '?')}")
                for cat in data["categories"]
            }

            total_image_count += image_count
            total_annotation_count += annotation_count
            all_category_names.extend(category_names)

            file_summaries.append({
                "filename": filename,
                "image_count": image_count,
                "annotation_count": annotation_count,
                "category_count": len(category_names),
                "categories": category_names,
                "class_mapping": category_mapping,
            })

        is_valid = len(errors) == 0
        summary = None
        if is_valid:
            # 카테고리 중복 제거 (여러 파일에서 동일 카테고리가 나올 수 있음)
            unique_categories = sorted(set(all_category_names))
            # 전체 파일의 class_mapping을 합산 (동일 id면 덮어씀 — 정상적이면 일치)
            merged_class_mapping: dict[str, str] = {}
            for file_summary in file_summaries:
                merged_class_mapping.update(file_summary.get("class_mapping", {}))
            summary = {
                "total_image_count": total_image_count,
                "total_annotation_count": total_annotation_count,
                "total_category_count": len(unique_categories),
                "categories": unique_categories,
                "class_mapping": merged_class_mapping,
                "files": file_summaries,
            }

        return FormatValidateResponse(valid=is_valid, errors=errors, summary=summary)

    def _validate_yolo_format(
        self,
        annotation_file_paths: list[str],
        annotation_meta_file: str | None = None,
    ) -> FormatValidateResponse:
        """
        YOLO txt 포맷 검증.

        파일이 대량(수천~수만)일 경우 전체를 검사하면 과도하므로
        MAX_SAMPLE_FILES개를 랜덤 샘플링하여 검증.
        각 파일에 대해:
        1. .txt 확장자 확인
        2. 샘플 라인이 'class_id center_x center_y width height' 형식인지 확인
        3. 값 범위 확인 (좌표 0~1, class_id 정수)

        annotation_meta_file이 있으면 yaml을 파싱하여 class name 매핑에 활용한다.
        """
        errors: list[str] = []
        total_label_count = 0
        class_id_set: set[int] = set()
        max_sample_lines = 20  # 파일당 샘플 검사 라인 수
        max_sample_files = 50  # 대량 파일 시 검사할 최대 파일 수

        total_file_count = len(annotation_file_paths)
        is_sampled = total_file_count > max_sample_files

        # 대량 파일이면 랜덤 샘플링
        if is_sampled:
            sampled_paths = random.sample(annotation_file_paths, max_sample_files)
        else:
            sampled_paths = annotation_file_paths

        # 전체 파일에서 .txt 확장자 비율 빠르게 확인
        non_txt_count = sum(
            1 for p in annotation_file_paths if not p.lower().endswith(".txt")
        )
        if non_txt_count > 0:
            errors.append(
                f"전체 {total_file_count}개 파일 중 {non_txt_count}개가 .txt가 아닙니다."
            )

        for file_path_str in sampled_paths:
            file_path = Path(file_path_str)
            filename = file_path.name

            if not file_path.exists():
                errors.append(f"[{filename}] 파일이 존재하지 않습니다: {file_path_str}")
                continue

            if not file_path.suffix.lower() == ".txt":
                errors.append(f"[{filename}] YOLO 포맷은 .txt 파일이어야 합니다.")
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as txt_file:
                    lines = txt_file.readlines()
            except Exception as read_error:
                errors.append(f"[{filename}] 파일 읽기 실패: {read_error}")
                continue

            non_empty_lines = [line.strip() for line in lines if line.strip()]
            total_label_count += len(non_empty_lines)

            # 샘플 라인 검사
            sample_lines = non_empty_lines[:max_sample_lines]
            for line_number, line in enumerate(sample_lines, start=1):
                parts = line.split()
                if len(parts) != 5:
                    errors.append(
                        f"[{filename}:{line_number}] 5개 값이어야 합니다 "
                        f"(class_id x y w h), 실제: {len(parts)}개"
                    )
                    continue

                try:
                    class_id = int(parts[0])
                    if class_id < 0:
                        errors.append(f"[{filename}:{line_number}] class_id가 음수입니다: {class_id}")
                        continue
                    class_id_set.add(class_id)
                except ValueError:
                    errors.append(f"[{filename}:{line_number}] class_id가 정수가 아닙니다: {parts[0]}")
                    continue

                for idx, coord_name in enumerate(["x", "y", "w", "h"], start=1):
                    try:
                        value = float(parts[idx])
                        if not (0.0 <= value <= 1.0):
                            errors.append(
                                f"[{filename}:{line_number}] {coord_name}={value} — 0~1 범위를 벗어남"
                            )
                    except ValueError:
                        errors.append(
                            f"[{filename}:{line_number}] {coord_name}이 숫자가 아닙니다: {parts[idx]}"
                        )

        is_valid = len(errors) == 0
        summary = None
        if is_valid:
            sorted_class_ids = sorted(class_id_set)

            # 메타 파일(yaml)이 있으면 class name 매핑 추출
            class_names_from_meta: list[str] | None = None
            if annotation_meta_file:
                meta_path = Path(annotation_meta_file)
                if meta_path.exists():
                    from app.pipeline.io.yolo_io import parse_yolo_yaml
                    class_names_from_meta = parse_yolo_yaml(meta_path)

            # class_mapping 구성:
            # meta 파일이 있으면 전체 클래스 목록을 사용 (데이터 미등장 클래스 포함).
            # 이미지 추가 시 새로운 class가 등장해도 매핑이 이미 존재하도록 보장한다.
            if class_names_from_meta:
                class_mapping = {
                    str(cid): class_names_from_meta[cid]
                    for cid in range(len(class_names_from_meta))
                }
            else:
                class_mapping = {str(cid): str(cid) for cid in sorted_class_ids}

            # class_count: meta 파일이 있으면 전체 정의된 클래스 수, 없으면 데이터 등장 클래스 수
            effective_class_count = (
                len(class_names_from_meta) if class_names_from_meta else len(class_id_set)
            )

            summary = {
                "total_file_count": total_file_count,
                "sampled_file_count": len(sampled_paths) if is_sampled else total_file_count,
                "is_sampled": is_sampled,
                "total_label_count": total_label_count,
                "unique_class_ids": sorted_class_ids,
                "class_count": effective_class_count,
                "class_mapping": class_mapping,
            }

        return FormatValidateResponse(valid=is_valid, errors=errors, summary=summary)

    async def _next_version(self, group_id: str, split: str) -> str:
        """해당 group+split 의 다음 버전 자동 계산."""
        result = await self.db.execute(
            select(Dataset.version)
            .where(Dataset.group_id == group_id, Dataset.split == split.upper())
            .order_by(Dataset.created_at.desc())
            .limit(1)
        )
        last_version = result.scalar_one_or_none()
        if not last_version:
            return "v1.0.0"

        try:
            parts = last_version.lstrip("v").split(".")
            patch = int(parts[2]) + 1
            return f"v{parts[0]}.{parts[1]}.{patch}"
        except (IndexError, ValueError):
            return "v1.0.0"

    # -------------------------------------------------------------------------
    # Dataset 개별 조회 / 수정
    # -------------------------------------------------------------------------

    async def get_dataset(self, dataset_id: str) -> Dataset | None:
        """단건 Dataset 조회. 소프트 삭제된 데이터셋은 제외. group 관계도 함께 로드."""
        result = await self.db.execute(
            select(Dataset)
            .where(Dataset.id == dataset_id, Dataset.deleted_at.is_(None))
            .options(selectinload(Dataset.group))
        )
        return result.scalar_one_or_none()

    async def update_dataset(self, dataset: Dataset, data: DatasetUpdate) -> Dataset:
        """
        Dataset 개별 수정 (부분 업데이트).
        annotation_format이 변경되면 기존 검증 결과(class_count, metadata)를 초기화한다.
        """
        update_data = data.model_dump(exclude_unset=True)

        # 포맷 변경 시 클래스 정보 초기화 — 재검증 필요
        new_format = update_data.get("annotation_format")
        if new_format and new_format != dataset.annotation_format:
            dataset.class_count = None
            dataset.metadata_ = None
            logger.info(
                "포맷 변경으로 클래스 정보 초기화",
                dataset_id=dataset.id,
                old_format=dataset.annotation_format,
                new_format=new_format,
            )

        for field, value in update_data.items():
            setattr(dataset, field, value)
        await self.db.flush()
        await self.db.refresh(dataset)
        return dataset

    async def replace_annotation_meta_file(
        self, dataset: Dataset, source_meta_file_path: str
    ) -> Dataset:
        """
        기존 데이터셋의 어노테이션 메타 파일을 교체한다.

        1. 업로드 경로의 파일을 검증
        2. 데이터셋 루트 디렉토리로 복사 (기존 파일 덮어쓰기)
        3. DB의 annotation_meta_file 컬럼 업데이트

        Args:
            dataset: 대상 Dataset 객체
            source_meta_file_path: 교체할 메타 파일 절대경로 (업로드 경로)

        Returns:
            업데이트된 Dataset 객체
        """
        # 소스 파일 경로 검증
        validated_path = self._validate_browse_path(source_meta_file_path, expect_dir=False)

        # 관리 스토리지로 복사 (기존 파일이 있으면 덮어쓰기됨)
        new_filename = self.storage.copy_annotation_meta_file(validated_path, dataset.storage_uri)
        logger.info(
            "어노테이션 메타 파일 교체 완료",
            dataset_id=dataset.id,
            old_file=dataset.annotation_meta_file,
            new_file=new_filename,
        )

        # DB 업데이트
        dataset.annotation_meta_file = new_filename
        await self.db.flush()
        await self.db.refresh(dataset)
        return dataset

    # -------------------------------------------------------------------------
    # 클래스 정보 추출 및 저장
    # -------------------------------------------------------------------------

    def _resolve_annotation_absolute_paths(self, dataset: Dataset) -> list[str]:
        """
        Dataset의 storage_uri + annotation_files로 절대 경로 목록 구성.

        저장 구조: {LOCAL_STORAGE_BASE}/{storage_uri}/{annotations_dirname}/{filename}
        """
        base_path = Path(settings.local_storage_base) / dataset.storage_uri
        annotations_dir = base_path / app_config.annotations_dirname

        if not dataset.annotation_files:
            raise ValueError(f"어노테이션 파일 목록이 비어있습니다: dataset_id={dataset.id}")

        absolute_paths: list[str] = []
        for filename in dataset.annotation_files:
            file_path = annotations_dir / filename
            if not file_path.exists():
                raise ValueError(f"어노테이션 파일이 존재하지 않습니다: {file_path}")
            absolute_paths.append(str(file_path))

        return absolute_paths

    def _resolve_annotation_meta_absolute_path(self, dataset: Dataset) -> str | None:
        """
        Dataset의 annotation_meta_file이 있으면 절대 경로로 변환.
        메타 파일은 데이터셋 루트에 위치한다.
        """
        if not dataset.annotation_meta_file:
            return None
        base_path = Path(settings.local_storage_base) / dataset.storage_uri
        meta_path = base_path / dataset.annotation_meta_file
        if not meta_path.exists():
            logger.warning(
                "어노테이션 메타 파일이 존재하지 않음",
                path=str(meta_path), dataset_id=dataset.id,
            )
            return None
        return str(meta_path)

    async def _extract_and_persist_class_info(self, dataset: Dataset) -> None:
        """
        이미 저장된 데이터셋의 어노테이션 파일에서 클래스 정보를 추출하여 DB에 저장.
        register_dataset 직후 자동 호출용 (best-effort).
        """
        annotation_format = (dataset.annotation_format or "").upper()
        if annotation_format not in ("COCO", "YOLO"):
            return

        absolute_paths = self._resolve_annotation_absolute_paths(dataset)
        meta_abs_path = self._resolve_annotation_meta_absolute_path(dataset)
        validation_request = FormatValidateRequest(
            annotation_format=annotation_format,
            annotation_files=absolute_paths,
            annotation_meta_file=meta_abs_path,
        )
        result = self.validate_annotation_format(validation_request)

        if result.valid and result.summary:
            self._apply_class_info_to_dataset(dataset, result.summary, annotation_format)
            await self.db.flush()

    async def validate_and_persist_class_info(
        self, dataset_id: str, annotation_format: str
    ) -> FormatValidateResponse:
        """
        이미 등록된 데이터셋의 어노테이션을 검증하고 클래스 정보를 DB에 저장.

        상세 페이지에서 '검증' 버튼 클릭 시 호출.
        1. dataset의 storage_uri + annotation_files로 절대 경로 구성
        2. validate_annotation_format 호출
        3. 결과에서 class_count, class_mapping 추출하여 DB 업데이트
        """
        dataset = await self.get_dataset(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset을 찾을 수 없습니다: {dataset_id}")

        absolute_paths = self._resolve_annotation_absolute_paths(dataset)
        meta_abs_path = self._resolve_annotation_meta_absolute_path(dataset)
        validation_request = FormatValidateRequest(
            annotation_format=annotation_format.upper(),
            annotation_files=absolute_paths,
            annotation_meta_file=meta_abs_path,
        )
        result = self.validate_annotation_format(validation_request)

        if result.valid and result.summary:
            # 포맷 변경이 있으면 함께 업데이트
            dataset.annotation_format = annotation_format.upper()
            self._apply_class_info_to_dataset(
                dataset, result.summary, annotation_format.upper()
            )
            await self.db.flush()
            await self.db.refresh(dataset)
            logger.info(
                "클래스 정보 저장 완료",
                dataset_id=dataset_id,
                class_count=dataset.class_count,
            )

        return result

    @staticmethod
    def _apply_class_info_to_dataset(
        dataset: Dataset, summary: dict, annotation_format: str
    ) -> None:
        """검증 결과 summary에서 클래스 정보를 추출하여 Dataset 객체에 적용."""
        class_mapping = summary.get("class_mapping", {})

        if annotation_format == "COCO":
            class_count = summary.get("total_category_count", len(class_mapping))
        else:
            class_count = summary.get("class_count", len(class_mapping))

        dataset.class_count = class_count
        dataset.metadata_ = {
            "class_info": {
                "class_count": class_count,
                "class_mapping": class_mapping,
            },
        }

    # -------------------------------------------------------------------------
    # 데이터셋 뷰어: 샘플 인덱스 캐싱 + 샘플 목록 + EDA 통계
    # -------------------------------------------------------------------------

    SAMPLE_INDEX_FILENAME = "sample_index.json"

    def _load_dataset_meta(self, dataset: Dataset) -> "DatasetMeta | None":
        """
        데이터셋의 annotation 파일을 파싱하여 DatasetMeta로 반환.
        READY 상태이고 annotation_files가 있을 때만 동작.
        파싱 실패 시 None 반환.
        """
        annotation_format = dataset.annotation_format or dataset.group.annotation_format
        if not annotation_format or annotation_format == "NONE":
            return None
        if not dataset.annotation_files:
            return None

        try:
            from lib.pipeline.dag_executor import load_source_meta_from_storage
            return load_source_meta_from_storage(
                storage=self.storage,
                storage_uri=dataset.storage_uri,
                annotation_format=annotation_format,
                annotation_files=dataset.annotation_files,
                annotation_meta_file=dataset.annotation_meta_file,
                dataset_id=dataset.id,
                skip_image_sizes=True,
            )
        except Exception as parse_error:
            logger.warning(
                "annotation 파싱 실패",
                dataset_id=dataset.id,
                error=str(parse_error),
            )
            return None

    def _get_sample_index_path(self, dataset: Dataset) -> Path:
        """sample_index.json의 절대경로를 반환."""
        return self.storage.resolve_path(dataset.storage_uri) / self.SAMPLE_INDEX_FILENAME

    def _get_or_create_sample_index(self, dataset: Dataset) -> dict | None:
        """
        sample_index.json 캐시를 반환한다.
        파일이 있으면 읽어서 반환, 없으면 annotation을 파싱하여 생성 후 반환.

        캐시 구조:
            {
                "categories": [{"id": 1, "name": "person"}, ...],
                "images": [
                    {
                        "image_id": 1,
                        "file_name": "000001.jpg",
                        "width": 640,
                        "height": 480,
                        "annotation_count": 3,
                        "annotations": [
                            {"category_id": 1, "category_name": "person", "bbox": [...], "area": 1234.5},
                            ...
                        ]
                    },
                    ...
                ]
            }

        READY 데이터셋은 내용이 변하지 않으므로 캐시 무효화가 불필요하다.
        """
        index_path = self._get_sample_index_path(dataset)

        # 캐시 파일이 이미 있으면 읽기만 하고 반환
        if index_path.exists():
            try:
                return json.loads(index_path.read_text(encoding="utf-8"))
            except Exception as read_error:
                logger.warning(
                    "sample_index.json 읽기 실패 — 재생성",
                    dataset_id=dataset.id,
                    error=str(read_error),
                )

        # 캐시 없음 → annotation 전체 파싱 후 인덱스 생성
        meta = self._load_dataset_meta(dataset)
        if meta is None:
            return None

        category_id_to_name = {cat["id"]: cat["name"] for cat in meta.categories}

        images = []
        for record in meta.image_records:
            annotation_items = []
            for ann in record.annotations:
                area = None
                if ann.bbox and len(ann.bbox) == 4:
                    area = round(ann.bbox[2] * ann.bbox[3], 1)
                annotation_items.append({
                    "category_id": ann.category_id,
                    "category_name": category_id_to_name.get(
                        ann.category_id, str(ann.category_id)
                    ),
                    "bbox": ann.bbox,
                    "area": area,
                })

            images.append({
                "image_id": record.image_id,
                "file_name": record.file_name,
                "width": record.width,
                "height": record.height,
                "annotation_count": len(record.annotations),
                "annotations": annotation_items,
            })

        sample_index = {
            "categories": meta.categories,
            "images": images,
        }

        # 디스크에 캐시 저장
        try:
            index_path.write_text(
                json.dumps(sample_index, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "sample_index.json 생성 완료",
                dataset_id=dataset.id,
                image_count=len(images),
            )
        except Exception as write_error:
            logger.warning(
                "sample_index.json 저장 실패 — 캐시 없이 계속 진행",
                dataset_id=dataset.id,
                error=str(write_error),
            )

        return sample_index

    def get_sample_list(
        self,
        dataset: Dataset,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """
        데이터셋의 이미지 + annotation 목록을 페이지네이션하여 반환.
        sample_index.json 캐시가 있으면 파싱 없이 바로 응답한다.
        nginx static 서빙 URL을 포함한다.
        """
        sample_index = self._get_or_create_sample_index(dataset)
        if sample_index is None:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "categories": [],
            }

        all_images = sample_index["images"]
        total = len(all_images)

        # 이미지 서빙 URL base
        image_url_base = self.storage.get_image_serve_url(
            f"{dataset.storage_uri}/images"
        )

        start_index = (page - 1) * page_size
        end_index = min(start_index + page_size, total)
        page_images = all_images[start_index:end_index]

        # 각 이미지에 서빙 URL 부여
        items = []
        for image_entry in page_images:
            items.append({
                **image_entry,
                "image_url": f"{image_url_base}/{image_entry['file_name']}",
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "categories": sample_index["categories"],
        }

    def get_eda_stats(self, dataset: Dataset) -> dict:
        """
        데이터셋의 annotation을 분석하여 EDA 통계를 반환.
        sample_index.json 캐시가 있으면 파싱 없이 바로 계산한다.
        클래스 분포, bbox 크기 분포, 이미지 해상도 범위 등.
        """
        sample_index = self._get_or_create_sample_index(dataset)
        if sample_index is None:
            return {
                "total_images": dataset.image_count or 0,
                "total_annotations": 0,
                "total_classes": dataset.class_count or 0,
                "images_without_annotations": 0,
                "class_distribution": [],
                "bbox_area_distribution": [],
            }

        all_images = sample_index["images"]
        categories = sample_index["categories"]
        category_id_to_name = {cat["id"]: cat["name"] for cat in categories}

        # 클래스별 통계
        class_annotation_count: dict[int, int] = {}
        class_image_set: dict[int, set] = {}
        total_annotations = 0
        images_without_annotations = 0

        # 이미지 해상도 범위
        widths = []
        heights = []

        # bbox area 수집
        bbox_areas: list[float] = []

        for image_entry in all_images:
            if image_entry.get("width") is not None:
                widths.append(image_entry["width"])
            if image_entry.get("height") is not None:
                heights.append(image_entry["height"])

            annotations = image_entry.get("annotations", [])
            if not annotations:
                images_without_annotations += 1

            seen_categories_in_image: set[int] = set()
            for ann in annotations:
                total_annotations += 1
                category_id = ann["category_id"]
                class_annotation_count[category_id] = (
                    class_annotation_count.get(category_id, 0) + 1
                )
                seen_categories_in_image.add(category_id)

                if ann.get("bbox") and len(ann["bbox"]) == 4:
                    bbox_areas.append(ann["bbox"][2] * ann["bbox"][3])

            for category_id in seen_categories_in_image:
                if category_id not in class_image_set:
                    class_image_set[category_id] = set()
                class_image_set[category_id].add(image_entry["image_id"])

        # 클래스 분포 (annotation 수 내림차순)
        class_distribution = []
        for category_id, annotation_count in sorted(
            class_annotation_count.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            class_distribution.append({
                "category_id": category_id,
                "category_name": category_id_to_name.get(
                    category_id, str(category_id)
                ),
                "annotation_count": annotation_count,
                "image_count": len(class_image_set.get(category_id, set())),
            })

        # bbox 면적 분포 (구간별)
        bbox_area_distribution = _compute_bbox_area_distribution(bbox_areas)

        return {
            "total_images": len(all_images),
            "total_annotations": total_annotations,
            "total_classes": len(categories),
            "images_without_annotations": images_without_annotations,
            "class_distribution": class_distribution,
            "bbox_area_distribution": bbox_area_distribution,
            "image_width_min": min(widths) if widths else None,
            "image_width_max": max(widths) if widths else None,
            "image_height_min": min(heights) if heights else None,
            "image_height_max": max(heights) if heights else None,
        }


def _compute_bbox_area_distribution(
    bbox_areas: list[float],
) -> list[dict[str, str | int]]:
    """bbox 면적을 구간별로 분류하여 분포를 반환한다."""
    if not bbox_areas:
        return []

    # 고정 구간: 면적 기준
    bins = [
        (0, 1024, "Tiny (< 32²)"),
        (1024, 9216, "Small (32²–96²)"),
        (9216, 65536, "Medium (96²–256²)"),
        (65536, 262144, "Large (256²–512²)"),
        (262144, float("inf"), "XLarge (> 512²)"),
    ]
    distribution = []
    for low, high, label in bins:
        count = sum(1 for area in bbox_areas if low <= area < high)
        if count > 0:
            distribution.append({"range_label": label, "count": count})
    return distribution
