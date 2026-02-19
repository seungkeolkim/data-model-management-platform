"""
UnitManipulator 추상 인터페이스 (Phase 2에서 구현)

설계 원칙:
  - 새 manipulator 추가 = 이 클래스 상속 + DB INSERT 만으로 완결
  - 기존 코드 수정 없음
  - transform_annotation: annotation 레벨만 처리, 이미지 파일 I/O 절대 금지
  - build_image_manipulation: 이미지에 적용할 변환 명세만 반환
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.pipeline.models import DatasetMeta, ImageManipulationSpec, ImageRecord


class UnitManipulator(ABC):
    """
    데이터 가공의 원자적 단위 추상 인터페이스.
    모든 manipulator는 이 클래스를 상속받아 구현한다.

    두 단계로 분리:
    1. transform_annotation: annotation JSON 레벨 변환 (빠름)
    2. build_image_manipulation: 이미지 변환 명세 생성 (실제 I/O는 ImageExecutor가 수행)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """DB manipulators.name 과 일치해야 함."""
        ...

    @abstractmethod
    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        Annotation 레벨 변환.

        규칙:
          - 이미지 파일 I/O 절대 금지
          - 이미지 제거는 image_records에서 해당 항목을 제거하는 방식으로 표현
          - PER_SOURCE: DatasetMeta 단건 입력
          - POST_MERGE: list[DatasetMeta] 입력 가능

        Args:
            input_meta: 입력 DatasetMeta (단건 또는 리스트)
            params: manipulator 파라미터 (GUI에서 입력)
            context: 실행 컨텍스트 (선택)

        Returns:
            변환된 DatasetMeta
        """
        ...

    def build_image_manipulation(
        self,
        image_record: ImageRecord,
        params: dict[str, Any],
    ) -> list[ImageManipulationSpec]:
        """
        해당 이미지에 적용할 변환 명세 반환.

        기본 구현: 빈 리스트 반환 (단순 copy)
        이미지 변환이 필요한 manipulator만 오버라이드.

        Args:
            image_record: 대상 이미지 레코드
            params: manipulator 파라미터

        Returns:
            ImageManipulationSpec 리스트. 비어있으면 단순 copy.
        """
        return []
