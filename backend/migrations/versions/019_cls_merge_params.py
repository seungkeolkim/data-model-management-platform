"""cls_merge_datasets params_schema 3옵션 도입 + 설명 갱신

Revision ID: 019_cls_merge_params
Revises: 018_cls_reorder_cls
Create Date: 2026-04-16

배경:
    `cls_merge_datasets` 실제 구현 (`lib/manipulators/cls_merge_datasets.py`) 은
    `objective_n_plan_7th.md §2-11` 정책에 따라 3개 옵션을 입력으로 받는다:
      - on_head_mismatch      : "error" | "fill_empty"
      - on_class_set_mismatch : "error" | "multi_label_union"
      - on_label_conflict     : "drop_image" | "merge_if_compatible"
    012 시드 당시에는 stub 이었던 탓에 `on_single_label_conflict` 단일 파라미터만
    들어가 있었는데, 실구현과 맞지 않아 정적 검증/ FE 모달 분기도 작동할 수 없다.
    본 마이그레이션은 params_schema 를 실구현 기준으로 교체한다.

    description 은 015 에서 stub 문구(“head_schema 정합성 검사 + SHA 기반 이미지
    dedup + labels union”) 가 유지되고 있어 팔레트 라벨로 다소 길다. 짧게
    “데이터셋 병합” 으로 다듬는다 (cls_ 계열 다른 노드들과 톤 통일).

조치:
    UPDATE manipulators
    SET params_schema = _NEW_PARAMS::jsonb,
        description   = _NEW_DESCRIPTION
    WHERE name = 'cls_merge_datasets';

    downgrade 는 012 시드 당시의 on_single_label_conflict 단일 옵션 +
    stub 시절 description 으로 원복한다.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "019_cls_merge_params"
down_revision: str | None = "018_cls_reorder_cls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "cls_merge_datasets"


# 신규 params_schema — DynamicParamForm 은 type="select" 를 지원한다 (enum 은 미지원).
# default 값은 resolve_merge_params 의 기본값과 정확히 일치시켜야 한다.
_NEW_PARAMS: dict = {
    "on_head_mismatch": {
        "type": "select",
        "label": "Head 집합 불일치 처리",
        "options": ["error", "fill_empty"],
        "default": "error",
        "required": True,
    },
    "on_class_set_mismatch": {
        "type": "select",
        "label": "Class 집합 불일치 처리",
        "options": ["error", "multi_label_union"],
        "default": "error",
        "required": True,
    },
    "on_label_conflict": {
        "type": "select",
        "label": "이미지 라벨 충돌 처리",
        "options": ["drop_image", "merge_if_compatible"],
        "default": "drop_image",
        "required": True,
    },
}

_NEW_DESCRIPTION = "데이터셋 병합"

# ---------------------------------------------------------------------------
# downgrade 원복 — 012 stub seed 당시의 값 그대로.
# ---------------------------------------------------------------------------
_OLD_PARAMS: dict = {
    "on_single_label_conflict": {
        "type": "enum",
        "label": "single-label 충돌 처리",
        "options": ["FAIL", "SKIP"],
        "default": "FAIL",
        "required": True,
    },
}

_OLD_DESCRIPTION = (
    "여러 Classification 데이터셋을 병합한다. "
    "head_schema 정합성 검사 + SHA 기반 이미지 dedup + labels union."
)


def _update(params_schema: dict, description: str) -> None:
    """manipulators 테이블에서 cls_merge_datasets 행의 params_schema/description 일괄 교체."""
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE manipulators "
        "SET params_schema = %s::jsonb, description = %s "
        "WHERE name = %s;",
        (json.dumps(params_schema), description, _NAME),
    )


def upgrade() -> None:
    _update(_NEW_PARAMS, _NEW_DESCRIPTION)


def downgrade() -> None:
    _update(_OLD_PARAMS, _OLD_DESCRIPTION)
