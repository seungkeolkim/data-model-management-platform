"""narrow manipulator compatible_task_types — CLASSIFICATION / SEGMENTATION 제거

Revision ID: 011_narrow_manip_task_types
Revises: 010_seed_cls_manips
Create Date: 2026-04-15

배경:
  Detection 용으로 구현된 manipulator 들이 `compatible_task_types` 에
  CLASSIFICATION / SEGMENTATION 을 함께 선언하고 있었다. 그러나:
    - CLS_MANIFEST 의 labels(dict) 자료구조와 COCO/YOLO 의 annotations(list[Annotation])
      자료구조가 이질적이라 한 manipulator 로 양쪽을 처리하면 내부가
      task_kind 분기로 반이 덮인다. SRP / 응집도 관점에서 바람직하지 않다.
    - SEGMENTATION 도 추후 독립 자료구조(mask/polygon) 로 분화될 가능성이 높아
      지금 단계에서 공용으로 선언하면 호환 매트릭스가 사실과 어긋난다.

조치:
  detection 전용 manipulator 6종의 `compatible_task_types` 를 ["DETECTION"] 으로 좁힌다.
  네이밍·파일·구현은 건드리지 않는다(사용자에게 보이는 팔레트 라벨/DAG 노드명 유지).
  Classification 전용 기능은 `*_classification` 접미사의 신규 manipulator 로
  분리하여 추가한다(별도 작업).

대상 manipulator 와 이전/이후 값:
  - filter_keep_images_containing_class_name      : [CLS,DET,SEG] → [DET]
  - filter_remove_images_containing_class_name    : [CLS,DET,SEG] → [DET]
  - remap_class_name                              : [CLS,DET,SEG] → [DET]
  - filter_remain_selected_class_names_only_in_annotation : [DET,SEG] → [DET]
  - mask_region_by_class                          : [DET,SEG]     → [DET]
  - rotate_image                                  : [DET,SEG]     → [DET]
"""
from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op

revision: str = "011_narrow_manip_task_types"
down_revision: Union[str, None] = "010_seed_cls_manips"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# upgrade 이후 모두 동일한 값을 가진다.
_DETECTION_ONLY = json.dumps(["DETECTION"])

# name → upgrade 이전 값(downgrade 복원용).
_PREVIOUS_TASK_TYPES: dict[str, str] = {
    "filter_keep_images_containing_class_name": json.dumps(
        ["CLASSIFICATION", "DETECTION", "SEGMENTATION"]
    ),
    "filter_remove_images_containing_class_name": json.dumps(
        ["CLASSIFICATION", "DETECTION", "SEGMENTATION"]
    ),
    "remap_class_name": json.dumps(
        ["CLASSIFICATION", "DETECTION", "SEGMENTATION"]
    ),
    "filter_remain_selected_class_names_only_in_annotation": json.dumps(
        ["DETECTION", "SEGMENTATION"]
    ),
    "mask_region_by_class": json.dumps(["DETECTION", "SEGMENTATION"]),
    "rotate_image": json.dumps(["DETECTION", "SEGMENTATION"]),
}


def upgrade() -> None:
    """대상 6종의 compatible_task_types 를 ["DETECTION"] 으로 좁힌다."""
    for name in _PREVIOUS_TASK_TYPES:
        op.execute(
            "UPDATE manipulators "
            f"SET compatible_task_types = '{_DETECTION_ONLY}'::jsonb "
            f"WHERE name = '{name}';"
        )


def downgrade() -> None:
    """각 manipulator 의 이전 값으로 복원."""
    for name, previous_value in _PREVIOUS_TASK_TYPES.items():
        op.execute(
            "UPDATE manipulators "
            f"SET compatible_task_types = '{previous_value}'::jsonb "
            f"WHERE name = '{name}';"
        )
