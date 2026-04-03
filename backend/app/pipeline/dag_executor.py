"""
app.pipeline.dag_executor — lib.pipeline.dag_executor re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.dag_executor를 직접 import할 것.
"""
from lib.pipeline.dag_executor import (  # noqa: F401
    PipelineDagExecutor,
    PipelineResult,
    load_source_meta_from_storage,
)
