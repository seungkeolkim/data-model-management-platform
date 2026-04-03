"""
app.pipeline.executor — lib.pipeline.executor re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.executor를 직접 import할 것.

app 레이어 전용 기능 (get_settings, get_app_config 연동)이 필요하면
이 모듈에 래퍼 함수를 추가한다.
"""
from lib.pipeline.executor import (  # noqa: F401
    PipelineExecutor,
    PipelineResult,
    load_source_meta_from_storage,
)
