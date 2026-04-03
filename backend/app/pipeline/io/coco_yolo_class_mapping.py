"""
app.pipeline.io.coco_yolo_class_mapping — lib.pipeline.io.coco_yolo_class_mapping re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.io.coco_yolo_class_mapping을 직접 import할 것.
"""
from lib.pipeline.io.coco_yolo_class_mapping import (  # noqa: F401
    COCO_80_CLASSES,
    COCO_ID_TO_NAME,
    COCO_ID_TO_YOLO_ID,
    NAME_TO_COCO_ID,
    NAME_TO_YOLO_ID,
    YOLO_ID_TO_COCO_ID,
    YOLO_ID_TO_NAME,
    build_coco_to_yolo_remap,
    build_yolo_to_coco_remap,
)
