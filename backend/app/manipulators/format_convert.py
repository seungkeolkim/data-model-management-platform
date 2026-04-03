"""
포맷 변환 Manipulator (COCO ↔ YOLO).

PER_SOURCE scope 전용.
변환 시 표준 COCO 80 클래스 매핑 테이블을 기본으로 사용하고,
사용자 지정 매핑이 있으면 override한다.

내부 bbox 좌표([x, y, w, h] absolute)는 건드리지 않는다.
실제 좌표계 변환(absolute ↔ normalized)은 IO 계층(coco_io, yolo_io)에서 수행한다.
"""
from __future__ import annotations

import copy
from typing import Any

from app.pipeline.io.class_mapping import (
    build_coco_to_yolo_remap,
    build_yolo_to_coco_remap,
)
from app.pipeline.manipulator import UnitManipulator
from app.pipeline.models import DatasetMeta, ImageManipulationSpec, ImageRecord


def _apply_category_id_remap(
    meta: DatasetMeta,
    remap_table: dict[int, int],
) -> None:
    """
    DatasetMeta 내 모든 annotation의 category_id를 remap_table에 따라 변환한다.
    meta를 직접 수정한다 (in-place).

    remap_table에 없는 category_id는 변경하지 않고 경고 로깅한다.
    """
    import logging
    logger = logging.getLogger(__name__)

    for image_record in meta.image_records:
        for annotation in image_record.annotations:
            original_id = annotation.category_id
            if original_id in remap_table:
                annotation.category_id = remap_table[original_id]
            else:
                logger.warning(
                    "리매핑 테이블에 없는 category_id 발견: %d (이미지: %s). "
                    "원본 ID를 유지합니다.",
                    original_id, image_record.file_name,
                )


class FormatConvertToYolo(UnitManipulator):
    """
    COCO → YOLO 포맷 변환.

    변환 내용:
      - annotation_format: "COCO" → "YOLO"
      - category_id: COCO 비순차 ID → YOLO 0-based 순차 ID로 리매핑
      - categories: YOLO 순차 ID 기준으로 재구성
      - bbox 좌표: 불변 (내부적으로 항상 COCO absolute 유지)

    리매핑 우선순위:
      1. params["class_id_mapping"]이 있으면 최우선 적용
      2. 표준 COCO 80 클래스 테이블에서 매칭
      3. 미지의 클래스 → 80번부터 순차 할당

    DB seed name: "format_convert_to_yolo"
    """

    @property
    def name(self) -> str:
        return "format_convert_to_yolo"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        COCO DatasetMeta를 YOLO DatasetMeta로 변환한다.

        Args:
            input_meta: COCO format의 DatasetMeta (단건만 허용)
            params: 선택적 파라미터
                - class_id_mapping: dict[int, int] — {coco_id: yolo_id} 커스텀 매핑
            context: 실행 컨텍스트 (선택)

        Returns:
            annotation_format="YOLO", category_id 리매핑된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때 (PER_SOURCE 전용)
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "format_convert_to_yolo는 PER_SOURCE 전용입니다. "
                "단건 DatasetMeta만 입력 가능합니다."
            )

        converted_meta = copy.deepcopy(input_meta)
        converted_meta.annotation_format = "YOLO"

        # 리매핑 테이블 구성 (표준 + 커스텀)
        custom_mapping = params.get("class_id_mapping")
        remap_table, new_categories = build_coco_to_yolo_remap(
            converted_meta.categories,
            custom_mapping=custom_mapping,
        )

        # category_id 리매핑 적용
        _apply_category_id_remap(converted_meta, remap_table)
        converted_meta.categories = new_categories

        return converted_meta


class FormatConvertToCoco(UnitManipulator):
    """
    YOLO → COCO 포맷 변환.

    변환 내용:
      - annotation_format: "YOLO" → "COCO"
      - category_id: YOLO 0-based 순차 ID → COCO 비순차 ID로 리매핑
      - categories: COCO ID 기준으로 재구성 (category_names로 이름 지정 가능)
      - bbox 좌표: 불변

    리매핑 우선순위:
      1. params["class_id_mapping"]이 있으면 최우선 적용
      2. 표준 COCO 80 클래스 테이블에서 매칭
      3. 미지의 클래스 → 91번부터 순차 할당

    DB seed name: "format_convert_to_coco"
    params_schema: category_names (textarea, required)
    """

    @property
    def name(self) -> str:
        return "format_convert_to_coco"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        YOLO DatasetMeta를 COCO DatasetMeta로 변환한다.

        Args:
            input_meta: YOLO format의 DatasetMeta (단건만 허용)
            params: 파라미터
                - category_names: list[str] — 클래스 이름 목록 (id 순서대로).
                    있으면 리매핑 전에 categories의 name을 업데이트한다.
                - class_id_mapping: dict[int, int] — {yolo_id: coco_id} 커스텀 매핑
            context: 실행 컨텍스트 (선택)

        Returns:
            annotation_format="COCO", category_id 리매핑된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때 (PER_SOURCE 전용)
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "format_convert_to_coco는 PER_SOURCE 전용입니다. "
                "단건 DatasetMeta만 입력 가능합니다."
            )

        converted_meta = copy.deepcopy(input_meta)
        converted_meta.annotation_format = "COCO"

        # category_names로 이름 업데이트 (리매핑 전에 적용)
        category_names = params.get("category_names")
        if category_names:
            for idx, category_name in enumerate(category_names):
                if idx < len(converted_meta.categories):
                    converted_meta.categories[idx]["name"] = category_name

        # 리매핑 테이블 구성 (표준 + 커스텀)
        custom_mapping = params.get("class_id_mapping")
        remap_table, new_categories = build_yolo_to_coco_remap(
            converted_meta.categories,
            custom_mapping=custom_mapping,
        )

        # category_id 리매핑 적용
        _apply_category_id_remap(converted_meta, remap_table)
        converted_meta.categories = new_categories

        return converted_meta
