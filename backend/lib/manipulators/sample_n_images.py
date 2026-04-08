"""
sample_n_images — N장 랜덤 샘플 추출 (SAMPLE).

image_records에서 N장을 랜덤으로 추출하여 나머지를 제거한다.
seed를 지정하면 동일한 결과를 재현할 수 있다.

params:
    n: int — 추출할 이미지 수 (필수, 1 이상)
    seed: int | None — 랜덤 시드 (선택, 기본값 42)

처리 흐름:
    1. n 파싱 및 검증 (총 이미지 수보다 크면 전체 유지)
    2. seed로 Random 인스턴스 생성
    3. image_records에서 n장 샘플링
    4. categories는 변경하지 않음
"""
from __future__ import annotations

import copy
import logging
import random
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta

logger = logging.getLogger(__name__)


class SampleNImages(UnitManipulator):
    """
    N장의 이미지를 랜덤으로 추출하는 SAMPLE manipulator.

    총 이미지 수가 N 이하이면 전체를 그대로 유지한다.
    seed를 동일하게 설정하면 동일한 샘플 결과를 재현할 수 있다.

    DB seed name: "sample_n_images"
    """

    @property
    def name(self) -> str:
        return "sample_n_images"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        image_records에서 N장을 랜덤 샘플링한다.

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - n: int — 추출할 이미지 수
                - seed: int | None — 랜덤 시드 (기본 42)
            context: 실행 컨텍스트 (선택)

        Returns:
            샘플링된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta가 list일 때
            ValueError: n이 1 미만일 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "sample_n_images는 단건 DatasetMeta만 입력 가능합니다."
            )

        sample_count = int(params.get("n", 0))
        if sample_count < 1:
            raise ValueError(
                "n이 1 미만입니다. 추출할 이미지 수를 1 이상으로 입력하세요."
            )

        seed_value = params.get("seed", 42)
        if seed_value is not None:
            seed_value = int(seed_value)

        filtered_meta = copy.deepcopy(input_meta)
        original_image_count = len(filtered_meta.image_records)

        # 총 이미지 수가 N 이하이면 전체 유지
        if original_image_count <= sample_count:
            logger.info(
                "sample_n_images: 총 이미지 수(%d)가 요청 수(%d) 이하 — 전체 유지",
                original_image_count, sample_count,
            )
            return filtered_meta

        # 랜덤 샘플링
        rng = random.Random(seed_value)
        filtered_meta.image_records = rng.sample(
            filtered_meta.image_records, sample_count,
        )

        logger.info(
            "sample_n_images 완료: %d장 → %d장 (seed=%s)",
            original_image_count, sample_count, seed_value,
        )

        return filtered_meta
