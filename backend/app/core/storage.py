"""
스토리지 추상화 레이어

설계 원칙:
  - 모든 파일 접근 코드는 StorageClient 인터페이스만 사용
  - 실제 구현체는 환경변수(STORAGE_BACKEND)에 따라 자동 선택
  - 1차: LocalStorageClient (NAS 직접 마운트)
  - 3차: S3StorageClient (MinIO or 클라우드 S3)

스토리지 구조:
  {base}/
    raw/{name}/{split}/{version}/images/
    raw/{name}/{split}/{version}/annotation.json
    source/...
    processed/...
    fusion/...
    eda/{dataset_id}/
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_app_config, get_settings


class StorageClient(ABC):
    """
    스토리지 추상 인터페이스.
    비즈니스 로직은 이 인터페이스만 사용한다.
    """

    @abstractmethod
    def resolve_path(self, relative_path: str) -> Path:
        """
        상대경로 → 실제 접근 가능한 절대경로 반환.
        DB에는 항상 상대경로만 저장한다.

        Args:
            relative_path: "processed/coco_aug/train/v1.0.0"

        Returns:
            실제 파일시스템 Path 객체
        """
        ...

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        """경로 존재 여부 확인."""
        ...

    @abstractmethod
    def list_files(self, relative_path: str, extensions: set[str] | None = None) -> list[str]:
        """
        지정 경로 하위의 파일 목록 반환 (재귀).

        Args:
            relative_path: 탐색할 상대경로
            extensions: 필터할 확장자 집합 (예: {'.jpg', '.png'})
                        None이면 모든 파일

        Returns:
            파일들의 상대경로 리스트
        """
        ...

    @abstractmethod
    def makedirs(self, relative_path: str) -> None:
        """디렉토리 생성 (부모 포함)."""
        ...

    @abstractmethod
    def get_image_serve_url(self, relative_path: str) -> str:
        """
        GUI에서 이미지를 표시하기 위한 URL 반환.
        Nginx static 서빙 URL 형태로 반환.
        """
        ...

    @abstractmethod
    def get_eda_path(self, dataset_id: str) -> Path:
        """EDA 결과 저장 경로 반환."""
        ...

    def build_dataset_uri(
        self,
        dataset_type: str,
        name: str,
        split: str,
        version: str,
    ) -> str:
        """
        표준 dataset storage_uri 생성.
        DB에 저장되는 값.

        Returns:
            예: "processed/coco_aug/train/v1.0.0"
        """
        cfg = get_app_config()
        type_dir = {
            "RAW": cfg.get("storage", "dir_raw", "raw"),
            "SOURCE": cfg.get("storage", "dir_source", "source"),
            "PROCESSED": cfg.get("storage", "dir_processed", "processed"),
            "FUSION": cfg.get("storage", "dir_fusion", "fusion"),
        }.get(dataset_type.upper(), dataset_type.lower())

        split_dir = split.lower() if split.upper() != "NONE" else "none"
        return f"{type_dir}/{name}/{split_dir}/{version}"

    def get_images_path(self, storage_uri: str) -> Path:
        """images/ 서브디렉토리 경로 반환."""
        cfg = get_app_config()
        return self.resolve_path(storage_uri) / cfg.images_dirname

    def get_annotation_path(self, storage_uri: str) -> Path:
        """annotation.json 경로 반환."""
        cfg = get_app_config()
        return self.resolve_path(storage_uri) / cfg.annotation_filename


class LocalStorageClient(StorageClient):
    """
    NAS 직접 마운트 기반 스토리지 클라이언트.
    1~2차 단계에서 사용.
    """

    def __init__(self, base_path: str, eda_base_path: str) -> None:
        self._base = Path(base_path)
        self._eda_base = Path(eda_base_path)

    def resolve_path(self, relative_path: str) -> Path:
        return self._base / relative_path

    def exists(self, relative_path: str) -> bool:
        return self.resolve_path(relative_path).exists()

    def list_files(self, relative_path: str, extensions: set[str] | None = None) -> list[str]:
        base_path = self.resolve_path(relative_path)
        if not base_path.exists():
            return []

        result = []
        for p in base_path.rglob("*"):
            if p.is_file():
                if extensions is None or p.suffix.lower() in extensions:
                    # 상대경로로 반환
                    result.append(str(p.relative_to(self._base)))
        return sorted(result)

    def makedirs(self, relative_path: str) -> None:
        self.resolve_path(relative_path).mkdir(parents=True, exist_ok=True)

    def get_image_serve_url(self, relative_path: str) -> str:
        """Nginx /static/* 경로로 매핑."""
        return f"/static/{relative_path}"

    def get_eda_path(self, dataset_id: str) -> Path:
        path = self._eda_base / dataset_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def count_images(self, storage_uri: str) -> int:
        """이미지 파일 수 카운트."""
        cfg = get_app_config()
        return len(self.list_files(
            f"{storage_uri}/{cfg.images_dirname}",
            extensions=cfg.allowed_image_extensions,
        ))

    def validate_structure(self, storage_uri: str) -> dict[str, bool | int]:
        """
        데이터셋 경로 구조 유효성 검사.
        GUI 등록 시 '경로 검증' 버튼에서 호출.
        """
        cfg = get_app_config()
        base = self.resolve_path(storage_uri)
        images_dir = base / cfg.images_dirname
        annotation_file = base / cfg.annotation_filename

        image_count = 0
        if images_dir.exists():
            image_count = sum(
                1 for p in images_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in cfg.allowed_image_extensions
            )

        return {
            "path_exists": base.exists(),
            "images_dir_exists": images_dir.exists(),
            "annotation_exists": annotation_file.exists(),
            "image_count": image_count,
        }


class S3StorageClient(StorageClient):
    """
    S3 호환 스토리지 클라이언트 (3차 K8S 전환 시 구현).
    현재는 NotImplementedError만 발생시키는 stub.
    """

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        # 3차에서 boto3/aioboto3 초기화
        raise NotImplementedError("S3StorageClient는 3차에서 구현됩니다.")

    def resolve_path(self, relative_path: str) -> Path:
        raise NotImplementedError

    def exists(self, relative_path: str) -> bool:
        raise NotImplementedError

    def list_files(self, relative_path: str, extensions: set[str] | None = None) -> list[str]:
        raise NotImplementedError

    def makedirs(self, relative_path: str) -> None:
        raise NotImplementedError

    def get_image_serve_url(self, relative_path: str) -> str:
        raise NotImplementedError

    def get_eda_path(self, dataset_id: str) -> Path:
        raise NotImplementedError


def get_storage_client() -> StorageClient:
    """
    환경변수에 따라 적절한 StorageClient 반환.
    FastAPI Depends 또는 직접 호출로 사용.

    Usage:
        # FastAPI Depends
        storage: StorageClient = Depends(get_storage_client)

        # 직접 사용
        client = get_storage_client()
    """
    s = get_settings()

    if s.storage_backend == "local":
        return LocalStorageClient(
            base_path=s.local_storage_base,
            eda_base_path=s.local_eda_base,
        )
    elif s.storage_backend == "s3":
        return S3StorageClient(
            endpoint=s.s3_endpoint or "",
            access_key=s.s3_access_key or "",
            secret_key=s.s3_secret_key or "",
            bucket=s.s3_bucket or "",
        )
    else:
        raise ValueError(f"알 수 없는 STORAGE_BACKEND: {s.storage_backend}")
