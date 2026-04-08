"""
rotate_image — 이미지 회전 (AUGMENT).

이미지를 지정한 각도(90°, 180°, 270°)만큼 시계 방향으로 회전한다.
annotation의 bbox 좌표도 함께 회전한다.

params:
    degrees: int — 회전 각도. 90 | 180 | 270 (필수, 기본값 180)

처리 흐름 (2단계):
    1. transform_annotation: bbox 좌표를 회전 각도에 맞게 변환
       - width/height가 없는 이미지(YOLO 정규화 좌표)는 정규화 좌표 기준으로 변환
       - 90°/270° 회전 시 width ↔ height 교환
    2. build_image_manipulation: ImageManipulationSpec 반환
       - 실제 이미지 I/O는 ImageMaterializer가 Phase B에서 수행

좌표 변환 공식 (COCO [x, y, w, h]):
    180°: [W - x - w, H - y - h, w, h]
    90°:  [H - y - h, x, h, w]     (시계 방향)
    270°: [y, W - x - w, h, w]     (반시계 방향)
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import (
    Annotation,
    DatasetMeta,
    ImageManipulationSpec,
    ImageRecord,
)

logger = logging.getLogger(__name__)

VALID_DEGREES = {90, 180, 270}


class RotateImage(UnitManipulator):
    """
    이미지를 지정 각도로 회전하는 AUGMENT manipulator.

    annotation bbox 좌표를 자동 변환하고,
    이미지 변환 명세(ImageManipulationSpec)를 생성한다.
    실제 이미지 회전은 ImageMaterializer가 Phase B에서 수행한다.

    DB seed name: "rotate_image"
    """

    REQUIRED_PARAMS = ["degrees"]

    @property
    def name(self) -> str:
        return "rotate_image"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        모든 image_record의 bbox를 회전 각도에 맞게 변환한다.

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - degrees: int — 90 | 180 | 270
            context: 실행 컨텍스트 (선택)

        Returns:
            bbox가 변환된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때
            ValueError: degrees가 유효하지 않을 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "rotate_image는 단건 DatasetMeta만 입력 가능합니다."
            )

        degrees = int(params.get("degrees", 180))
        if degrees not in VALID_DEGREES:
            raise ValueError(
                f"degrees는 {VALID_DEGREES} 중 하나여야 합니다. 입력값: {degrees}"
            )

        rotated_meta = copy.deepcopy(input_meta)

        for record in rotated_meta.image_records:
            image_width = record.width
            image_height = record.height

            # width/height가 None이면 정규화 좌표(0~1) 기준으로 처리
            # YOLO skip_image_sizes=True 등에서 발생
            use_normalized = image_width is None or image_height is None
            if use_normalized:
                image_width = 1
                image_height = 1

            for annotation in record.annotations:
                if annotation.bbox is not None:
                    annotation.bbox = _rotate_bbox(
                        annotation.bbox, degrees, image_width, image_height,
                    )

            # 90°/270° 회전 시 width ↔ height 교환
            if degrees in (90, 270) and not use_normalized:
                record.width, record.height = record.height, record.width

            # 이미지 변환 명세를 record.extra에 누적
            # Phase B의 _build_image_plans에서 추출하여 ImagePlan.specs에 넣는다
            existing_specs = record.extra.get("image_manipulation_specs", [])
            existing_specs.append({
                "operation": "rotate_image",
                "params": {"degrees": degrees},
            })
            record.extra["image_manipulation_specs"] = existing_specs

        logger.info(
            "rotate_image 완료: %d장 이미지 × %d° 회전",
            len(rotated_meta.image_records), degrees,
        )

        return rotated_meta

    def build_image_manipulation(
        self,
        image_record: ImageRecord,
        params: dict[str, Any],
    ) -> list[ImageManipulationSpec]:
        """이미지 회전 변환 명세를 반환한다."""
        degrees = int(params.get("degrees", 180))
        return [ImageManipulationSpec(
            operation="rotate_image",
            params={"degrees": degrees},
        )]


def _rotate_bbox(
    bbox: list[float],
    degrees: int,
    image_width: int,
    image_height: int,
) -> list[float]:
    """
    COCO 형식 bbox [x, y, w, h]를 시계 방향으로 회전한다.

    Args:
        bbox: [x, y, w, h] — 좌상단 기준
        degrees: 90 | 180 | 270
        image_width: 이미지 너비 (정규화 좌표 시 1)
        image_height: 이미지 높이 (정규화 좌표 시 1)

    Returns:
        회전된 [x, y, w, h]
    """
    bx, by, bw, bh = bbox

    if degrees == 180:
        return [image_width - bx - bw, image_height - by - bh, bw, bh]
    elif degrees == 90:
        # 시계 방향 90°: (x,y) → (H-y-h, x), (w,h) → (h,w)
        return [image_height - by - bh, bx, bh, bw]
    elif degrees == 270:
        # 반시계 방향 90° (= 시계 270°): (x,y) → (y, W-x-w), (w,h) → (h,w)
        return [by, image_width - bx - bw, bh, bw]
    else:
        return bbox
