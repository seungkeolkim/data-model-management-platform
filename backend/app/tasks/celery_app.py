"""
Celery 앱 초기화
broker/backend 모두 PostgreSQL 사용 (Redis 미사용)
"""
from __future__ import annotations

from celery import Celery

# ORM 세션 이벤트 리스너 등록 — Celery worker 프로세스에서도 반드시 로드되어야
# Dataset 변경 시 DatasetGroup.updated_at 이 갱신된다 (register / pipeline 태스크).
import app.models.events  # noqa: F401
from app.core.config import settings

celery_app = Celery(
    "mlplatform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.pipeline_tasks",
        "app.tasks.register_tasks",
        "app.tasks.register_classification_tasks",
        "app.tasks.eda_tasks",
        # "app.tasks.training_tasks",  # 2차 활성화
    ],
)

celery_app.conf.update(
    # 직렬화
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,

    # 결과 만료 (7일)
    result_expires=604800,

    # 대용량 데이터셋 처리를 위한 timeout (24시간)
    task_soft_time_limit=86400,
    task_time_limit=90000,

    # 재시도 설정
    task_max_retries=3,
    task_default_retry_delay=60,

    # 큐 설정
    task_default_queue="default",
    task_queues={
        "pipeline": {"exchange": "pipeline", "routing_key": "pipeline"},
        "eda": {"exchange": "eda", "routing_key": "eda"},
        "default": {"exchange": "default", "routing_key": "default"},
        # "training": {"exchange": "training", "routing_key": "training"},  # 2차
    },
    task_routes={
        "app.tasks.pipeline_tasks.*": {"queue": "pipeline"},
        "app.tasks.eda_tasks.*": {"queue": "eda"},
        # "app.tasks.training_tasks.*": {"queue": "training"},  # 2차
    },

    # worker 설정
    worker_prefetch_multiplier=1,  # 파이프라인은 long-running이므로 1로 고정
)
