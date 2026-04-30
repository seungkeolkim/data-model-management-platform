"""
시스템 상태 — 호스트 마운트 디렉토리의 디스크 사용량.

매우 단순한 minimal 응답. SystemStatusPage 가 한두 줄로 표시할 정보만.
나중에 큰 작업으로 갈아엎을 예정.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/storage-usage")
def storage_usage() -> dict:
    """
    LOCAL_STORAGE_BASE / LOCAL_UPLOAD_BASE 의 디스크 사용량.

    각 path 에 대해 shutil.disk_usage 결과 (total / used / free 바이트) 반환.
    경로가 없으면 exists=False 로 표시하고 사이즈는 None.
    """
    paths = [
        ("storage", settings.local_storage_base),
        ("upload", settings.local_upload_base),
    ]
    items = []
    for label, raw_path in paths:
        path_obj = Path(raw_path)
        item: dict = {
            "label": label,
            "path": raw_path,
            "exists": path_obj.exists(),
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "error": None,
        }
        if item["exists"]:
            try:
                usage = shutil.disk_usage(path_obj)
                item["total_bytes"] = usage.total
                item["used_bytes"] = usage.used
                item["free_bytes"] = usage.free
            except OSError as exc:
                item["error"] = str(exc)
        items.append(item)
    return {"items": items}
