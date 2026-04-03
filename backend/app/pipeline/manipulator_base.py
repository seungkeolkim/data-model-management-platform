"""
app.pipeline.manipulator_base — lib.pipeline.manipulator_base re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.pipeline.manipulator_base를 직접 import할 것.
"""
from lib.pipeline.manipulator_base import UnitManipulator  # noqa: F401
