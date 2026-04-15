"""classification manipulator postfix(_classification) → prefix(cls_) 로 변경

Revision ID: 013_cls_prefix_rename
Revises: 012_rename_cls_manips_and_stubs
Create Date: 2026-04-15

배경:
    pipeline.png(graphviz) 시각화에서 노드 라벨이 길어 가독성이 떨어진다.
    축약어는 가급적 지양하나 시각화 가독성을 위해 본 도메인에 한해 "cls_" prefix
    규약을 도입한다. prefix 통일은 IDE 파일 트리에서 같은 도메인 노드끼리 자연 정렬되는
    부수 효과도 있다. cls_ 이후 부분은 절대 축약하지 않는다.

조치:
    UPDATE manipulators SET name = ... — 010 + 012 에서 만든 classification 10종 일괄 rename.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "013_cls_prefix_rename"
down_revision: Union[str, None] = "012_rename_cls_manips_and_stubs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# old → new 매핑. 010 + 012 에서 만든 10종 전부 대상.
_RENAMES: dict[str, str] = {
    "select_heads_classification": "cls_select_heads",
    "rename_head_classification": "cls_rename_head",
    "reorder_heads_classification": "cls_reorder_heads",
    "rename_class_classification": "cls_rename_class",
    "merge_classes_classification": "cls_merge_classes",
    "reorder_classes_classification": "cls_reorder_classes",
    "filter_by_class_classification": "cls_filter_by_class",
    "remove_images_without_label_classification": "cls_remove_images_without_label",
    "merge_datasets_classification": "cls_merge_datasets",
    "sample_n_images_classification": "cls_sample_n_images",
}


def upgrade() -> None:
    for old_name, new_name in _RENAMES.items():
        op.execute(
            f"UPDATE manipulators SET name = '{new_name}' WHERE name = '{old_name}';"
        )


def downgrade() -> None:
    for old_name, new_name in _RENAMES.items():
        op.execute(
            f"UPDATE manipulators SET name = '{old_name}' WHERE name = '{new_name}';"
        )
