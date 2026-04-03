"""
app.manipulators — lib.manipulators re-export.

기존 import 경로 호환을 위한 래퍼.
새 코드에서는 lib.manipulators를 직접 import할 것.
"""
from lib.manipulators import MANIPULATOR_REGISTRY  # noqa: F401
