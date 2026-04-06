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
    raw/{name}/{split}/{version}/annotations/
    source/...
    processed/...
    fusion/...
    eda/{dataset_id}/
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from app.core.config import get_app_config, get_settings

logger = structlog.get_logger(__name__)


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
        app_config = get_app_config()
        type_dir = {
            "RAW": app_config.get("storage", "dir_raw", "raw"),
            "SOURCE": app_config.get("storage", "dir_source", "source"),
            "PROCESSED": app_config.get("storage", "dir_processed", "processed"),
            "FUSION": app_config.get("storage", "dir_fusion", "fusion"),
        }.get(dataset_type.upper(), dataset_type.lower())

        split_dir = split.lower() if split.upper() != "NONE" else "none"
        return f"{type_dir}/{name}/{split_dir}/{version}"

    def get_images_dir(self, storage_uri: str) -> Path:
        """images/ 서브디렉토리 경로 반환."""
        app_config = get_app_config()
        return self.resolve_path(storage_uri) / app_config.images_dirname

    def get_annotations_dir(self, storage_uri: str) -> Path:
        """annotations/ 디렉토리 경로 반환."""
        app_config = get_app_config()
        return self.resolve_path(storage_uri) / app_config.annotations_dirname

    @abstractmethod
    def copy_image_directory(self, source_abs: Path, dest_storage_uri: str) -> int:
        """
        이미지 폴더를 관리 스토리지의 images/ 로 복사.

        Args:
            source_abs: 원본 이미지 폴더 절대경로
            dest_storage_uri: 복사 대상 dataset storage_uri (예: "raw/my_data/train/v1.0.0")

        Returns:
            복사된 이미지 파일 수
        """
        ...

    @abstractmethod
    def copy_annotation_files(
        self, source_abs_paths: list[Path], dest_storage_uri: str
    ) -> list[str]:
        """
        어노테이션 파일들을 관리 스토리지의 annotations/ 하위로 복사. 원본 파일명 유지.

        Args:
            source_abs_paths: 원본 어노테이션 파일 절대경로 목록
            dest_storage_uri: 복사 대상 dataset storage_uri (예: "raw/my_data/train/v1.0.0")

        Returns:
            복사된 파일명 목록 (원본 파일명 그대로)
        """
        ...

    @abstractmethod
    def copy_annotation_meta_file(
        self, source_abs_path: Path, dest_storage_uri: str
    ) -> str:
        """
        어노테이션 메타 파일(예: data.yaml)을 관리 스토리지의 annotations/ 하위로 복사.

        Args:
            source_abs_path: 원본 메타 파일 절대경로
            dest_storage_uri: 복사 대상 dataset storage_uri

        Returns:
            복사된 파일명 (원본 파일명 그대로)
        """
        ...

    @abstractmethod
    def delete_dataset_directory(self, storage_uri: str) -> bool:
        """
        데이���셋 디렉��리 전체 삭제 (images/, annotations/ 포함).

        Args:
            storage_uri: 삭제할 dataset storage_uri (예: "raw/my_data/train/v1.0.0")

        Returns:
            True면 실제로 삭제됨, False면 경로가 존재하지 않았음
        """
        ...


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

    def copy_image_directory(self, source_abs: Path, dest_storage_uri: str) -> int:
        """이미지 폴더를 {dest_storage_uri}/images/ 로 복사."""
        app_config = get_app_config()
        dest = self.resolve_path(dest_storage_uri) / app_config.images_dirname
        logger.info("copytree 시작 (이미지 폴더)", source=str(source_abs), dest=str(dest))
        shutil.copytree(source_abs, dest)
        image_count = sum(
            1 for p in dest.rglob("*")
            if p.is_file() and p.suffix.lower() in app_config.allowed_image_extensions
        )
        logger.info("copytree 완료 (이미지 폴더)", image_count=image_count)
        return image_count

    def copy_annotation_files(
        self, source_abs_paths: list[Path], dest_storage_uri: str
    ) -> list[str]:
        """어노테이션 파일들을 {dest_storage_uri}/annotations/ 로 복사. 원본 파일명 유지."""
        app_config = get_app_config()
        dest_dir = self.resolve_path(dest_storage_uri) / app_config.annotations_dirname
        dest_dir.mkdir(parents=True, exist_ok=True)
        logger.info("어노테이션 파일 복사 시작", file_count=len(source_abs_paths), dest=str(dest_dir))
        filenames = []
        for src in source_abs_paths:
            shutil.copy2(src, dest_dir / src.name)
            filenames.append(src.name)
        logger.info("어노테이션 파일 복사 완료", file_count=len(filenames))
        return filenames

    def copy_annotation_meta_file(
        self, source_abs_path: Path, dest_storage_uri: str
    ) -> str:
        """어노테이션 메타 파일을 {dest_storage_uri}/annotations/ 로 복사. 원본 파일명 유지."""
        app_config = get_app_config()
        dest_dir = self.resolve_path(dest_storage_uri) / app_config.annotations_dirname
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_abs_path, dest_dir / source_abs_path.name)
        logger.info("어노테이션 메타 파일 복사 완료", file=source_abs_path.name, dest=str(dest_dir))
        return source_abs_path.name

    def delete_dataset_directory(self, storage_uri: str) -> bool:
        """
        데이터셋 디렉토리 전체 삭제 (images/, annotations/ 포함).
        삭제 후 비어있는 상위 디렉토리도 base 경로까지 재귀적으로 정리한다.
        예: raw/coco-v3/train/v1.0.0 삭제 후 train/, coco-v3/ 가 비면 함께 제거.
        """
        target_path = self.resolve_path(storage_uri)
        if not target_path.exists():
            logger.warning("삭제 대상 경로가 존재하지 않음", storage_uri=storage_uri)
            return False
        shutil.rmtree(target_path)
        logger.info("데이터셋 디렉토리 삭제 완료", storage_uri=storage_uri, path=str(target_path))

        # 빈 상위 디렉토리 정리 (base 경로까지만)
        parent = target_path.parent
        while parent != self._base and parent.exists():
            if any(parent.iterdir()):
                break  # 다른 파일/폴더가 남아있으면 중단
            parent.rmdir()
            logger.info("빈 상위 디렉토리 제거", path=str(parent))
            parent = parent.parent

        return True

    def count_images(self, storage_uri: str) -> int:
        """이미지 파일 수 카운트."""
        app_config = get_app_config()
        return len(self.list_files(
            f"{storage_uri}/{app_config.images_dirname}",
            extensions=app_config.allowed_image_extensions,
        ))

    def validate_structure(self, storage_uri: str) -> dict[str, bool | int]:
        """
        데이터셋 경로 구조 유효성 검사.
        GUI 등록 시 '경로 검증' 버튼에서 호출.
        """
        app_config = get_app_config()
        base = self.resolve_path(storage_uri)
        images_dir = base / app_config.images_dirname
        annotations_dir = base / app_config.annotations_dirname

        image_count = 0
        if images_dir.exists():
            image_count = sum(
                1 for p in images_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in app_config.allowed_image_extensions
            )

        annotation_count = 0
        if annotations_dir.exists():
            annotation_count = sum(1 for p in annotations_dir.iterdir() if p.is_file())

        return {
            "path_exists": base.exists(),
            "images_dir_exists": images_dir.exists(),
            "annotations_dir_exists": annotations_dir.exists(),
            "image_count": image_count,
            "annotation_count": annotation_count,
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

    def copy_image_directory(self, source_abs: Path, dest_storage_uri: str) -> int:
        raise NotImplementedError

    def copy_annotation_files(
        self, source_abs_paths: list[Path], dest_storage_uri: str
    ) -> list[str]:
        raise NotImplementedError

    def delete_dataset_directory(self, storage_uri: str) -> bool:
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
    storage_backend_config = get_settings()

    if storage_backend_config.storage_backend == "local":
        return LocalStorageClient(
            base_path=storage_backend_config.local_storage_base,
            eda_base_path=storage_backend_config.local_eda_base,
        )
    elif storage_backend_config.storage_backend == "s3":
        return S3StorageClient(
            endpoint=storage_backend_config.s3_endpoint or "",
            access_key=storage_backend_config.s3_access_key or "",
            secret_key=storage_backend_config.s3_secret_key or "",
            bucket=storage_backend_config.s3_bucket or "",
        )
    else:
        raise ValueError(f"알 수 없는 STORAGE_BACKEND: {storage_backend_config.storage_backend}")
