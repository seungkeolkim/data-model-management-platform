"""
Manipulator 레지스트리 — 자동 발견.

설계:
  - 이 패키지 하위의 모든 .py 모듈을 walk하여 UnitManipulator 서브클래스를 자동 수집
  - 새 manipulator 추가 시 이 파일 수정 불필요 (lib/manipulators/ 아래 모듈만 추가)
  - `name` 속성(property)을 키로 사용 — DB seed의 manipulators.name과 일치시켜야 함

주의:
  - 수집 대상은 UnitManipulator의 "구체" 서브클래스만. 추상 중간 클래스는 제외.
  - 같은 name이 2번 등록되면 즉시 예외 — seed 정합성 버그 조기 감지.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING

from lib.pipeline.manipulator_base import UnitManipulator

if TYPE_CHECKING:
    pass


def _discover_manipulator_classes() -> dict[str, type[UnitManipulator]]:
    """
    이 패키지 하위 모듈을 iter_modules로 순회하며 UnitManipulator 서브클래스를 수집.

    수집 규칙:
      - abstract 클래스(ABC) 제외
      - 이름이 UnitManipulator와 같거나 중간 추상 베이스 제외
      - 인스턴스화하여 `.name` 프로퍼티 값을 키로 사용
    """
    discovered: dict[str, type[UnitManipulator]] = {}
    package_name = __name__
    package_path = __path__  # type: ignore[name-defined]

    for module_info in pkgutil.iter_modules(package_path):
        # 언더스코어로 시작하는 내부 모듈 스킵
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package_name}.{module_info.name}")

        for _, obj in inspect.getmembers(module, inspect.isclass):
            # 이 모듈에서 정의된 클래스만 (import된 상위 베이스 제외)
            if obj.__module__ != module.__name__:
                continue
            if not issubclass(obj, UnitManipulator):
                continue
            if obj is UnitManipulator:
                continue
            if inspect.isabstract(obj):
                continue

            # `.name`을 얻기 위해 인스턴스화 시도
            try:
                instance = obj()
                manipulator_name = instance.name
            except Exception:
                # name property가 인스턴스화 없이 동작하지 않으면 skip
                continue

            if manipulator_name in discovered:
                raise RuntimeError(
                    f"중복 manipulator name '{manipulator_name}': "
                    f"{discovered[manipulator_name].__name__} vs {obj.__name__}"
                )
            discovered[manipulator_name] = obj

    return discovered


# 모듈 import 시 1회 자동 수집.
MANIPULATOR_REGISTRY: dict[str, type[UnitManipulator]] = _discover_manipulator_classes()
