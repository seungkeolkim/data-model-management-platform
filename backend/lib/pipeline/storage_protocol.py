"""
스토리지 인터페이스 프로토콜.

파이프라인 실행 엔진이 필요로 하는 스토리지 메서드만 정의한다.
app.core.storage.StorageClient가 이 프로토콜을 자연스럽게 만족한다.
lib/ 패키지가 app/ 에 의존하지 않도록 분리하기 위한 Protocol.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProtocol(Protocol):
    """
    파이프라인 실행에 필요한 스토리지 메서드 프로토콜.

    app.core.storage.StorageClient는 이 프로토콜의 모든 메서드를 이미 구현하고 있다.
    """

    def resolve_path(self, relative_path: str) -> Path:
        """상대경로 → 절대경로 변환."""
        ...

    def exists(self, relative_path: str) -> bool:
        """경로 존재 여부 확인."""
        ...

    def makedirs(self, relative_path: str) -> None:
        """디렉토리 생성 (부모 포함)."""
        ...

    def build_dataset_uri(
        self,
        dataset_type: str,
        name: str,
        split: str,
        version: str,
    ) -> str:
        """표준 dataset storage_uri 생성."""
        ...

    def get_images_path(self, storage_uri: str) -> Path:
        """images/ 서브디렉토리 경로 반환."""
        ...

    def get_annotations_dir(self, storage_uri: str) -> Path:
        """annotations/ 디렉토리 경로 반환."""
        ...
