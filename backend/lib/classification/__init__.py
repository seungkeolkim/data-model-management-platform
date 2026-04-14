"""
Classification 데이터셋 ingest 순수 로직 패키지.

폴더 구조 <root>/<head>/<class>/<images> 를 스캔·정규화하여
단일 풀(images/{sha}.ext) + manifest.jsonl + head_schema.json 형태로 저장한다.

- lib/ 는 DB/FastAPI 무의존 — storage는 StorageProtocol로 추상화
- 호출자(app/services, celery task)는 이 모듈의 ingest_classification() 1개만 사용
"""
from __future__ import annotations

from lib.classification.ingest import (
    ClassificationHeadInput,
    ClassificationIngestResult,
    DuplicateConflict,
    DuplicateConflictError,
    ImageOccurrence,
    IntraClassDuplicate,
    ingest_classification,
)

__all__ = [
    "ClassificationHeadInput",
    "ClassificationIngestResult",
    "DuplicateConflict",
    "DuplicateConflictError",
    "ImageOccurrence",
    "IntraClassDuplicate",
    "ingest_classification",
]
