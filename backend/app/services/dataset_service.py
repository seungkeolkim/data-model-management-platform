"""
DatasetGroup 비즈니스 로직 서비스
"""
from __future__ import annotations

import json
import random
import shutil
import uuid
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.storage import get_storage_client
from app.models.all_models import Dataset, DatasetGroup
from app.schemas.dataset import (
    DatasetGroupCreate,
    DatasetGroupUpdate,
    DatasetRegisterRequest,
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
        """데이터셋 그룹 목록 조회 (페이지네이션)."""
        query = select(DatasetGroup).options(selectinload(DatasetGroup.datasets))

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
        """단건 DatasetGroup 조회 (datasets 포함)."""
        result = await self.db.execute(
            select(DatasetGroup)
            .where(DatasetGroup.id == group_id)
            .options(selectinload(DatasetGroup.datasets))
        )
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # 생성
    # -------------------------------------------------------------------------

    async def create_group(self, data: DatasetGroupCreate) -> DatasetGroup:
        """DatasetGroup 생성."""
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

    async def delete_group(self, group: DatasetGroup) -> None:
        """DatasetGroup 삭제 (CASCADE: datasets, lineage 함께 삭제)."""
        await self.db.delete(group)
        await self.db.flush()

    # -------------------------------------------------------------------------
    # GUI 등록 (파일 브라우저 방식)
    # -------------------------------------------------------------------------

    async def register_dataset(self, req: DatasetRegisterRequest) -> tuple[DatasetGroup, Dataset]:
        """
        GUI Dataset 등록 (파일 브라우저 방식).

        1. source_image_dir, source_annotation_files 경로 검증
        2. DatasetGroup 신규 생성 또는 기존 그룹에 추가
        3. 버전 자동 생성
        4. 관리 스토리지로 파일 복사
        5. Dataset DB 저장

        원본 파일은 복사(copy)하며 삭제하지 않음.
        """
        # ------------------------------------------------------------------
        # 소스 경로 검증
        # ------------------------------------------------------------------
        logger.info("소스 경로 검증 시작", image_dir=req.source_image_dir, annotation_count=len(req.source_annotation_files))
        image_dir = self._validate_browse_path(req.source_image_dir, expect_dir=True)
        annotation_paths = [
            self._validate_browse_path(p, expect_dir=False)
            for p in req.source_annotation_files
        ]
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
                select(DatasetGroup).where(DatasetGroup.name == req.group_name)
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
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(
                f"동일한 split/version 데이터셋이 이미 존재합니다: "
                f"split={req.split}, version={version}"
            )

        # ------------------------------------------------------------------
        # storage_uri 결정 및 파일 복사
        # ------------------------------------------------------------------
        group_name = group.name
        storage_uri = self.storage.build_dataset_uri("RAW", group_name, req.split, version)
        dest_abs = Path(settings.local_storage_base) / storage_uri
        logger.info("파일 복사 시작", storage_uri=storage_uri, dest=str(dest_abs))

        try:
            image_count = self.storage.copy_image_directory(image_dir, storage_uri)
            logger.info("이미지 폴더 복사 완료", image_count=image_count)
            annotation_filenames = self.storage.copy_annotation_files(annotation_paths, storage_uri)
            logger.info("어노테이션 파일 복사 완료", files=annotation_filenames)
        except Exception as e:
            logger.error("파일 복사 실패", error=str(e), storage_uri=storage_uri)
            # 복사 실패 시 부분 생성된 디렉토리 정리
            if dest_abs.exists():
                shutil.rmtree(dest_abs, ignore_errors=True)
                logger.info("부분 생성 디렉토리 정리 완료", path=str(dest_abs))
            raise ValueError(f"파일 복사 중 오류가 발생했습니다: {e}") from e

        # ------------------------------------------------------------------
        # Dataset DB 저장
        # ------------------------------------------------------------------
        logger.info("Dataset DB 저장 시작", group_id=group.id, split=req.split, version=version)
        dataset = Dataset(
            id=str(uuid.uuid4()),
            group_id=group.id,
            split=req.split.upper(),
            version=version,
            annotation_format=req.annotation_format,
            storage_uri=storage_uri,
            status="READY",
            image_count=image_count,
            class_count=None,
            annotation_files=annotation_filenames,
        )
        self.db.add(dataset)
        await self.db.flush()
        logger.info("Dataset DB 저장 완료", dataset_id=dataset.id)

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
        p = Path(path_str)

        if not p.exists():
            raise ValueError(f"경로가 존재하지 않습니다: {path_str}")

        if expect_dir and not p.is_dir():
            raise ValueError(f"디렉토리가 아닙니다: {path_str}")

        if not expect_dir and not p.is_file():
            raise ValueError(f"파일이 아닙니다: {path_str}")

        return p

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
            return self._validate_yolo_format(req.annotation_files)
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

            total_image_count += image_count
            total_annotation_count += annotation_count
            all_category_names.extend(category_names)

            file_summaries.append({
                "filename": filename,
                "image_count": image_count,
                "annotation_count": annotation_count,
                "category_count": len(category_names),
                "categories": category_names,
            })

        is_valid = len(errors) == 0
        summary = None
        if is_valid:
            # 카테고리 중복 제거 (여러 파일에서 동일 카테고리가 나올 수 있음)
            unique_categories = sorted(set(all_category_names))
            summary = {
                "total_image_count": total_image_count,
                "total_annotation_count": total_annotation_count,
                "total_category_count": len(unique_categories),
                "categories": unique_categories,
                "files": file_summaries,
            }

        return FormatValidateResponse(valid=is_valid, errors=errors, summary=summary)

    def _validate_yolo_format(self, annotation_file_paths: list[str]) -> FormatValidateResponse:
        """
        YOLO txt 포맷 검증.

        파일이 대량(수천~수만)일 경우 전체를 검사하면 과도하므로
        MAX_SAMPLE_FILES개를 랜덤 샘플링하여 검증.
        각 파일에 대해:
        1. .txt 확장자 확인
        2. 샘플 라인이 'class_id center_x center_y width height' 형식인지 확인
        3. 값 범위 확인 (좌표 0~1, class_id 정수)
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
            summary = {
                "total_file_count": total_file_count,
                "sampled_file_count": len(sampled_paths) if is_sampled else total_file_count,
                "is_sampled": is_sampled,
                "total_label_count": total_label_count,
                "unique_class_ids": sorted(class_id_set),
                "class_count": len(class_id_set),
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
