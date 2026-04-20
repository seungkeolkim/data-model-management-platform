"""Classification manipulator 파라미터 label 축약 (DAG 박스·속성 패널 가독성)

Revision ID: 028_shorten_cls_param_labels
Revises: 027_cls_filter_by_class_unified
Create Date: 2026-04-20

배경:
    다음 3개 manipulator 의 일부 파라미터 label 이 너무 길어서, DAG 박스 안에서는
    노드 가로폭을 비정상적으로 늘리고, 속성 패널에서는 폭이 좁은 경우 텍스트가
    잘려 보이는 문제가 있었다.

    label 을 '한눈에 필드 용도만 식별' 하는 짧은 문구로 줄이고, 상세 의미는
    설계서 / manipulator docstring 쪽에 남긴다 (DynamicParamForm 에 tooltip/help
    필드가 아직 없으므로 label 자체를 축약).

대상 필드 (총 6개):
  1. cls_add_head.class_candidates
       "Class 후보 (줄바꿈 구분, 2개 이상, 순서 = 학습 output index)"
     → "Class 후보 (줄바꿈 구분, 2개 이상)"
  2. cls_add_head.multi_label
       "Multi-label 여부 (체크 시 한 이미지가 여러 class 를 동시에 가질 수 있음)"
     → "Multi-Label 여부"
  3. cls_set_head_labels_for_all_images.set_unknown
       "Unknown 으로 초기화 (체크 시 classes 무시하고 모든 라벨을 null 로)"
     → "Unknown 으로 초기화"
  4. cls_set_head_labels_for_all_images.classes
       "설정할 Class 이름 (줄바꿈 구분, set_unknown 미체크 시 사용). single-label 은 정확히 1개, multi-label 은 0개 이상(빈 값 허용)."
     → "설정할 Class 이름 (줄바꿈 구분)"
  5. cls_filter_by_class.include_unknown
       "Unknown(null) 라벨도 매칭 대상에 포함 (체크 시 labels[head] 가 null 인 이미지도 match)"
     → "Unknown 라벨 포함"
  6. cls_filter_by_class.classes
       "대상 Class 이름 (줄바꿈 구분, any match). 비워두면 include_unknown 조합으로만 판정."
     → "대상 Class 이름 (줄바꿈 구분)"
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "028_shorten_cls_param_labels"
down_revision: str | None = "027_cls_filter_by_class_unified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (manipulator name, param key, new label, old label) — downgrade 시 old 로 복원.
_UPDATES: list[tuple[str, str, str, str]] = [
    (
        "cls_add_head",
        "class_candidates",
        "Class 후보 (줄바꿈 구분, 2개 이상)",
        "Class 후보 (줄바꿈 구분, 2개 이상, 순서 = 학습 output index)",
    ),
    (
        "cls_add_head",
        "multi_label",
        "Multi-Label 여부",
        "Multi-label 여부 (체크 시 한 이미지가 여러 class 를 동시에 가질 수 있음)",
    ),
    (
        "cls_set_head_labels_for_all_images",
        "set_unknown",
        "Unknown 으로 초기화",
        "Unknown 으로 초기화 (체크 시 classes 무시하고 모든 라벨을 null 로)",
    ),
    (
        "cls_set_head_labels_for_all_images",
        "classes",
        "설정할 Class 이름 (줄바꿈 구분)",
        "설정할 Class 이름 (줄바꿈 구분, set_unknown 미체크 시 사용). single-label 은 정확히 1개, multi-label 은 0개 이상(빈 값 허용).",
    ),
    (
        "cls_filter_by_class",
        "include_unknown",
        "Unknown 라벨 포함",
        "Unknown(null) 라벨도 매칭 대상에 포함 (체크 시 labels[head] 가 null 인 이미지도 match)",
    ),
    (
        "cls_filter_by_class",
        "classes",
        "대상 Class 이름 (줄바꿈 구분)",
        "대상 Class 이름 (줄바꿈 구분, any match). 비워두면 include_unknown 조합으로만 판정.",
    ),
]


def _apply(new_to_old: bool) -> None:
    """한 방향으로 label 일괄 치환. new_to_old=False 면 upgrade(short), True 면 downgrade(복원)."""
    connection = op.get_bind()
    for manipulator_name, param_key, new_label, old_label in _UPDATES:
        target_label = old_label if new_to_old else new_label
        # jsonb_set(path, value) — 다른 필드는 건드리지 않음. value 는 JSON 스칼라 문자열이어야 하므로 json.dumps 로 감싼다.
        connection.exec_driver_sql(
            "UPDATE manipulators "
            "SET params_schema = jsonb_set(params_schema, %s, %s::jsonb, false) "
            "WHERE name = %s;",
            ("{" + param_key + ",label}", json.dumps(target_label), manipulator_name),
        )


def upgrade() -> None:
    _apply(new_to_old=False)


def downgrade() -> None:
    _apply(new_to_old=True)
