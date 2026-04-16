"""classification manipulator description/category/params_schema 재구성

Revision ID: 015_cls_desc_rewrite
Revises: 014_det_prefix_rename
Create Date: 2026-04-16

배경:
    1) 팔레트 노출 라벨이 길어 한눈에 들어오지 않음 → description 을 짧은
       행동 이름으로 다시 쓴다. frontend 는 description 을 그대로 팔레트
       라벨로 사용하므로 SSOT 가 DB description 이다.
    2) 기존 category(SCHEMA/REMAP) 로는 UX 가 분화되지 않아 "기타" 아래
       뒤섞여 보인다. classification head/class 조작을 두 카테고리로 분리:
         - CLS_HEAD_CTRL : "분류 항목 제어"      (head 단위 조작)
         - CLS_CLASS_CTRL: "분류 Class 상세 제어" (head 내 class 조작)
       카테고리 스타일·라벨은 frontend/src/pipeline-sdk/styles.ts 에서
       정의한다.
    3) cls_rename_head 의 params_schema 를 det_remap_class_name 과 같은
       key_value UX (+추가 버튼) 로 쓰려면 key_label / value_label 가 필요해
       함께 덮어쓴다. 라벨 문구는 classification + cls_manifest 맥락을
       반영해 "Head 이름" 으로 한다.

    cls_filter_by_class / cls_merge_datasets / cls_sample_n_images /
    cls_remove_images_without_label 는 분류 제어 그룹과 성격이 달라
    기존 category 유지.

조치:
    - UPDATE manipulators.description / category WHERE name IN (...).
    - UPDATE manipulators.params_schema WHERE name = 'cls_rename_head'.
    - downgrade: 010/012 시드 당시 문자열/카테고리/params_schema 로 원복.
"""
from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op

revision: str = "015_cls_desc_rewrite"
down_revision: Union[str, None] = "014_det_prefix_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 새 (description, category) 매핑. 팔레트 라벨에 그대로 노출되므로 짧게.
# 팔레트 내부 정렬은 frontend styles.ts 의 CATEGORY_ITEM_ORDER 에서 별도 관리.
_NEW: dict[str, tuple[str, str]] = {
    # --- 분류 항목 제어 (head 단위) ---
    "cls_select_heads":  ("선택된 Head 외 제거", "CLS_HEAD_CTRL"),
    "cls_rename_head":   ("Head 이름 변경",       "CLS_HEAD_CTRL"),
    "cls_reorder_heads": ("Head 순서 변경",       "CLS_HEAD_CTRL"),
    # --- 분류 Class 상세 제어 (head 내 class 조작) ---
    "cls_rename_class":    ("Head 내 Class 이름 변경", "CLS_CLASS_CTRL"),
    "cls_reorder_classes": ("Head 내 Class 순서 변경", "CLS_CLASS_CTRL"),
    "cls_merge_classes":   ("Head 내 Class 병합",      "CLS_CLASS_CTRL"),
    # --- 그 외 (category 유지, description 만 간결화) ---
    "cls_remove_images_without_label": (
        "Label 없는 이미지 제거",
        "IMAGE_FILTER",
    ),
    "cls_sample_n_images": ("N장 랜덤 샘플 추출", "SAMPLE"),
}

# 원복용 — 010/012 시드 당시의 (description, category) 그대로.
_OLD: dict[str, tuple[str, str]] = {
    "cls_select_heads": (
        "Head 선택 — 지정한 head 만 유지하고 나머지는 head_schema/labels 에서 제거한다.",
        "SCHEMA",
    ),
    "cls_rename_head": (
        "Head 이름 변경 — head_schema[*].name 과 labels 키를 함께 rename. "
        "주로 merge 전 충돌 회피 용도.",
        "SCHEMA",
    ),
    "cls_reorder_heads": (
        "Head 순서 변경 — head_schema 배열을 지정한 순서로 재정렬. "
        "merge 전 순서 통일 용도.",
        "SCHEMA",
    ),
    "cls_rename_class": (
        "특정 head 내 class 이름 변경 — classes 배열과 labels 값도 함께 rename.",
        "REMAP",
    ),
    "cls_reorder_classes": (
        "특정 head 의 class 순서 변경 — classes 배열을 재정렬. "
        "classes 순서는 학습 output index SSOT 이므로 신중히 사용.",
        "SCHEMA",
    ),
    "cls_merge_classes": (
        "같은 head 내 여러 class 를 하나로 병합. labels 에서 해당 class 들을 "
        "target 으로 치환 후 dedup.",
        "REMAP",
    ),
    "cls_remove_images_without_label": (
        "지정한 head(비우면 전체) 에 label 이 없는 이미지를 제거. "
        "multi_label head 의 라벨 누락 정리 용도.",
        "IMAGE_FILTER",
    ),
    "cls_sample_n_images": (
        "Classification 데이터셋에서 이미지 N장을 랜덤 샘플링. labels 는 그대로 유지.",
        "SAMPLE",
    ),
}


def _apply(mapping: dict[str, tuple[str, str]]) -> None:
    """주어진 매핑으로 manipulators.description/category 를 일괄 UPDATE 한다."""
    connection = op.get_bind()
    for manipulator_name, (new_description, new_category) in mapping.items():
        connection.exec_driver_sql(
            "UPDATE manipulators SET description = %s, category = %s "
            "WHERE name = %s;",
            (new_description, new_category, manipulator_name),
        )


# cls_rename_head params_schema — classification head 이름 매핑용 key_value UX.
# key_label/value_label 를 명시하여 DynamicParamForm 이 입력 placeholder 로 표시.
_CLS_RENAME_HEAD_PARAMS_NEW: dict = {
    "mapping": {
        "type": "key_value",
        "label": "Head 이름 매핑 (원래 → 새 이름)",
        "key_label": "원래 Head 이름",
        "value_label": "새 Head 이름",
        "required": True,
    },
}

# 010 시드 당시의 params_schema — downgrade 시 원복용.
_CLS_RENAME_HEAD_PARAMS_OLD: dict = {
    "mapping": {
        "type": "key_value",
        "label": "원래 head 이름 → 새 head 이름",
        "required": True,
    },
}


def _update_params_schema(manipulator_name: str, params_schema: dict) -> None:
    """단일 manipulator 의 params_schema(JSONB) 를 일괄 교체한다."""
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE manipulators SET params_schema = %s::jsonb WHERE name = %s;",
        (json.dumps(params_schema), manipulator_name),
    )


def upgrade() -> None:
    _apply(_NEW)
    _update_params_schema("cls_rename_head", _CLS_RENAME_HEAD_PARAMS_NEW)


def downgrade() -> None:
    _apply(_OLD)
    _update_params_schema("cls_rename_head", _CLS_RENAME_HEAD_PARAMS_OLD)
