"""detection manipulator 14종 → det_ prefix 일괄 변경

Revision ID: 014_det_prefix_rename
Revises: 013_cls_prefix_rename
Create Date: 2026-04-15

배경:
    classification 도메인이 cls_ prefix 로 통일된 것에 대응하여 detection 도메인도
    det_ prefix 로 통일한다. pipeline.png 시각화 라벨에서 도메인이 한눈에 구분되고,
    IDE 파일 트리에서 같은 도메인 노드끼리 자연 정렬된다. det_ 이후 부분은 절대 축약하지 않는다.

조치:
  1) manipulators 테이블의 detection 14종 name 일괄 rename
  2) 이미 실행된 pipeline_executions.config(jsonb) 내부의 task.operator 문자열도
     동일 매핑으로 갱신 — 기존 lineage 표시/재실행 호환을 위해 필요.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "014_det_prefix_rename"
down_revision: Union[str, None] = "013_cls_prefix_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# old → new 매핑. 002 + 011 에서 시드된 detection 14종 전부 대상.
_RENAMES: dict[str, str] = {
    "filter_keep_images_containing_class_name": "det_filter_keep_images_containing_class_name",
    "filter_remain_selected_class_names_only_in_annotation": "det_filter_remain_selected_class_names_only_in_annotation",
    "filter_remove_images_containing_class_name": "det_filter_remove_images_containing_class_name",
    "format_convert_to_coco": "det_format_convert_to_coco",
    "format_convert_to_yolo": "det_format_convert_to_yolo",
    "format_convert_visdrone_to_coco": "det_format_convert_visdrone_to_coco",
    "format_convert_visdrone_to_yolo": "det_format_convert_visdrone_to_yolo",
    "mask_region_by_class": "det_mask_region_by_class",
    "merge_datasets": "det_merge_datasets",
    "remap_class_name": "det_remap_class_name",
    "rotate_image": "det_rotate_image",
    "sample_n_images": "det_sample_n_images",
    "change_compression": "det_change_compression",
    "shuffle_image_ids": "det_shuffle_image_ids",
}


def upgrade() -> None:
    # (1) manipulators.name rename
    for old_name, new_name in _RENAMES.items():
        op.execute(
            f"UPDATE manipulators SET name = '{new_name}' WHERE name = '{old_name}';"
        )

    # (2) pipeline_executions.config 내부 operator 문자열 동기화.
    #     config 는 jsonb 이므로 text 캐스팅 후 정확한 quoted form 만 치환한다.
    #     ("operator": "old") 패턴이 아니라 단순 quoted-name 치환이지만, classification 의
    #     cls_merge_datasets 는 이미 prefix 를 가지고 있어 충돌 없음.
    for old_name, new_name in _RENAMES.items():
        op.execute(
            "UPDATE pipeline_executions "
            f"SET config = REPLACE(config::text, '\"{old_name}\"', '\"{new_name}\"')::jsonb "
            f"WHERE config::text LIKE '%\"{old_name}\"%';"
        )


def downgrade() -> None:
    # 역순으로 되돌림. (manipulators 먼저, 그 다음 pipeline_executions)
    for old_name, new_name in _RENAMES.items():
        op.execute(
            f"UPDATE manipulators SET name = '{old_name}' WHERE name = '{new_name}';"
        )
    for old_name, new_name in _RENAMES.items():
        op.execute(
            "UPDATE pipeline_executions "
            f"SET config = REPLACE(config::text, '\"{new_name}\"', '\"{old_name}\"')::jsonb "
            f"WHERE config::text LIKE '%\"{new_name}\"%';"
        )
