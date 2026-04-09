"""
remap_class_name — class명 변경 (REMAP).

통일포맷: categories(list[str])와 annotation.category_name을 직접 변경한다.

params:
    mapping: dict[str, str] — 원래 이름 → 새 이름 매핑 (필수)
        예: {"van": "car", "pedestrian": "person"}

처리 흐름:
    1. mapping 파싱 및 검증 (빈 매핑이면 ValueError)
    2. categories의 name을 매핑에 따라 변경 + 중복 자연 병합
    3. 모든 annotation의 category_name도 함께 변경
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta

logger = logging.getLogger(__name__)


class RemapClassName(UnitManipulator):
    """
    categories의 class name을 매핑 테이블에 따라 변경하는 REMAP manipulator.

    통일포맷에서 annotation.category_name이 직접 참조이므로,
    categories와 annotation 양쪽의 name을 모두 변경한다.

    동일한 new_name으로 매핑되는 class들은 자연 병합된다.
    (예: pedestrian→person, walker→person → categories에 person 하나만 남음)

    DB seed name: "remap_class_name"
    """

    REQUIRED_PARAMS = ["mapping"]

    @property
    def name(self) -> str:
        return "remap_class_name"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        categories와 annotation의 category_name을 매핑에 따라 변경한다.

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - mapping: dict[str, str] — 원래 이름 → 새 이름
            context: 실행 컨텍스트 (선택)

        Returns:
            class name이 변경된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때
            ValueError: mapping이 비어있을 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "remap_class_name는 단건 DatasetMeta만 입력 가능합니다."
            )

        mapping = params.get("mapping", {})
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                "mapping이 비어있습니다. 변경할 class 이름 매핑을 하나 이상 입력하세요."
            )

        remapped_meta = copy.deepcopy(input_meta)

        # 매핑에 존재하지만 categories에 없는 이름 경고
        existing_names = set(input_meta.categories)
        unmatched_keys = set(mapping.keys()) - existing_names
        if unmatched_keys:
            logger.warning(
                "remap_class_name: 매핑에 지정되었으나 categories에 존재하지 않는 class 이름: %s (무시됨)",
                ", ".join(sorted(unmatched_keys)),
            )

        # categories 변경 + 중복 자연 병합 (등장 순서 보존, deduplicate)
        renamed_count = 0
        new_categories: list[str] = []
        seen_names: set[str] = set()
        for original_name in remapped_meta.categories:
            new_name = mapping.get(original_name, original_name)
            if new_name != original_name:
                renamed_count += 1
            if new_name not in seen_names:
                new_categories.append(new_name)
                seen_names.add(new_name)
        remapped_meta.categories = new_categories

        # annotation의 category_name도 함께 변경
        annotation_renamed_count = 0
        for image_record in remapped_meta.image_records:
            for annotation in image_record.annotations:
                if annotation.category_name in mapping:
                    annotation.category_name = mapping[annotation.category_name]
                    annotation_renamed_count += 1

        logger.info(
            "remap_class_name 완료: categories %d개 변경 → %d개 (병합 후), "
            "annotation %d건 변경",
            renamed_count, len(remapped_meta.categories), annotation_renamed_count,
        )

        return remapped_meta
