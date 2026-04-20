"""
Classification 데이터셋 ingest 순수 로직 패키지.

폴더 구조 <root>/<head>/<class>/<images> 를 스캔·정규화하여
단일 풀(images/{original_filename}) + manifest.jsonl + head_schema.json 형태로 저장한다.

이미지 identity = filename. 같은 파일명은 같은 이미지로 간주되며,
single-label head 에서 충돌(같은 파일명이 2개 이상 class 에 존재) 시 warning + skip 처리.

- lib/ 는 DB/FastAPI 무의존 — storage는 StorageProtocol로 추상화
- 호출자(app/services, celery task)는 이 모듈의 ingest_classification() 1개만 사용
"""
from __future__ import annotations

from lib.classification.ingest import (
    ClassificationHeadInput,
    ClassificationIngestResult,
    FilenameCollision,
    ingest_classification,
)

__all__ = [
    "ClassificationHeadInput",
    "ClassificationIngestResult",
    "FilenameCollision",
    "ingest_classification",
]
