"""Classification group.head_schema NULL 백필 — SSOT 정렬

Revision ID: 029_backfill_group_head_schema
Revises: 028_shorten_cls_param_labels
Create Date: 2026-04-22

배경:
    파이프라인 실행 경로가 과거에 DatasetGroup.head_schema 를 채우지 않아,
    파이프라인으로 생성된 classification 그룹 일부가 head_schema=NULL 상태로
    남아 있다. 설계서 §2-8 단일 원칙("Group 내 모든 Dataset 은 동일
    head_schema") 에 어긋나는 상태이며, preview-schema 응답이
    HEAD_SCHEMA_MISSING 경고를 내고 있었다.

    pipeline_tasks._execute_pipeline 에 setdefault 초기화 로직을 추가한 뒤에도
    과거 실행분은 자동 복구되지 않으므로, 이 마이그레이션으로 일회성 백필한다.

규약 (설계서 §2-8):
    DatasetGroup.head_schema JSON 포맷:
        {"heads": [{"name": str, "multi_label": bool, "classes": list[str]}]}

    Dataset.metadata.class_info.heads 는 같은 스키마를 class_mapping 포맷으로
    갖고 있다:
        [{"name": str, "multi_label": bool,
          "class_mapping": {"0": "no_helmet", "1": "helmet"},
          "per_class_image_count": {...}}]
    class_mapping 의 key 가 출력 index 이므로 int 정렬로 classes 순서 복원.

백필 원칙:
    - task_types 에 "CLASSIFICATION" 이 들어 있고 head_schema 가 NULL 인 그룹만 대상.
    - 해당 그룹의 삭제되지 않은 Dataset 중 class_info.heads 가 들어있는 행을
      created_at 오름차순 1개 선택 (최초 생성된 스냅샷). 같은 그룹의 여러 Dataset
      은 SSOT 원칙상 구조가 동일해야 하므로 어느 것을 골라도 같지만, 보수적으로
      '최초' 를 기준으로 삼는다.
    - class_info.heads 가 없는 그룹은 skip + 로그. 수동 조치 필요.

downgrade:
    백필된 그룹을 NULL 로 되돌리는 작업은 단일 원칙에 역행하므로 수행하지 않는다.
    no-op 로 둠 (실수로 역방향 실행해도 데이터 무결성 훼손을 막기 위함).
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "029_backfill_group_head_schema"
down_revision = "028_shorten_cls_param_labels"
branch_labels = None
depends_on = None


def _class_mapping_to_ordered_classes(class_mapping: dict) -> list[str]:
    """class_mapping({"0": "a", "1": "b"}) → classes(["a", "b"]).

    key 를 int 로 정렬해 출력 index 순서를 복원한다. key 가 누락되거나 연속되지
    않으면 존재하는 값만 순서대로 반환한다 (누락된 index 에 대한 가정은 피함).
    """
    if not class_mapping:
        return []
    sorted_items = sorted(class_mapping.items(), key=lambda kv: int(kv[0]))
    return [str(value) for _, value in sorted_items]


def _heads_metadata_to_head_schema_json(metadata_heads: list) -> dict:
    """Dataset.metadata.class_info.heads → DatasetGroup.head_schema JSON 포맷 변환."""
    heads_out: list[dict] = []
    for head in metadata_heads:
        heads_out.append({
            "name": str(head["name"]),
            "multi_label": bool(head.get("multi_label", False)),
            "classes": _class_mapping_to_ordered_classes(
                head.get("class_mapping") or {},
            ),
        })
    return {"heads": heads_out}


def upgrade() -> None:
    connection = op.get_bind()

    # 1) 백필 대상: task_types 에 CLASSIFICATION 이 포함되고 head_schema 가 NULL 인 그룹.
    target_group_rows = connection.execute(
        sa.text(
            """
            SELECT id, name
            FROM dataset_groups
            WHERE head_schema IS NULL
              AND deleted_at IS NULL
              AND task_types::jsonb @> '["CLASSIFICATION"]'::jsonb
            ORDER BY created_at ASC
            """
        )
    ).fetchall()

    if not target_group_rows:
        print("[029 backfill] 대상 그룹 없음 — no-op")
        return

    print(f"[029 backfill] 대상 그룹 수={len(target_group_rows)}")

    restored_count = 0
    skipped_count = 0

    for group_id, group_name in target_group_rows:
        # 해당 그룹의 Dataset 중 class_info.heads 를 가진 최초 행을 찾는다.
        dataset_row = connection.execute(
            sa.text(
                """
                SELECT id, metadata
                FROM datasets
                WHERE group_id = :group_id
                  AND deleted_at IS NULL
                  AND metadata IS NOT NULL
                  AND metadata ? 'class_info'
                  AND (metadata->'class_info') ? 'heads'
                  AND jsonb_array_length((metadata->'class_info')->'heads') > 0
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {"group_id": group_id},
        ).first()

        if dataset_row is None:
            print(
                f"[029 backfill][SKIP] group={group_name} ({group_id}) — "
                "class_info.heads 를 가진 Dataset 없음. 수동 조치 필요."
            )
            skipped_count += 1
            continue

        _, metadata_value = dataset_row
        # asyncpg 드라이버가 JSONB 를 dict 로 반환하지만, 방어적으로 문자열도 허용.
        if isinstance(metadata_value, str):
            metadata = json.loads(metadata_value)
        else:
            metadata = metadata_value

        metadata_heads = (
            metadata.get("class_info", {}).get("heads") if metadata else None
        ) or []
        if not metadata_heads:
            print(
                f"[029 backfill][SKIP] group={group_name} ({group_id}) — "
                "선택된 Dataset.metadata.class_info.heads 가 비어 있음."
            )
            skipped_count += 1
            continue

        new_head_schema = _heads_metadata_to_head_schema_json(metadata_heads)

        connection.execute(
            sa.text("UPDATE dataset_groups SET head_schema = :hs WHERE id = :gid"),
            {"hs": json.dumps(new_head_schema), "gid": group_id},
        )
        head_summary = ", ".join(
            f"{h['name']}({len(h['classes'])}cls)" for h in new_head_schema["heads"]
        )
        print(
            f"[029 backfill][OK] group={group_name} ({group_id}) — "
            f"{len(new_head_schema['heads'])} heads 복원: {head_summary}"
        )
        restored_count += 1

    print(
        f"[029 backfill] 완료 — restored={restored_count}, skipped={skipped_count}, "
        f"total_targets={len(target_group_rows)}"
    )


def downgrade() -> None:
    # 정보 손실을 피하기 위해 no-op.
    # 백필된 head_schema 를 다시 NULL 로 되돌리면 설계서 §2-8 단일 원칙 위반 상태로
    # 회귀하게 된다. 이 마이그레이션의 역방향은 의미가 없다고 판단하여 비워 둔다.
    pass
