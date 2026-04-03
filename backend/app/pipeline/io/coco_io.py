"""
app.pipeline.io.coco_io — lib.pipeline.io.coco_io re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.io.coco_io를 직접 import할 것.
"""
from lib.pipeline.io.coco_io import parse_coco_json, write_coco_json  # noqa: F401
