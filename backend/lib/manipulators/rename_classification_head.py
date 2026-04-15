"""
rename_classification_head — Head 이름 변경 manipulator (STUB).

역할:
    head_schema[*].name 을 매핑에 따라 변경한다.
    image_records[*].labels 의 키도 동일한 매핑으로 변경한다.

params:
    mapping: dict[str, str] — 원래 이름 → 새 이름.

주로 merge 이전에 이름 충돌을 회피하기 위해 사용한다.
이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class RenameClassificationHead(UnitManipulator):
    """DB seed name: "rename_classification_head"."""

    @property
    def name(self) -> str:
        return "rename_classification_head"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "rename_classification_head 는 아직 구현되지 않았습니다 (stub)."
        )
