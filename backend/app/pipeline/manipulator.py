"""
app.pipeline.manipulator — lib.pipeline.manipulator re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.manipulator를 직접 import할 것.
"""
from lib.pipeline.manipulator import UnitManipulator  # noqa: F401
