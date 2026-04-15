"""
det_mask_region_by_class — 이미지 마스킹 (AUGMENT).

지정한 class의 bbox 영역을 검정색 또는 흰색으로 채워 마스킹한다.
annotation 자체는 유지하고, 이미지만 변형한다.

params:
    class_names: str — 마스킹할 class 이름 (줄바꿈 구분, 필수)
    fill_color: str — "black" | "white" (필수, 기본값 "black")

처리 흐름:
    1. transform_annotation: 마스킹 대상 bbox 정보를 image_manipulation_specs에 누적
       - annotation은 변경하지 않음 (마스킹은 이미지만 변형)
    2. ImageMaterializer가 Phase B에서 실제 이미지에 사각형 채우기 수행
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import (
    DatasetMeta,
    ImageManipulationSpec,
    ImageRecord,
)

logger = logging.getLogger(__name__)

VALID_FILL_COLORS = {"black", "white"}


class MaskRegionByClass(UnitManipulator):
    """
    지정 class의 bbox 영역을 채워서 마스킹하는 AUGMENT manipulator.

    annotation은 그대로 유지하고, 이미지의 해당 영역만 단색으로 채운다.
    실제 이미지 처리는 ImageMaterializer가 Phase B에서 수행한다.

    DB seed name: "det_mask_region_by_class"
    """

    REQUIRED_PARAMS = ["class_names"]

    @property
    def name(self) -> str:
        return "det_mask_region_by_class"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        마스킹 대상 bbox를 수집하여 image_manipulation_specs에 누적한다.

        annotation 자체는 변경하지 않는다 — 마스킹은 이미지 레벨 변형이다.

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - class_names: str — 줄바꿈 구분된 class 이름 목록
                - fill_color: str — "black" | "white" (기본 "black")
            context: 실행 컨텍스트 (선택)

        Returns:
            image_manipulation_specs가 추가된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때
            ValueError: class_names가 비어있을 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "det_mask_region_by_class는 단건 DatasetMeta만 입력 가능합니다."
            )

        # class_names 파싱
        raw_names = params.get("class_names", "")
        if isinstance(raw_names, list):
            target_names = set(n.strip() for n in raw_names if n.strip())
        else:
            target_names = set(
                line.strip() for line in str(raw_names).split("\n") if line.strip()
            )

        if not target_names:
            raise ValueError(
                "class_names가 비어있습니다. 마스킹할 class 이름을 하나 이상 입력하세요."
            )

        fill_color = params.get("fill_color", "black")
        if fill_color not in VALID_FILL_COLORS:
            fill_color = "black"

        masked_meta = copy.deepcopy(input_meta)

        # 매칭되지 않는 이름 경고
        existing_names = set(masked_meta.categories)
        matched_names = target_names & existing_names
        unmatched_names = target_names - existing_names
        if unmatched_names:
            logger.warning(
                "det_mask_region_by_class: categories에 존재하지 않는 class 이름: %s (무시됨)",
                ", ".join(sorted(unmatched_names)),
            )

        # 이미지별로 마스킹 대상 bbox를 수집하여 specs에 누적
        total_mask_count = 0
        for record in masked_meta.image_records:
            mask_bboxes = []
            for annotation in record.annotations:
                if annotation.category_name in target_names and annotation.bbox:
                    mask_bboxes.append(annotation.bbox)

            if not mask_bboxes:
                continue

            total_mask_count += len(mask_bboxes)

            # image_manipulation_specs에 누적
            existing_specs = record.extra.get("image_manipulation_specs", [])
            existing_specs.append({
                "operation": "mask_region",
                "params": {
                    "bboxes": mask_bboxes,
                    "fill_color": fill_color,
                    "bbox_normalized": record.width is None,
                },
            })
            record.extra["image_manipulation_specs"] = existing_specs

        logger.info(
            "det_mask_region_by_class 완료: 대상 class %d개, 마스킹 bbox %d개, 이미지 %d장",
            len(matched_names), total_mask_count, len(masked_meta.image_records),
        )

        return masked_meta

    def build_image_manipulation(
        self,
        image_record: ImageRecord,
        params: dict[str, Any],
    ) -> list[ImageManipulationSpec]:
        """이미지 마스킹 변환 명세를 반환한다."""
        return [ImageManipulationSpec(
            operation="mask_region",
            params=params,
        )]
