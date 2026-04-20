"""
cls_crop_image — 이미지 Crop manipulator (STUB).

역할:
    이미지 상하좌우 영역을 비율(%) 로 잘라낸다. 한 노드에서 상하 / 좌우 / 상하좌우 모두
    옵션으로 지정 가능하도록 설계한다. head_schema / labels 자체는 변경하지 않으며
    Phase B 실체화 시 이미지 바이너리 변형 + `record.file_name` 갱신이 필요하다.

params (잠정 — 실구현 시 범위·default 재검토):
    top_pct:    number (0~50) — 상단에서 잘라낼 비율.
    bottom_pct: number (0~50) — 하단에서 잘라낼 비율.
    left_pct:   number (0~50) — 좌측에서 잘라낼 비율.
    right_pct:  number (0~50) — 우측에서 잘라낼 비율.

v7.5 filename-identity 체계에서는 SHA 재계산이 불필요하다 (§2-13). 결과 파일명만
결정론적으로 정해 dst 에 저장하면 된다.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class CropImageClassification(UnitManipulator):
    """DB seed name: "cls_crop_image"."""

    @property
    def name(self) -> str:
        return "cls_crop_image"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_crop_image 는 아직 구현되지 않았습니다 (stub)."
        )
