"""
cls_rename_class — 특정 Head 내 Class 이름 변경 manipulator (STUB).

역할:
    지정 head 의 classes 배열 내 이름을 매핑에 따라 변경한다.
    해당 head 의 image_records[*].labels[head_name] 내 class 이름도 함께 변경한다.

params:
    head_name: str — 대상 head 이름.
    mapping:   dict[str, str] — 원래 class 이름 → 새 class 이름.

주로 merge 이전에 class 이름 충돌을 회피하기 위해 사용한다.
이미지 바이너리 불변 → sha/file_name 유지 → lazy copy.

현재는 STUB. 실제 로직은 다음 세션.
"""
from __future__ import annotations

from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta


class ClsRenameClass(UnitManipulator):
    """DB seed name: "cls_rename_class"."""

    @property
    def name(self) -> str:
        return "cls_rename_class"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        raise NotImplementedError(
            "cls_rename_class 는 아직 구현되지 않았습니다 (stub)."
        )
