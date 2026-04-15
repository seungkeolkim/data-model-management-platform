"""
select_classification_heads — Classification 전용 Head 선택 manipulator (STUB).

역할:
    head_schema 에서 사용자가 지정한 head 만 유지하고 나머지는 제거한다.
    image_records[*].labels 에서도 선택되지 않은 head 키를 제거한다.

params:
    keep_head_names: list[str] — 유지할 head 이름 목록 (필수).

이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

현재는 구조체 설계 검증용 STUB. 실제 로직은 다음 세션에서 구현.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class SelectClassificationHeads(UnitManipulator):
    """DB seed name: "select_classification_heads"."""

    @property
    def name(self) -> str:
        return "select_classification_heads"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "select_classification_heads 는 아직 구현되지 않았습니다 (stub)."
        )
