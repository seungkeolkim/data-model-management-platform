"""classification manipulator 8종 description 간결화

Revision ID: 015_cls_desc_rewrite
Revises: 014_det_prefix_rename
Create Date: 2026-04-16

배경:
    팔레트 노출 라벨이 길어 한눈에 들어오지 않아, 주요 classification manipulator 8종의
    description 을 짧은 행동 이름 위주로 다시 쓴다. frontend 는 description 을
    그대로 팔레트 라벨로 사용(`extractShortLabel` 규칙이 있지만 괄호 포함
    "버튼 (도움말)" 패턴이 아닌 경우 전체 텍스트가 라벨이 된다)하므로 SSOT 가
    DB description 이다. cls_filter_by_class / cls_merge_datasets 는 사용자 지시로
    이번 변경에서 제외 (향후 노드 자체가 없어질 수 있거나 아직 결정 대기).

조치:
    - UPDATE manipulators.description WHERE name IN (아래 8종).
    - downgrade: 과거 description 을 원상 복구.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "015_cls_desc_rewrite"
down_revision: Union[str, None] = "014_det_prefix_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 새 description. 팔레트 라벨에 그대로 노출되므로 짧게.
_NEW_DESCRIPTIONS: dict[str, str] = {
    "cls_select_heads": "선택된 Head 외 제거",
    "cls_rename_head": "Head 이름 변경",
    "cls_reorder_heads": "Head 순서 변경",
    "cls_reorder_classes": "특정 Head의 Class 순서 변경 (Output Class Index 변경)",
    "cls_rename_class": "Head 내 Class 이름 변경",
    "cls_merge_classes": "Head 내 Class 병합",
    "cls_remove_images_without_label": "Label 없는 이미지 제거",
    "cls_sample_n_images": "N장 랜덤 샘플 추출",
}

# 원복용 — 010/012 시드 당시의 문자열 그대로.
_OLD_DESCRIPTIONS: dict[str, str] = {
    "cls_select_heads": (
        "Head 선택 — 지정한 head 만 유지하고 나머지는 head_schema/labels 에서 제거한다."
    ),
    "cls_rename_head": (
        "Head 이름 변경 — head_schema[*].name 과 labels 키를 함께 rename. "
        "주로 merge 전 충돌 회피 용도."
    ),
    "cls_reorder_heads": (
        "Head 순서 변경 — head_schema 배열을 지정한 순서로 재정렬. "
        "merge 전 순서 통일 용도."
    ),
    "cls_reorder_classes": (
        "특정 head 의 class 순서 변경 — classes 배열을 재정렬. "
        "classes 순서는 학습 output index SSOT 이므로 신중히 사용."
    ),
    "cls_rename_class": (
        "특정 head 내 class 이름 변경 — classes 배열과 labels 값도 함께 rename."
    ),
    "cls_merge_classes": (
        "같은 head 내 여러 class 를 하나로 병합. labels 에서 해당 class 들을 "
        "target 으로 치환 후 dedup."
    ),
    "cls_remove_images_without_label": (
        "지정한 head(비우면 전체) 에 label 이 없는 이미지를 제거. "
        "multi_label head 의 라벨 누락 정리 용도."
    ),
    "cls_sample_n_images": (
        "Classification 데이터셋에서 이미지 N장을 랜덤 샘플링. labels 는 그대로 유지."
    ),
}


def _apply(mapping: dict[str, str]) -> None:
    """주어진 매핑으로 manipulators.description 을 일괄 UPDATE 한다."""
    connection = op.get_bind()
    for manipulator_name, new_description in mapping.items():
        connection.exec_driver_sql(
            "UPDATE manipulators SET description = %s WHERE name = %s;",
            (new_description, manipulator_name),
        )


def upgrade() -> None:
    _apply(_NEW_DESCRIPTIONS)


def downgrade() -> None:
    _apply(_OLD_DESCRIPTIONS)
