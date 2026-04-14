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


# =============================================================================
# Classification 폴더 스캔
# =============================================================================
# 데이터셋 루트 하위를 2레벨 구조 ( <head>/<class>/<images> ) 로 단순 스캔한다.
# 이 시점에는 어떤 규칙(예: prefix 0_, 1_)도 판단하지 않는다 — 화면에서
# 사용자가 직접 순서·설정을 고를 수 있도록 원형 구조를 그대로 반환한다.


class ClassificationClassEntry(BaseModel):
    """하나의 Output Class (level2) 정보."""
    name: str                   # 폴더명 원본 (예: "0_no_helmet")
    path: str                   # 절대경로
    image_count: int            # 해당 폴더 바로 아래 이미지 파일 수
    # class 폴더 안에 서브디렉토리가 있으면 사용자가 데이터셋 루트를 잘못 선택했을
    # 가능성이 높다 (기대 구조는 <root>/<head>/<class>/<images> 2레벨이므로).
    has_subdirs: bool = False


class ClassificationHeadEntry(BaseModel):
    """하나의 Classification Head (level1) 정보."""
    name: str                   # 폴더명 원본 (예: "hardhat_wear")
    path: str                   # 절대경로
    classes: list[ClassificationClassEntry]


class ClassificationScanResponse(BaseModel):
    """데이터셋 루트 2레벨 스캔 결과."""
    root_path: str                              # 스캔한 루트 절대경로
    heads: list[ClassificationHeadEntry]        # 발견된 head 목록
