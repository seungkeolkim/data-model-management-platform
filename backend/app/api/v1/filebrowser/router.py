"""
서버 파일 브라우저 API

사용자가 서버 로컬 파일시스템을 GUI로 탐색하여
이미지 폴더 및 어노테이션 파일을 선택할 수 있도록 지원.

허용 경로: LOCAL_BROWSE_ROOTS 환경변수로 지정한 루트들 하위만 접근 가능.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.schemas.filebrowser import (
    FileBrowserEntry,
    FileBrowserListResponse,
    FileBrowserRootsResponse,
)

router = APIRouter()


def _resolve_safe(path_str: str) -> Path:
    """
    요청 경로를 정규화하고 허용된 루트 중 하나의 하위인지 검증.
    통과하지 못하면 403 raise.
    """
    try:
        resolved = Path(path_str).resolve()
    except Exception as e:
        raise HTTPException(status_code=400, detail="잘못된 경로입니다.") from e

    for root in settings.local_browse_roots_list:
        try:
            resolved.relative_to(Path(root).resolve())
            return resolved
        except ValueError:
            continue

    raise HTTPException(
        status_code=403,
        detail=f"허용되지 않은 경로입니다. 접근 가능한 루트: {settings.local_browse_roots_list}",
    )


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
    """허용된 브라우저 루트 목록 반환."""
    return FileBrowserRootsResponse(roots=settings.local_browse_roots_list)


@router.get("/list", response_model=FileBrowserListResponse)
def list_directory(
    path: str = Query(default="", description="탐색할 절대경로. 비어있으면 루트 목록 반환."),
    mode: str = Query(default="all", description="directory | file | all"),
):
    """
    디렉토리 내용 목록 반환.

    - path 미입력: 허용된 루트 목록을 entries로 반환 (is_browse_root=True)
    - path 입력: 해당 경로의 파일/디렉토리 목록 반환
    - mode=directory: 디렉토리만 표시
    - mode=file: 파일만 표시
    - mode=all: 모두 표시
    """
    # path가 비어있으면 루트 목록 화면
    if not path.strip():
        roots = settings.local_browse_roots_list
        entries = []
        for r in roots:
            rp = Path(r)
            if rp.exists():
                entries.append(_make_entry(rp))
        return FileBrowserListResponse(
            current_path="",
            parent_path=None,
            is_browse_root=True,
            entries=entries,
        )

    resolved = _resolve_safe(path)

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"경로가 존재하지 않습니다: {path}")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="파일 경로가 아닌 디렉토리 경로를 지정하세요.")

    # 상위 경로 계산 (루트 중 하나면 parent_path=None)
    parent = resolved.parent
    parent_path: str | None = str(parent)
    try:
        for root in settings.local_browse_roots_list:
            root_resolved = Path(root).resolve()
            if resolved == root_resolved:
                parent_path = None
                break
    except Exception:
        pass

    # 디렉토리 내용 읽기
    try:
        children = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
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

    return FileBrowserListResponse(
        current_path=str(resolved),
        parent_path=parent_path,
        is_browse_root=False,
        entries=entries,
    )
