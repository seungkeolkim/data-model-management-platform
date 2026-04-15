"""
cls_reorder_heads — Head 순서 변경 manipulator (STUB).

역할:
    head_schema 배열의 순서를 사용자가 지정한 순서대로 재정렬한다.
    merge 이전에 두 브랜치의 head 순서를 맞추기 위해 사용한다.

params:
    ordered_head_names: list[str] — 새 순서. 모든 기존 head 를 빠짐없이 포함해야 한다.

head_schema 만 변경되며 image_records[*].labels 는 dict 이라 순서 무관 → 수정 불요.
이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class ClsReorderHeads(UnitManipulator):
    """DB seed name: "cls_reorder_heads"."""

    @property
    def name(self) -> str:
        return "cls_reorder_heads"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_reorder_heads 는 아직 구현되지 않았습니다 (stub)."
        )
