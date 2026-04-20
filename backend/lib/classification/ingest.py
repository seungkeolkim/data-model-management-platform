"""
Classification 폴더 구조 → 단일 풀 + manifest.jsonl 정규화 ingest.

입력:
    heads = [ClassificationHeadInput(name, multi_label, classes, source_class_paths), ...]
    이 구조는 Pydantic 스키마 ClassificationHeadSpec과 동일한 형태이지만,
    lib/ 는 app/schemas 에 의존하지 않으므로 간단한 dataclass로 재정의한다.

출력 디렉토리 구조 (dest_root 하위):
    images/{original_filename}   # 이미지 identity = filename. 이름이 같으면 같은 이미지로 간주.
    manifest.jsonl               # 이미지 1장당 1줄
    head_schema.json             # 그룹 head_schema 복사본

Manifest 한 줄 스키마 (§2-12 확정: null=unknown, []=explicit empty):
    {
      "filename": "images/img_0001.jpg",
      "original_filename": "img_0001.jpg",
      "labels": {"hardhat_wear": ["helmet"], "visibility": null}
    }

이미지 identity = filename (파일명 기반):
    - 같은 파일명이 여러 (head, class) 폴더에 등장 = 같은 이미지 → multi-head 라벨로 통합.
    - 단, single-label head 에서 같은 파일명이 2개 이상 class 에 등장 = 사용자 라벨링 오류 →
      warning 로그 + 해당 이미지 전체 skip (모든 head 에서 제외, pool 에도 저장 안 함).
    - 같은 파일명이지만 내용이 다른 경우는 감지할 수 없으며 (SHA 기반 content identity 는 폐지),
      첫 발견 파일 하나만 pool 에 저장된다.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

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
class FilenameCollision:
    """
    Single-label head 에서 같은 파일명이 2개 이상 class 에 등장한 케이스.

    이는 사용자의 라벨링 오류(동일 이미지를 서로 다른 class 로 분류)이므로,
    ingest 는 해당 이미지를 모든 head 에서 제외하고 skip 한다.
    """
    filename: str
    head_name: str
    conflicting_classes: list[str]   # 정렬된 class 이름
    source_abs_paths: list[str]      # 충돌이 발생한 각 class 폴더의 이미지 절대경로


@dataclass
class ClassificationIngestResult:
    """ingest 완료 후 요약."""
    image_count: int
    head_class_counts: dict[str, list[int]]              # head_name → class 순서별 이미지 수
    manifest_relpath: str                                 # "manifest.jsonl"
    head_schema_relpath: str                              # "head_schema.json"
    skipped_collisions: list[FilenameCollision] = field(default_factory=list)


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
    allowed_extensions: set[str] | None = None,
) -> ClassificationIngestResult:
    """
    Classification 데이터셋 ingest.

    dest_root는 이미 비어있거나 존재하지 않는 디렉토리여야 안전하다(신규 Dataset 저장 위치).
    이 함수는 dest_root를 필요 시 생성한다.

    Args:
        dest_root: 최종 저장 루트 절대경로. 아래에 images/, manifest.jsonl, head_schema.json 작성.
        heads: head별 (name, multi_label, classes, source_class_paths).
        allowed_extensions: 허용 이미지 확장자. None이면 DEFAULT_IMAGE_EXTENSIONS.

    Returns:
        ClassificationIngestResult
    """
    extensions = allowed_extensions if allowed_extensions is not None else DEFAULT_IMAGE_EXTENSIONS

    dest_root.mkdir(parents=True, exist_ok=True)
    images_dir = dest_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 1차 패스: 모든 (head, class, file) 조합을 filename 기준으로 수집한다.
    # file_records[filename] = {
    #   "first_seen_abs_path": Path,                          # pool 저장 대상 (첫 발견 파일)
    #   "occurrences_by_head": {
    #        head_name: {class_name: source_abs_path, ...},
    #        ...
    #   }
    # }
    # 같은 (head, class) 폴더에 같은 파일명이 있을 수는 없다(파일시스템 제약).
    file_records: dict[str, dict] = {}

    for head in heads:
        for class_index, class_name in enumerate(head.classes):
            class_dir = Path(head.source_class_paths[class_index])
            for image_path in _iter_images_in_class_dir(class_dir, extensions):
                filename = image_path.name
                record = file_records.get(filename)
                if record is None:
                    record = {
                        "first_seen_abs_path": image_path,
                        "occurrences_by_head": {},
                    }
                    file_records[filename] = record
                head_buckets = record["occurrences_by_head"].setdefault(head.name, {})
                head_buckets[class_name] = str(image_path)

    # 2차 패스: single-label head 에서 filename 충돌 감지 → skip 대상 확정.
    # 충돌은 사용자의 라벨링 오류이며 detection 경로와 동일하게 warning + skip 처리한다.
    skipped_filenames: set[str] = set()
    skipped_collisions: list[FilenameCollision] = []

    single_label_head_lookup = {head.name: head for head in heads if not head.multi_label}

    for filename, record in file_records.items():
        for head_name, class_to_abs_path in record["occurrences_by_head"].items():
            if head_name not in single_label_head_lookup:
                continue
            if len(class_to_abs_path) <= 1:
                continue
            conflicting_classes = sorted(class_to_abs_path.keys())
            collision = FilenameCollision(
                filename=filename,
                head_name=head_name,
                conflicting_classes=conflicting_classes,
                source_abs_paths=[class_to_abs_path[cn] for cn in conflicting_classes],
            )
            skipped_collisions.append(collision)
            skipped_filenames.add(filename)
            logger.warning(
                "classification ingest: filename 충돌로 이미지 skip — "
                "filename=%s, head=%s, classes=%s, paths=%s",
                filename,
                head_name,
                conflicting_classes,
                collision.source_abs_paths,
            )
            # 같은 파일명이 여러 head 에서 동시에 충돌할 수 있으나, skip 판정은 한 번이면 충분하다.
            break

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
        for filename, record in file_records.items():
            if filename in skipped_filenames:
                continue

            dest_image_path = images_dir / filename
            if not dest_image_path.exists():
                shutil.copy2(record["first_seen_abs_path"], dest_image_path)

            # head별 라벨 직렬화 — 어떤 head 에도 속하지 않은 이미지는 null(unknown). §2-12.
            labels_out: dict[str, list[str] | None] = {head.name: None for head in heads}
            for head in heads:
                head_buckets = record["occurrences_by_head"].get(head.name)
                if not head_buckets:
                    # labels_out[head.name] = None 유지 (unknown)
                    continue
                labels_sorted = sorted(head_buckets.keys())
                labels_out[head.name] = labels_sorted
                for class_name in labels_sorted:
                    class_idx = class_index_lookup[head.name][class_name]
                    head_class_counts[head.name][class_idx] += 1

            manifest_entry = {
                "filename": f"images/{filename}",
                "original_filename": filename,
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
        skipped_collisions=skipped_collisions,
    )
