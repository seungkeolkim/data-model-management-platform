"""
sample_n_images_classification — Classification 데이터셋 이미지 N장 샘플링 (STUB).

역할:
    image_records 에서 N 장을 샘플링하여 출력 DatasetMeta 에 남긴다.
    Detection 용 `sample_n_images` 와 자료구조가 달라(classification 은 labels dict 기반) 별도 분리.

주요 고려사항 (실제 구현 시):
    1. 샘플링 전략
       - random (seed 고정 가능), head/class 층화(stratified), per-head 최소 개수 보장 등.
       - 기본은 random(seed=0) 로 시작.
    2. Class 존재성
       - 샘플 결과에서 특정 class 가 0장으로 남는 경우 head_schema 는 유지할지(빈 class 허용)
         결정 필요. 기본은 유지(학습 시 빈 class 는 weight 0 로 처리).
    3. 이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

params:
    n: int — 샘플 장수.
    seed: int | None — 재현성을 위한 랜덤 시드.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class SampleNImagesClassification(UnitManipulator):
    """DB seed name: "sample_n_images_classification"."""

    @property
    def name(self) -> str:
        return "sample_n_images_classification"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "sample_n_images_classification 는 아직 구현되지 않았습니다 (stub)."
        )
