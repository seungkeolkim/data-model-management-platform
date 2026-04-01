"""
서버 파일 브라우저 스키마
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FileBrowserEntry(BaseModel):
    name: str
    path: str           # 절대경로
    is_dir: bool
    size: int | None    # 파일 크기 (bytes), 디렉토리는 None
    modified_at: datetime | None


class FileBrowserListResponse(BaseModel):
    current_path: str           # 현재 절대경로
    parent_path: str | None     # 상위 절대경로 (루트 목록 화면이면 None)
    is_browse_root: bool        # True이면 허용 루트 목록을 보여주는 최상위 화면
    entries: list[FileBrowserEntry]


class FileBrowserRootsResponse(BaseModel):
    roots: list[str]            # 허용된 루트 절대경로 목록
