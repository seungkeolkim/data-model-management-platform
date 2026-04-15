"""
ORM 세션 이벤트 리스너.

이 모듈을 import 하는 것만으로 리스너가 등록된다.
애플리케이션/워커 부팅 시 한 번만 import 되도록 한다.

등록된 리스너:
  - Dataset 변경 시 부모 DatasetGroup.updated_at 자동 갱신
"""
from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.models.all_models import Dataset, DatasetGroup

logger = structlog.get_logger(__name__)


@event.listens_for(Session, "before_flush")
def touch_dataset_group_on_dataset_change(
    session: Session, flush_context, instances
) -> None:
    """
    현재 flush 에 포함된 Dataset 의 insert/update/delete 를 감지해서
    부모 DatasetGroup 의 updated_at 을 현재 시각으로 갱신한다.

    - Dataset 추가 (session.new): 그룹에 split 이 추가됐다
    - Dataset 수정 (session.dirty): status / image_count / metadata 등 변화
    - Dataset 삭제 (session.deleted 또는 deleted_at 지정된 update): soft delete

    DatasetGroup 자신의 ORM 업데이트는 모델의 onupdate=_now 로 이미
    updated_at 이 갱신되므로 여기서 중복 처리하지 않는다.

    주의: `update(Dataset).where(...).values(...)` 같은 Core bulk 문은
    ORM 이벤트를 트리거하지 않으므로 별도 처리가 필요하다. 현재 코드에서는
    delete_group 만 bulk update 를 쓰는데, 그 플로우에서는 DatasetGroup
    자체가 ORM 경로로 수정되어 onupdate 로 updated_at 이 함께 갱신된다.
    """
    affected_group_ids: set[str] = set()
    for instance in (*session.new, *session.dirty, *session.deleted):
        if isinstance(instance, Dataset):
            group_id = getattr(instance, "group_id", None)
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
