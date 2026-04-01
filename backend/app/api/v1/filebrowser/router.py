"""
서버 파일 브라우저 API

사용자가 /mnt/uploads (LOCAL_UPLOAD_BASE) 아래에 사전에 올려둔 데이터를
GUI로 탐색하여 이미지 폴더 및 어노테이션 파일을 선택할 수 있도록 지원.

경로 제한: docker-compose에서 LOCAL_UPLOAD_BASE 만 마운트하므로
컨테이너는 그 외의 호스트 파일시스템에 접근할 수 없음.
"""
from __future__ import annotations

import structlog
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.schemas.filebrowser import (
    FileBrowserEntry,
    FileBrowserListResponse,
    FileBrowserRootsResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


def _upload_root() -> Path:
    return Path(settings.local_upload_base)


def _make_entry(p: Path) -> FileBrowserEntry:
    try:
        stat = p.stat()
        size = stat.st_size if p.is_file() else None
        modified_at = datetime.fromtimestamp(stat.st_mtime)
    except OSError:
        size = None
        modified_at = None

    return FileBrowserEntry(
        name=p.name,
        path=str(p),
        is_dir=p.is_dir(),
        size=size,
        modified_at=modified_at,
    )


@router.get("/roots", response_model=FileBrowserRootsResponse)
def list_roots():
    """업로드 루트 경로 반환."""
    logger.info("파일 브라우저 루트 조회", root=str(_upload_root()))
    return FileBrowserRootsResponse(roots=[str(_upload_root())])


@router.get("/list", response_model=FileBrowserListResponse)
def list_directory(
    path: str = Query(default="", description="탐색할 절대경로. 비어있으면 업로드 루트 반환."),
    mode: str = Query(default="all", description="directory | file | all"),
):
    """
    디렉토리 내용 목록 반환.

    - path 미입력: 업로드 루트 디렉토리 내용 반환
    - mode=directory: 디렉토리만 표시
    - mode=file: 파일만 표시
    - mode=all: 모두 표시
    """
    logger.info("디렉토리 목록 조회", path=path, mode=mode)
    root = _upload_root()

    if not path.strip():
        target = root
    else:
        target = Path(path)

    if not target.exists():
        logger.warning("디렉토리 조회 실패 — 경로 없음", path=path)
        raise HTTPException(status_code=404, detail=f"경로가 존재하지 않습니다: {path}")
    if not target.is_dir():
        logger.warning("디렉토리 조회 실패 — 파일 경로", path=path)
        raise HTTPException(status_code=400, detail="디렉토리 경로를 지정하세요.")

    # 업로드 루트 상위는 표시하지 않음
    try:
        target.relative_to(root)
    except ValueError:
        target = root

    # 상위 경로 (루트면 None)
    parent_path: str | None = None
    is_browse_root = (target == root)
    if not is_browse_root:
        parent = target.parent
        # parent가 root보다 상위이면 root로 고정
        try:
            parent.relative_to(root)
            parent_path = str(parent)
        except ValueError:
            parent_path = str(root)

    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail="디렉토리 접근 권한이 없습니다.") from e

    entries = []
    for child in children:
        if child.name.startswith("."):
            continue
        if mode == "directory" and not child.is_dir():
            continue
        if mode == "file" and child.is_dir():
            continue
        entries.append(_make_entry(child))

    logger.info("디렉토리 목록 조회 완료", path=str(target), entry_count=len(entries))
    return FileBrowserListResponse(
        current_path=str(target),
        parent_path=parent_path,
        is_browse_root=is_browse_root,
        entries=entries,
    )
