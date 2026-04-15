"""rename classification manipulators + detection-only narrow + new cls stubs

Revision ID: 012_rename_cls_manips_and_stubs
Revises: 011_narrow_manip_task_types
Create Date: 2026-04-15

배경:
  1) 이름 규약 — Classification 전용 manipulator 는 모두 `_classification` 접미사로 통일한다.
     Detection 전용과 팔레트/코드 어디서도 착각할 일이 없도록 하고, 이후 SEGMENTATION 등
     다른 task 용 manipulator 가 추가될 때도 동일 패턴 확장이 가능하게 한다.

  2) compatible_task_types 가 비어있던 4종을 명시적으로 ["DETECTION"] 으로 좁힌다.
     빈 목록이 팔레트 필터 규칙상 "모든 task 에 노출" 이 되는 관대한 해석이라,
     Classification 팔레트에 detection 전용 노드가 새어들어오는 것을 차단한다.

  3) merge_datasets / sample_n_images 는 자료구조 이질성 때문에 classification 전용
     변형이 필요하므로 stub seed 2종(merge_datasets_classification,
     sample_n_images_classification) 을 추가한다. 실제 transform 구현은 이후.

조치 요약:
  - UPDATE: 기존 classification manipulator 8종의 `name` 을 접미사 규약으로 rename
  - UPDATE: detection 전용 4종의 compatible_task_types 를 ["DETECTION"] 으로 명시
  - INSERT: classification stub 2종 추가 (manipulators 테이블)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_rename_cls_manips_and_stubs"
down_revision: Union[str, None] = "011_narrow_manip_task_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# 1. Classification manipulator 이름 rename 매핑 (old → new)
# ---------------------------------------------------------------------------
_CLS_RENAMES: dict[str, str] = {
    "select_classification_heads": "select_heads_classification",
    "rename_classification_head": "rename_head_classification",
    "reorder_classification_heads": "reorder_heads_classification",
    "rename_classification_class": "rename_class_classification",
    "merge_classification_classes": "merge_classes_classification",
    "reorder_classification_classes": "reorder_classes_classification",
    "filter_by_classification_class": "filter_by_class_classification",
    "remove_images_without_classification_label": "remove_images_without_label_classification",
}


# ---------------------------------------------------------------------------
# 2. 빈 compatible_task_types 4종을 ["DETECTION"] 으로 명시
#    (migration 011 이 이미 6종을 처리했으나 당시 빈 목록 4종은 의도적 보류)
# ---------------------------------------------------------------------------
_DETECTION_ONLY_NAMES: list[str] = [
    "merge_datasets",
    "sample_n_images",
    "change_compression",
    "shuffle_image_ids",
]
_DETECTION_ONLY_JSON = json.dumps(["DETECTION"])


# ---------------------------------------------------------------------------
# 3. 신규 classification stub seed 2종
# ---------------------------------------------------------------------------
_SEED_CREATED_AT = datetime.utcnow().isoformat()


def _build_cls_stub_seed(
    name: str,
    category: str,
    scope: list[str],
    params_schema: dict,
    description: str,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "category": category,
        "scope": json.dumps(scope),
        "compatible_task_types": json.dumps(["CLASSIFICATION"]),
        "compatible_annotation_fmts": json.dumps(["CLS_MANIFEST"]),
        "output_annotation_fmt": "CLS_MANIFEST",
        "params_schema": json.dumps(params_schema),
        "description": description,
        "status": "ACTIVE",
        "version": "1.0.0",
        "created_at": _SEED_CREATED_AT,
    }


_NEW_CLASSIFICATION_STUBS: list[dict] = [
    _build_cls_stub_seed(
        name="merge_datasets_classification",
        category="MERGE",
        scope=["POST_MERGE"],
        description=(
            "여러 Classification 데이터셋을 병합한다. "
            "head_schema 정합성 검사 + SHA 기반 이미지 dedup + labels union."
        ),
        params_schema={
            "on_single_label_conflict": {
                "type": "enum",
                "label": "single-label 충돌 처리",
                "options": ["FAIL", "SKIP"],
                "default": "FAIL",
                "required": True,
            },
        },
    ),
    _build_cls_stub_seed(
        name="sample_n_images_classification",
        category="SAMPLE",
        scope=["PER_SOURCE", "POST_MERGE"],
        description="Classification 데이터셋에서 이미지 N장을 랜덤 샘플링. labels 는 그대로 유지.",
        params_schema={
            "n": {
                "type": "int",
                "label": "샘플 장수",
                "required": True,
            },
            "seed": {
                "type": "int",
                "label": "랜덤 시드 (재현성)",
                "required": False,
            },
        },
    ),
]

_NEW_STUB_NAMES: list[str] = [entry["name"] for entry in _NEW_CLASSIFICATION_STUBS]


def upgrade() -> None:
    # (1) 기존 classification manipulator rename
    for old_name, new_name in _CLS_RENAMES.items():
        op.execute(
            f"UPDATE manipulators SET name = '{new_name}' WHERE name = '{old_name}';"
        )

    # (2) detection 전용 4종 compatible_task_types 명시
    for name in _DETECTION_ONLY_NAMES:
        op.execute(
            "UPDATE manipulators "
            f"SET compatible_task_types = '{_DETECTION_ONLY_JSON}'::jsonb "
            f"WHERE name = '{name}';"
        )

    # (3) 신규 classification stub 2종 INSERT
    op.bulk_insert(
        sa.table(
            "manipulators",
            sa.column("id"),
            sa.column("name"),
            sa.column("category"),
            sa.column("scope"),
            sa.column("compatible_task_types"),
            sa.column("compatible_annotation_fmts"),
            sa.column("output_annotation_fmt"),
            sa.column("params_schema"),
            sa.column("description"),
            sa.column("status"),
            sa.column("version"),
            sa.column("created_at"),
        ),
        _NEW_CLASSIFICATION_STUBS,
    )


def downgrade() -> None:
    # (3') 신규 stub 삭제
    names_sql = ", ".join(f"'{name}'" for name in _NEW_STUB_NAMES)
    op.execute(f"DELETE FROM manipulators WHERE name IN ({names_sql});")

    # (2') 4종 compatible_task_types 를 NULL 로 되돌림
    for name in _DETECTION_ONLY_NAMES:
        op.execute(
            "UPDATE manipulators SET compatible_task_types = NULL "
            f"WHERE name = '{name}';"
        )

    # (1') 이름 역매핑
    for old_name, new_name in _CLS_RENAMES.items():
        op.execute(
            f"UPDATE manipulators SET name = '{old_name}' WHERE name = '{new_name}';"
        )
