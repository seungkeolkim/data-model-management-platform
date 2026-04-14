"""
Classification 폴더 구조 → 단일 풀 + manifest.jsonl 정규화 ingest.

입력:
    heads = [HeadSpec(name, multi_label, classes, source_class_paths), ...]
    이 구조는 Pydantic 스키마 ClassificationHeadSpec과 동일한 형태이지만,
    lib/ 는 app/schemas 에 의존하지 않으므로 간단한 dataclass로 재정의한다.

출력 디렉토리 구조 (dest_root 하위):
    images/{sha1}.{원본확장자}
    manifest.jsonl   — 이미지 1장당 1줄
    head_schema.json — 그룹 head_schema 복사본

Manifest 한 줄 스키마:
    {
      "sha": "ab12...",
      "filename": "images/ab12....jpg",
      "original_filename": "img_0001.jpg",
      "labels": {"hardhat_wear": ["helmet"], "visibility": ["seen"]}
    }

단일 label head의 이미지 중복 정책:
    - FAIL: 첫 충돌 감지 즉시 DuplicateConflictError 예외 발생
    - SKIP: 충돌된 이미지는 pool/manifest에 포함하지 않고 계속 진행

중복 탐지는 SHA-1 기반. 파일명/크기가 달라도 내용이 같으면 같은 이미지로 간주한다.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

DuplicatePolicy = Literal["FAIL", "SKIP"]

# 기본 허용 이미지 확장자. 호출자가 override 가능.
DEFAULT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass(frozen=True)
class ClassificationHeadInput:
    """ingest 호출자가 전달하는 head 계약.

    classes 순서는 학습 output index의 SSOT이며, source_class_paths와
    길이가 같아야 한다(동일 index끼리 대응).
    """
    name: str
    multi_label: bool
    classes: list[str]
    source_class_paths: list[str]

    def __post_init__(self) -> None:
        if len(self.classes) != len(self.source_class_paths):
            raise ValueError(
                f"head '{self.name}': classes와 source_class_paths 길이 불일치 "
                f"({len(self.classes)} vs {len(self.source_class_paths)})"
            )


@dataclass
class DuplicateConflict:
    """single-label head에서 이미지가 여러 class에 걸쳐 있는 경우."""
    sha: str
    head_name: str
    conflicting_classes: list[str]
    # 원본 파일명 중 하나(사용자 메시지용)
    sample_original_filename: str


class DuplicateConflictError(Exception):
    """dup_policy=FAIL 상태에서 중복 이미지가 감지됨."""

    def __init__(self, conflict: DuplicateConflict) -> None:
        super().__init__(
            f"head '{conflict.head_name}'에서 이미지 '{conflict.sample_original_filename}'가 "
            f"여러 class({conflict.conflicting_classes})에 동시에 포함되어 있습니다."
        )
        self.conflict = conflict


@dataclass
class ClassificationIngestResult:
    """ingest 완료 후 요약."""
    image_count: int
    head_class_counts: dict[str, list[int]]  # head_name → class 순서별 이미지 수
    manifest_relpath: str  # "manifest.jsonl"
    head_schema_relpath: str  # "head_schema.json"
    skipped_conflicts: list[DuplicateConflict] = field(default_factory=list)


def _compute_sha1(image_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """이미지 파일의 SHA-1 hex digest. 1MB 단위 스트리밍."""
    hasher = hashlib.sha1()
    with image_path.open("rb") as image_file:
        while True:
            chunk = image_file.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _iter_images_in_class_dir(
    class_dir: Path,
    allowed_extensions: set[str],
) -> list[Path]:
    """class 폴더 바로 아래(비재귀)의 이미지 파일 정렬 목록."""
    if not class_dir.exists() or not class_dir.is_dir():
        return []
    images = []
    for entry in class_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if not entry.is_file():
            continue
        if entry.suffix.lower() in allowed_extensions:
            images.append(entry)
    images.sort(key=lambda path: path.name.lower())
    return images


def _build_head_schema_json(heads: list[ClassificationHeadInput]) -> dict:
    """DB head_schema / head_schema.json 에 저장할 구조."""
    return {
        "heads": [
            {
                "name": head.name,
                "multi_label": head.multi_label,
                "classes": list(head.classes),
            }
            for head in heads
        ]
    }


def ingest_classification(
    *,
    dest_root: Path,
    heads: list[ClassificationHeadInput],
    duplicate_policy: DuplicatePolicy = "FAIL",
    allowed_extensions: set[str] | None = None,
) -> ClassificationIngestResult:
    """
    Classification 데이터셋 ingest.

    dest_root는 이미 비어있거나 존재하지 않는 디렉토리여야 안전하다(신규 Dataset 저장 위치).
    이 함수는 dest_root를 필요 시 생성한다.

    Args:
        dest_root: 최종 저장 루트 절대경로. 아래에 images/, manifest.jsonl, head_schema.json 작성.
        heads: head별 (name, multi_label, classes, source_class_paths).
        duplicate_policy: single-label head 이미지 중복 정책.
        allowed_extensions: 허용 이미지 확장자. None이면 DEFAULT_IMAGE_EXTENSIONS.

    Returns:
        ClassificationIngestResult
    """
    extensions = allowed_extensions if allowed_extensions is not None else DEFAULT_IMAGE_EXTENSIONS

    dest_root.mkdir(parents=True, exist_ok=True)
    images_dir = dest_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 1차 패스: 이미지별 SHA-1 계산 + head별 class 라벨 누적.
    # image_records[sha] = {
    #   "original_filename": "...",
    #   "suffix": ".jpg",
    #   "source_abs_path": Path,
    #   "labels": {head_name: {class_name, ...}, ...}
    # }
    image_records: dict[str, dict] = {}

    for head in heads:
        for class_index, class_name in enumerate(head.classes):
            class_dir = Path(head.source_class_paths[class_index])
            for image_path in _iter_images_in_class_dir(class_dir, extensions):
                sha = _compute_sha1(image_path)
                record = image_records.get(sha)
                if record is None:
                    record = {
                        "original_filename": image_path.name,
                        "suffix": image_path.suffix.lower(),
                        "source_abs_path": image_path,
                        "labels": {},
                    }
                    image_records[sha] = record

                head_labels = record["labels"].setdefault(head.name, set())
                head_labels.add(class_name)

    # 2차 패스: 중복 정책 적용 (single-label head에 한해 class 2개 이상이면 충돌).
    skipped_shas: set[str] = set()
    skipped_conflicts: list[DuplicateConflict] = []

    for sha, record in image_records.items():
        for head in heads:
            if head.multi_label:
                continue
            label_set = record["labels"].get(head.name)
            if label_set is None:
                continue
            if len(label_set) <= 1:
                continue
            conflict = DuplicateConflict(
                sha=sha,
                head_name=head.name,
                conflicting_classes=sorted(label_set),
                sample_original_filename=record["original_filename"],
            )
            if duplicate_policy == "FAIL":
                raise DuplicateConflictError(conflict)
            # SKIP
            skipped_shas.add(sha)
            skipped_conflicts.append(conflict)
            break  # 같은 이미지를 여러 head에서 중복 리포트할 필요 없음

    # 3차 패스: 파일 복사 + manifest 기록.
    manifest_path = dest_root / "manifest.jsonl"
    head_class_counts: dict[str, list[int]] = {
        head.name: [0] * len(head.classes) for head in heads
    }
    class_index_lookup: dict[str, dict[str, int]] = {
        head.name: {class_name: idx for idx, class_name in enumerate(head.classes)}
        for head in heads
    }

    written_count = 0
    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        for sha, record in image_records.items():
            if sha in skipped_shas:
                continue
            dest_filename = f"{sha}{record['suffix']}"
            dest_image_path = images_dir / dest_filename
            if not dest_image_path.exists():
                shutil.copy2(record["source_abs_path"], dest_image_path)

            # head별 라벨을 정렬된 list로 직렬화 (다중 label 포함, 항상 list).
            labels_out: dict[str, list[str]] = {}
            for head in heads:
                label_set = record["labels"].get(head.name)
                if label_set is None:
                    # 해당 head에 대해 이 이미지는 라벨이 없음 — 빈 list로 기록
                    labels_out[head.name] = []
                    continue
                labels_sorted = sorted(label_set)
                labels_out[head.name] = labels_sorted
                for class_name in labels_sorted:
                    class_idx = class_index_lookup[head.name][class_name]
                    head_class_counts[head.name][class_idx] += 1

            manifest_entry = {
                "sha": sha,
                "filename": f"images/{dest_filename}",
                "original_filename": record["original_filename"],
                "labels": labels_out,
            }
            manifest_file.write(json.dumps(manifest_entry, ensure_ascii=False) + "\n")
            written_count += 1

    # head_schema.json 작성
    head_schema_path = dest_root / "head_schema.json"
    head_schema_path.write_text(
        json.dumps(_build_head_schema_json(heads), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return ClassificationIngestResult(
        image_count=written_count,
        head_class_counts=head_class_counts,
        manifest_relpath="manifest.jsonl",
        head_schema_relpath="head_schema.json",
        skipped_conflicts=skipped_conflicts,
    )
