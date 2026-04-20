"""cls_filter_by_class 실구현 + cls_remove_images_without_label 통합 제거

Revision ID: 027_cls_filter_by_class_unified
Revises: 026_cls_crop_image_params
Create Date: 2026-04-20

배경:
    "label 없는 이미지 제거" (`cls_remove_images_without_label`) 는 `cls_filter_by_class`
    의 exclude 모드 + `include_unknown=True` + `classes=[]` 조합으로 완전히 표현 가능.
    따라서 기능 중복을 제거하고 `cls_filter_by_class` 하나로 통합한다.

    통합 후 `cls_filter_by_class` params:
      - head_name:        text (required) — 대상 head.
      - mode:             select("include" | "exclude"), default "include".
                          include = match True 이미지만 남김 (1개라도 매칭되면 keep).
                          exclude = match True 이미지를 제거 (1개라도 매칭되면 drop).
      - classes:          textarea (줄바꿈 구분, 0개 이상).
                          class 하나라도 labels 와 겹치면 match (any policy 고정).
                          비워두면 unknown 만 판정 (include_unknown 조합).
      - include_unknown:  checkbox, default False.
                          True 면 labels[head] 가 null/None(=unknown) 인 이미지도 match.
                          §2-12 의 `null`=unknown 규약에 맞춤. `[]` (explicit empty) 는
                          unknown 이 아니라 "class 없음" 이 확정된 상태이므로 unknown 처리
                          대상이 아니며, classes 와 교집합 평가(any) 결과 False 로 흐른다.

    `cls_remove_images_without_label` 은 DB 와 파일시스템 양쪽에서 제거.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "027_cls_filter_by_class_unified"
down_revision: str | None = "026_cls_crop_image_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FILTER_NAME = "cls_filter_by_class"
_REMOVE_NAME = "cls_remove_images_without_label"

# 통합 후 params — 4-필드 XOR-gate 스타일.
_NEW_PARAMS: dict = {
    "head_name": {
        "type": "text",
        "label": "대상 Head 이름",
        "required": True,
    },
    "mode": {
        "type": "select",
        "label": "필터 모드",
        "options": ["include", "exclude"],
        "default": "include",
        "required": True,
    },
    "classes": {
        "type": "textarea",
        "label": (
            "대상 Class 이름 (줄바꿈 구분, any match). "
            "비워두면 include_unknown 조합으로만 판정."
        ),
        "required": False,
    },
    "include_unknown": {
        "type": "checkbox",
        "label": (
            "Unknown(null) 라벨도 매칭 대상에 포함 "
            "(체크 시 labels[head] 가 null 인 이미지도 match)"
        ),
        "default": False,
        "required": False,
    },
}

_NEW_DESCRIPTION = (
    "Class 기반 이미지 필터 (특정 head 의 class 포함/제외 + unknown 토글로 "
    "이미지 단위 keep/drop)"
)

# downgrade 에서 cls_remove_images_without_label 을 되살리기 위한 기존 seed 재구축용.
# 015 (`015_cls_desc_rewrite.py`) 까지 반영된 값.
_OLD_REMOVE_PARAMS: dict = {
    "target_head_names": {
        "type": "multiselect",
        "label": "대상 Head 이름 목록",
        "options": [],
        "required": False,
    },
}
_OLD_REMOVE_DESCRIPTION = "Label 없는 이미지 제거"

# downgrade 용 cls_filter_by_class 원형 params (023 이전 stub 시절 기준).
_OLD_FILTER_PARAMS: dict = {
    "head_name": {
        "type": "text",
        "label": "대상 Head 이름",
        "required": True,
    },
    "class_names": {
        "type": "textarea",
        "label": "대상 Class 이름 (줄바꿈 구분)",
        "required": True,
    },
    "mode": {
        "type": "select",
        "label": "필터 모드",
        "options": ["include", "exclude"],
        "default": "include",
        "required": True,
    },
}
_OLD_FILTER_DESCRIPTION = (
    "특정 head 의 특정 class 를 포함(include)하거나 제외(exclude) 하는 이미지 단위 필터."
)


def upgrade() -> None:
    connection = op.get_bind()

    # 1) cls_filter_by_class params 갱신.
    connection.exec_driver_sql(
        "UPDATE manipulators "
        "SET params_schema = %s::jsonb, description = %s "
        "WHERE name = %s;",
        (json.dumps(_NEW_PARAMS), _NEW_DESCRIPTION, _FILTER_NAME),
    )

    # 2) cls_remove_images_without_label 제거.
    connection.exec_driver_sql(
        "DELETE FROM manipulators WHERE name = %s;",
        (_REMOVE_NAME,),
    )


def downgrade() -> None:
    connection = op.get_bind()

    # 1) cls_filter_by_class 를 원형 params 로 복구.
    connection.exec_driver_sql(
        "UPDATE manipulators "
        "SET params_schema = %s::jsonb, description = %s "
        "WHERE name = %s;",
        (json.dumps(_OLD_FILTER_PARAMS), _OLD_FILTER_DESCRIPTION, _FILTER_NAME),
    )

    # 2) cls_remove_images_without_label 재삽입 (stub 시절 메타데이터).
    connection.exec_driver_sql(
        "INSERT INTO manipulators "
        "(id, name, category, scope, compatible_task_types, compatible_annotation_fmts, "
        " output_annotation_fmt, params_schema, description, status, version, created_at) "
        "VALUES (gen_random_uuid(), %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, "
        "        %s, %s::jsonb, %s, %s, %s, NOW()) "
        "ON CONFLICT (name) DO NOTHING;",
        (
            _REMOVE_NAME,
            "IMAGE_FILTER",
            json.dumps(["PER_SOURCE", "POST_MERGE"]),
            json.dumps(["CLASSIFICATION"]),
            json.dumps(["CLS_MANIFEST"]),
            "CLS_MANIFEST",
            json.dumps(_OLD_REMOVE_PARAMS),
            _OLD_REMOVE_DESCRIPTION,
            "ACTIVE",
            "1.0.0",
        ),
    )
