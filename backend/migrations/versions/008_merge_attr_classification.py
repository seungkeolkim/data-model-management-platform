"""merge ATTR_CLASSIFICATION into CLASSIFICATION

Revision ID: 008_merge_attr_classification
Revises: 007_migrate_version_format
Create Date: 2026-04-14

ATTR_CLASSIFICATION은 CLASSIFICATION으로 통합되었다.
이 마이그레이션은 기존 JSONB 컬럼에 남아있을 수 있는 ATTR_CLASSIFICATION 문자열을
CLASSIFICATION으로 치환한다. 중복이 발생하면 중복을 제거한다.

대상:
- dataset_groups.task_types (JSONB list)
- manipulators.compatible_task_types (JSONB list)

원칙:
- 데이터 손실 없음 — ATTR_CLASSIFICATION이 있던 자리에 CLASSIFICATION이 없었다면 CLASSIFICATION으로 치환
- 이미 CLASSIFICATION이 있었다면 ATTR_CLASSIFICATION을 단순 제거 (중복 방지)
- downgrade는 no-op — ATTR_CLASSIFICATION 복원은 정보가 부족하여 불가능
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "008_merge_attr_classification"
down_revision: Union[str, None] = "007_migrate_version_format"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# jsonb 배열에서 ATTR_CLASSIFICATION → CLASSIFICATION 치환 + 중복 제거.
# jsonb_array_elements_text로 펼친 뒤 CASE로 치환하고 jsonb_agg(DISTINCT)로 다시 묶는다.
_JSONB_MERGE_SQL = """
UPDATE {table}
SET {column} = (
    SELECT jsonb_agg(DISTINCT replaced_element)
    FROM (
        SELECT CASE
            WHEN original_element = 'ATTR_CLASSIFICATION' THEN 'CLASSIFICATION'
            ELSE original_element
        END AS replaced_element
        FROM jsonb_array_elements_text({column}) AS original_element
    ) AS subquery
)
WHERE {column} IS NOT NULL
  AND {column} @> '["ATTR_CLASSIFICATION"]'::jsonb;
"""


def upgrade() -> None:
    # dataset_groups.task_types 정리
    op.execute(
        _JSONB_MERGE_SQL.format(
            table="dataset_groups",
            column="task_types",
        )
    )
    # manipulators.compatible_task_types 정리
    op.execute(
        _JSONB_MERGE_SQL.format(
            table="manipulators",
            column="compatible_task_types",
        )
    )


def downgrade() -> None:
    # ATTR_CLASSIFICATION 복원은 불가능 (정보 손실).
    # 롤백 필요 시 수동으로 원 레코드를 식별하여 처리해야 한다.
    pass
