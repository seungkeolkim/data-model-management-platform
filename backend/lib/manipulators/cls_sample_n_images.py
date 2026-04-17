"""
cls_sample_n_images — Classification 데이터셋 이미지 N장 랜덤 샘플 추출.

image_records 에서 N장을 랜덤으로 추출하여 나머지를 제거한다.
seed 를 지정하면 동일한 결과를 재현할 수 있다.
head_schema 는 변경하지 않는다 (샘플 결과에서 특정 class 가 0장이 되어도 유지).

params:
    n:    int        — 추출할 이미지 수 (필수, 1 이상)
    seed: int | None — 랜덤 시드 (선택, 기본값 42)

이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.
"""
from __future__ import annotations

import copy
import logging
import random
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta

logger = logging.getLogger(__name__)


class SampleNImagesClassification(UnitManipulator):
    """
    N장의 이미지를 랜덤으로 추출하는 SAMPLE manipulator (Classification 전용).

    총 이미지 수가 N 이하이면 전체를 그대로 유지한다.
    seed 를 동일하게 설정하면 동일한 샘플 결과를 재현할 수 있다.

    DB seed name: "cls_sample_n_images"
    """

    REQUIRED_PARAMS = ["n"]

    @property
    def name(self) -> str:
        return "cls_sample_n_images"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        image_records 에서 N장을 랜덤 샘플링한다.

        head_schema 는 변경하지 않는다. 샘플 결과에서 특정 class 가 0장이 되어도
        head_schema.classes 에는 남아있다 (학습 시 빈 class 는 weight 0 처리).

        Args:
            input_meta: 입력 DatasetMeta (단건)
            params:
                - n: int — 추출할 이미지 수
                - seed: int | None — 랜덤 시드 (기본 42)
            context: 실행 컨텍스트 (선택)

        Returns:
            샘플링된 DatasetMeta (deep copy)

        Raises:
            TypeError: input_meta 가 list 일 때
            ValueError: n 이 1 미만이거나, head_schema 가 None 일 때
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_sample_n_images 는 단일 입력만 지원합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_sample_n_images 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        sample_count = int(params.get("n", 0))
        if sample_count < 1:
            raise ValueError(
                "n 이 1 미만입니다. 추출할 이미지 수를 1 이상으로 입력하세요."
            )

        seed_value = params.get("seed", 42)
        if seed_value is not None:
            seed_value = int(seed_value)

        sampled_meta = copy.deepcopy(input_meta)
        original_image_count = len(sampled_meta.image_records)

        # 총 이미지 수가 N 이하이면 전체 유지.
        if original_image_count <= sample_count:
            logger.info(
                "cls_sample_n_images: 총 이미지 수(%d)가 요청 수(%d) 이하 — 전체 유지",
                original_image_count, sample_count,
            )
            return sampled_meta

        # 랜덤 샘플링.
        rng = random.Random(seed_value)
        sampled_meta.image_records = rng.sample(
            sampled_meta.image_records, sample_count,
        )

        logger.info(
            "cls_sample_n_images 완료: %d장 → %d장 (seed=%s)",
            original_image_count, sample_count, seed_value,
        )

        return sampled_meta
