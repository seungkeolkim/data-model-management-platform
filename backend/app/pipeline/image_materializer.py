"""
app.pipeline.image_materializer — lib.pipeline.image_materializer re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.image_materializer를 직접 import할 것.
"""
from lib.pipeline.image_materializer import ImageMaterializer  # noqa: F401
