"""
ORM 세션 이벤트 리스너.

이 모듈을 import 하는 것만으로 리스너가 등록된다.
애플리케이션/워커 부팅 시 한 번만 import 되도록 한다.

등록된 리스너:
  - DatasetVersion 변경 시 부모 DatasetGroup.updated_at 자동 갱신
    (v7.9 — 3계층 분리 후 group_id 접근 경로가 split 경유로 바뀜)
"""
from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.models.all_models import DatasetGroup, DatasetSplit, DatasetVersion

logger = structlog.get_logger(__name__)


def _resolve_group_id_for_version(
    session: Session, version: DatasetVersion,
) -> str | None:
    """DatasetVersion 에서 group_id 를 안전하게 추출한다.

    v7.9 3계층 분리 후 group_id 접근은 split → group_id 2단 경유다. 우선순위:
      1) association_proxy `version.group_id` 가 바로 값을 반환하면 사용 (split 이
         이미 세션에 로드돼 있으면 lazy load 없이 즉시 해결)
      2) 실패 시 `split_id` 만 보고 DatasetSplit 를 조회해 group_id 반환 (flush 중
         `session.get` 은 안전)

    insert 직후 (DatasetVersion.new) 에는 split relationship 이 아직 연결만 되고
    split_id 가 비어 있을 수 있다. 그 경우 `version.split.group_id` 를 직접 읽어야
    한다.
    """
    # split_slot relationship 이 연결된 경우 (insert 직후 가장 흔한 케이스)
    split_obj = version.__dict__.get("split_slot")
    if split_obj is not None and getattr(split_obj, "group_id", None):
        return split_obj.group_id

    # split_id 만 있는 경우 (update / delete 흐름)
    split_id = getattr(version, "split_id", None)
    if not split_id:
        return None

    # identity_map 조회 (쿼리 없이 즉시 해결되는 경우)
    split_from_map = session.identity_map.get(
        (DatasetSplit, (split_id,), None)
    )
    if split_from_map is not None:
        return split_from_map.group_id

    # 최후 수단: DB 조회. flush 중에도 SELECT 는 허용된다.
    group_id = session.execute(
        select(DatasetSplit.group_id).where(DatasetSplit.id == split_id)
    ).scalar_one_or_none()
    return group_id


@event.listens_for(Session, "before_flush")
def touch_dataset_group_on_version_change(
    session: Session, flush_context, instances
) -> None:
    """
    현재 flush 에 포함된 DatasetVersion 의 insert/update/delete 를 감지해서
    조부모 DatasetGroup 의 updated_at 을 현재 시각으로 갱신한다.

    - DatasetVersion 추가 (session.new): 그룹의 특정 split 에 신규 버전이 커밋됨
    - DatasetVersion 수정 (session.dirty): status / image_count / metadata 등 변화
    - DatasetVersion 삭제 (session.deleted 또는 deleted_at 지정된 update): soft delete

    DatasetGroup / DatasetSplit 자신의 ORM 업데이트는 모델의 onupdate=_now (group 만
    해당, split 은 updated_at 컬럼 없음) 로 자체 갱신되므로 여기서 중복 처리하지 않는다.

    주의: `update(DatasetVersion).where(...).values(...)` 같은 Core bulk 문은
    ORM 이벤트를 트리거하지 않으므로 별도 처리가 필요하다.
    """
    affected_group_ids: set[str] = set()
    for instance in (*session.new, *session.dirty, *session.deleted):
        if isinstance(instance, DatasetVersion):
            group_id = _resolve_group_id_for_version(session, instance)
            if group_id:
                affected_group_ids.add(group_id)

    if not affected_group_ids:
        return

    now = datetime.utcnow()

    # 동일 세션 identity_map 에 이미 적재된 그룹은 속성 갱신만 하면
    # SQLAlchemy 가 이번 flush 에 UPDATE 로 묶어서 내보낸다.
    touched_group_ids: set[str] = set()
    for loaded_object in list(session.identity_map.values()):
        if (
            isinstance(loaded_object, DatasetGroup)
            and loaded_object.id in affected_group_ids
        ):
            loaded_object.updated_at = now
            touched_group_ids.add(loaded_object.id)

    # identity_map 에 없는 그룹은 단일 UPDATE 한 번으로 갱신.
    remaining_group_ids = affected_group_ids - touched_group_ids
    if remaining_group_ids:
        session.execute(
            update(DatasetGroup)
            .where(DatasetGroup.id.in_(remaining_group_ids))
            .values(updated_at=now)
        )
