"""
remap_class_name — class명 변경 (REMAP).

categories의 name을 매핑 테이블에 따라 변경한다.
category_id는 유지하고, name만 변경하므로 annotation은 건드리지 않는다.

params:
    mapping: dict[str, str] — 원래 이름 → 새 이름 매핑 (필수)
        예: {"van": "car", "pedestrian": "person"}

처리 흐름:
    1. mapping 파싱 및 검증 (빈 매핑이면 ValueError)
    2. 변경 후 categories에 중복 이름이 생기는지 사전 검사
    3. categories의 name을 매핑에 따라 변경
    4. image_records / annotations는 category_id 참조이므로 변경 불요
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

    category_id는 그대로 유지하고 name만 변경하므로,
    annotation의 category_id 참조는 자동으로 새 이름을 가리키게 된다.

    매핑에 포함되지 않은 class는 원래 이름을 유지한다.
    변경 후 중복 이름이 발생하면 RuntimeError를 발생시켜 파이프라인을 중단한다.

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
        categories의 name을 매핑 테이블에 따라 변경한다.

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
            RuntimeError: 변경 후 categories에 중복 이름이 발생할 때
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

        # 매핑에 포함되지 않은 class는 원래 이름 유지 → 변경 후 전체 이름 목록 구성
        result_names: list[str] = []
        renamed_count = 0
        for category in remapped_meta.categories:
            original_name = category["name"]
            if original_name in mapping:
                category["name"] = mapping[original_name]
                renamed_count += 1
            result_names.append(category["name"])

        # 매핑에 존재하지만 categories에 없는 이름 경고
        existing_names = {cat["name"] for cat in input_meta.categories}
        unmatched_keys = set(mapping.keys()) - existing_names
        if unmatched_keys:
            logger.warning(
                "remap_class_name: 매핑에 지정되었으나 categories에 존재하지 않는 class 이름: %s (무시됨)",
                ", ".join(sorted(unmatched_keys)),
            )

        # 중복 이름 검사 — 변경 후 같은 이름이 2개 이상 존재하면 비정상 종료
        seen_names: set[str] = set()
        duplicate_names: set[str] = set()
        for result_name in result_names:
            if result_name in seen_names:
                duplicate_names.add(result_name)
            seen_names.add(result_name)

        if duplicate_names:
            error_message = (
                f"remap_class_name: class name 변경 후 중복이 발생했습니다 — "
                f"중복 이름: {', '.join(sorted(duplicate_names))}. "
                f"매핑을 수정하거나, 기존 class 이름과 겹치지 않도록 변경하세요."
            )
            logger.error(error_message)
            raise RuntimeError(error_message)

        logger.info(
            "remap_class_name 완료: %d개 class 이름 변경, 전체 %d개 class 유지",
            renamed_count, len(remapped_meta.categories),
        )

        return remapped_meta
