"""
filter_final_classes — 지정 class만 남기고 나머지 annotation 제거.

이미지 자체는 삭제하지 않는다.
annotation이 0개가 된 이미지도 image_records에 유지한다 (빈 이미지로 남김).

params:
    keep_class_names: str — 줄바꿈 구분된 class 이름 목록.
        GUI textarea에서 입력된 문자열을 그대로 받는다.
        예: "person\ncar"

처리 흐름:
    1. keep_class_names 파싱 → 유지할 class 이름 set 구성
    2. categories에서 이름이 매칭되는 category_id set 구성
    3. 모든 image_record의 annotations에서 해당 category_id만 유지
    4. categories도 유지 대상만 남김
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta

logger = logging.getLogger(__name__)


class FilterFinalClasses(UnitManipulator):
    """
    지정한 class 이름에 해당하는 annotation만 유지하고 나머지를 제거한다.

    이미지 파일은 건드리지 않는다 (annotation 레벨만 처리).
    annotation이 전부 제거된 이미지도 image_records에 유지한다.

    DB seed name: "filter_final_classes"
    """

    @property
    def name(self) -> str:
        return "filter_final_classes"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        지정 class만 남기고 나머지 annotation을 제거한다.

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - keep_class_names: str — 줄바꿈 구분된 class 이름 목록
            context: 실행 컨텍스트 (선택)

        Returns:
            annotation이 필터링된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때
            ValueError: keep_class_names가 비어있을 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "filter_final_classes는 단건 DatasetMeta만 입력 가능합니다."
            )

        raw_names = params.get("keep_class_names", "")
        if isinstance(raw_names, list):
            # GUI에서 이미 리스트로 파싱되어 올 수도 있음
            keep_names = set(n.strip() for n in raw_names if n.strip())
        else:
            keep_names = set(
                line.strip() for line in str(raw_names).split("\n") if line.strip()
            )

        if not keep_names:
            raise ValueError(
                "keep_class_names가 비어있습니다. 남길 class 이름을 하나 이상 입력하세요."
            )

        filtered_meta = copy.deepcopy(input_meta)

        # 유지할 category_id 집합 구성
        keep_category_ids = set()
        for category in filtered_meta.categories:
            if category["name"] in keep_names:
                keep_category_ids.add(category["id"])

        # 매칭되지 않는 이름이 있으면 경고
        matched_names = {
            cat["name"] for cat in filtered_meta.categories
            if cat["name"] in keep_names
        }
        unmatched_names = keep_names - matched_names
        if unmatched_names:
            logger.warning(
                "categories에 존재하지 않는 class 이름: %s (무시됨)",
                ", ".join(sorted(unmatched_names)),
            )

        # annotation 필터링 — 이미지는 유지, annotation만 제거
        total_removed = 0
        for image_record in filtered_meta.image_records:
            original_count = len(image_record.annotations)
            image_record.annotations = [
                ann for ann in image_record.annotations
                if ann.category_id in keep_category_ids
            ]
            total_removed += original_count - len(image_record.annotations)

        # categories도 유지 대상만 남김
        filtered_meta.categories = [
            cat for cat in filtered_meta.categories
            if cat["id"] in keep_category_ids
        ]

        logger.info(
            "filter_final_classes 완료: 유지 class %d개, 제거된 annotation %d개, "
            "이미지 수 변동 없음 (%d장)",
            len(keep_category_ids), total_removed, len(filtered_meta.image_records),
        )

        return filtered_meta
