"""
filter_keep_images_containing_class_name — 지정 class 포함 이미지만 유지 (IMAGE_FILTER).

지정된 class 중 1개라도 annotation에 포함된 이미지만 남기고,
지정 class가 하나도 없는 이미지는 image_records에서 통째로 제거한다.

filter_remove_images_containing_class_name의 반대 동작:
  - filter_remove_images_containing_class_name: 지정 class 포함 → 이미지 제거
  - filter_keep_images_containing_class_name:   지정 class 포함 → 이미지 유지, 미포함 → 제거

params:
    class_names: list[str] | str — 유지 기준 class 이름 목록.
        GUI multiselect에서 리스트로 전달되거나, 줄바꿈 구분 문자열로 올 수 있다.

처리 흐름:
    1. class_names 파싱 → 유지 기준 class 이름 set 구성
    2. 각 image_record의 annotations 중 하나라도 해당 category_name을 포함하면 유지, 아니면 제거
    3. categories는 변경하지 않음 (카테고리 목록은 유지)
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta

logger = logging.getLogger(__name__)


class FilterKeepImagesContainingClassName(UnitManipulator):
    """
    지정된 class 중 1개라도 포함한 이미지만 유지하는 IMAGE_FILTER.

    OR 조건: 이미지의 annotation 중 하나라도 지정 class에 해당하면 유지한다.
    지정 class가 하나도 없는 이미지는 image_records에서 제거한다.

    DB seed name: "filter_keep_images_containing_class_name"
    """

    REQUIRED_PARAMS = ["class_names"]

    @property
    def name(self) -> str:
        return "filter_keep_images_containing_class_name"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        지정 class를 1개라도 포함한 이미지만 유지하고 나머지를 제거한다.

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - class_names: list[str] | str — 유지 기준 class 이름 목록
                  (multiselect → 리스트, textarea → 줄바꿈 구분 문자열)
            context: 실행 컨텍스트 (선택)

        Returns:
            이미지가 필터링된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때
            ValueError: class_names가 비어있을 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "filter_keep_images_containing_class_name는 단건 DatasetMeta만 입력 가능합니다."
            )

        raw_names = params.get("class_names", "")
        if isinstance(raw_names, list):
            keep_names = set(n.strip() for n in raw_names if n.strip())
        else:
            keep_names = set(
                line.strip() for line in str(raw_names).split("\n") if line.strip()
            )

        if not keep_names:
            raise ValueError(
                "class_names가 비어있습니다. 유지 기준 class 이름을 하나 이상 입력하세요."
            )

        filtered_meta = copy.deepcopy(input_meta)

        # 매칭되지 않는 이름이 있으면 경고
        existing_names = set(filtered_meta.categories)
        matched_names = keep_names & existing_names
        unmatched_names = keep_names - existing_names
        if unmatched_names:
            logger.warning(
                "categories에 존재하지 않는 class 이름: %s (무시됨)",
                ", ".join(sorted(unmatched_names)),
            )

        # 이미지 필터링 — 지정 class의 annotation이 1개라도 있는 이미지만 유지
        original_image_count = len(filtered_meta.image_records)
        filtered_meta.image_records = [
            image_record
            for image_record in filtered_meta.image_records
            if any(
                ann.category_name in keep_names
                for ann in image_record.annotations
            )
        ]
        removed_image_count = original_image_count - len(filtered_meta.image_records)

        logger.info(
            "filter_keep_images_containing_class_name 완료: 유지 기준 class %d개 (%s), "
            "제거된 이미지 %d장, 남은 이미지 %d장",
            len(matched_names),
            ", ".join(sorted(matched_names)),
            removed_image_count,
            len(filtered_meta.image_records),
        )

        return filtered_meta
