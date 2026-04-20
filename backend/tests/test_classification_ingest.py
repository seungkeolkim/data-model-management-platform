"""
lib.classification.ingest.ingest_classification 회귀 테스트.

정책 참조: `objective_n_plan_7th.md §2-8 (filename identity)` + §2-12.

이미지 identity = filename (SHA 기반 content dedup 폐지).
  - 같은 파일명이 여러 (head, class) 폴더에 등장 = 같은 이미지 → multi-head 라벨로 통합.
  - single-label head 에서 같은 파일명이 2개 이상 class 에 등장 = 사용자 라벨링 오류 →
    warning 로그 + 해당 이미지 전체 skip (모든 head 에서 제외, pool 에도 저장 안 함).

커버 영역:
  1. 행복 경로 — 단일 single-label head, class 별로 서로 다른 파일명이면 전부 기록된다.
  2. multi-head 통합 — 같은 파일명이 head A 와 head B 양쪽에 있으면 labels 가 합쳐진다.
  3. multi-label OR 병합 — multi-label head 에서 같은 파일명이 class1, class2 양쪽에 있으면 둘 다 기록.
  4. single-label 충돌 → skip (manifest 미기록, head_class_counts 미반영, skipped_collisions 에 기록).
  5. null(unknown) — 한쪽 head 에만 나타나는 이미지의 다른 head 값은 null.
"""
from __future__ import annotations

import json
from pathlib import Path

from lib.classification.ingest import (
    ClassificationHeadInput,
    ingest_classification,
)


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_image_file(path: Path, content: bytes = b"fakejpegbytes") -> None:
    """class 폴더 안에 가짜 이미지 파일 1개 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read_manifest(dest_root: Path) -> list[dict]:
    """manifest.jsonl 을 dict 리스트로 읽어 반환."""
    manifest_path = dest_root / "manifest.jsonl"
    return [json.loads(line) for line in manifest_path.read_text().splitlines() if line]


# ─────────────────────────────────────────────────────────────────
# 1. 행복 경로
# ─────────────────────────────────────────────────────────────────


def test_happy_path_single_head_two_classes(tmp_path: Path) -> None:
    """single-label head 1개, class 폴더 2개, 서로 다른 파일명 → 정상 기록."""
    source_root = tmp_path / "src"
    dest_root = tmp_path / "dest"

    _make_image_file(source_root / "helmet" / "a.jpg")
    _make_image_file(source_root / "no_helmet" / "b.jpg")

    head = ClassificationHeadInput(
        name="hardhat",
        multi_label=False,
        classes=["helmet", "no_helmet"],
        source_class_paths=[
            str(source_root / "helmet"),
            str(source_root / "no_helmet"),
        ],
    )

    result = ingest_classification(dest_root=dest_root, heads=[head])

    assert result.image_count == 2
    assert result.skipped_collisions == []
    assert result.head_class_counts == {"hardhat": [1, 1]}

    manifest = _read_manifest(dest_root)
    by_filename = {entry["filename"]: entry for entry in manifest}
    assert by_filename["images/a.jpg"]["labels"] == {"hardhat": ["helmet"]}
    assert by_filename["images/b.jpg"]["labels"] == {"hardhat": ["no_helmet"]}

    # 실제 이미지 복사 검증
    assert (dest_root / "images" / "a.jpg").exists()
    assert (dest_root / "images" / "b.jpg").exists()


# ─────────────────────────────────────────────────────────────────
# 2. multi-head 통합
# ─────────────────────────────────────────────────────────────────


def test_same_filename_across_different_heads_merges_labels(tmp_path: Path) -> None:
    """같은 파일명이 head A 와 head B 각각의 class 폴더에 있으면 labels 가 통합된다."""
    source_root = tmp_path / "src"
    dest_root = tmp_path / "dest"

    # shared.jpg 가 두 head 각각의 한 class 에만 존재 (동일 head 내 충돌 아님)
    _make_image_file(source_root / "head_a" / "helmet" / "shared.jpg")
    _make_image_file(source_root / "head_b" / "seen" / "shared.jpg")

    head_a = ClassificationHeadInput(
        name="hardhat",
        multi_label=False,
        classes=["helmet", "no_helmet"],
        source_class_paths=[
            str(source_root / "head_a" / "helmet"),
            str(source_root / "head_a" / "no_helmet"),
        ],
    )
    head_b = ClassificationHeadInput(
        name="visibility",
        multi_label=False,
        classes=["seen", "unseen"],
        source_class_paths=[
            str(source_root / "head_b" / "seen"),
            str(source_root / "head_b" / "unseen"),
        ],
    )

    result = ingest_classification(dest_root=dest_root, heads=[head_a, head_b])

    assert result.image_count == 1
    assert result.skipped_collisions == []

    manifest = _read_manifest(dest_root)
    assert len(manifest) == 1
    labels = manifest[0]["labels"]
    assert labels == {"hardhat": ["helmet"], "visibility": ["seen"]}


# ─────────────────────────────────────────────────────────────────
# 3. multi-label OR 병합
# ─────────────────────────────────────────────────────────────────


def test_multi_label_head_same_filename_merges_classes(tmp_path: Path) -> None:
    """multi-label head 에서 같은 파일명이 두 class 에 있으면 둘 다 labels 에 들어간다."""
    source_root = tmp_path / "src"
    dest_root = tmp_path / "dest"

    _make_image_file(source_root / "hat" / "item.jpg")
    _make_image_file(source_root / "glasses" / "item.jpg")

    head = ClassificationHeadInput(
        name="attrs",
        multi_label=True,
        classes=["hat", "glasses", "scarf"],
        source_class_paths=[
            str(source_root / "hat"),
            str(source_root / "glasses"),
            str(source_root / "scarf"),
        ],
    )

    result = ingest_classification(dest_root=dest_root, heads=[head])

    assert result.image_count == 1
    assert result.skipped_collisions == []
    # head_class_counts: item.jpg 가 hat(0) 와 glasses(1) 양쪽에 반영
    assert result.head_class_counts == {"attrs": [1, 1, 0]}

    manifest = _read_manifest(dest_root)
    assert len(manifest) == 1
    assert sorted(manifest[0]["labels"]["attrs"]) == ["glasses", "hat"]


# ─────────────────────────────────────────────────────────────────
# 4. single-label 충돌 → skip
# ─────────────────────────────────────────────────────────────────


def test_single_label_filename_collision_skips_image(tmp_path: Path) -> None:
    """single-label head 에서 같은 파일명이 2개 class 에 존재하면 skip + skipped_collisions 에 기록."""
    source_root = tmp_path / "src"
    dest_root = tmp_path / "dest"

    _make_image_file(source_root / "helmet" / "dup.jpg")
    _make_image_file(source_root / "no_helmet" / "dup.jpg")
    # 충돌 없는 정상 이미지도 하나 추가해, skip 된 것 외에는 정상 처리되는지 확인.
    _make_image_file(source_root / "helmet" / "clean.jpg")

    head = ClassificationHeadInput(
        name="hardhat",
        multi_label=False,
        classes=["helmet", "no_helmet"],
        source_class_paths=[
            str(source_root / "helmet"),
            str(source_root / "no_helmet"),
        ],
    )

    result = ingest_classification(dest_root=dest_root, heads=[head])

    # clean.jpg 1장만 기록되고 dup.jpg 는 skip.
    assert result.image_count == 1
    assert result.head_class_counts == {"hardhat": [1, 0]}

    # skipped_collisions 검증.
    assert len(result.skipped_collisions) == 1
    collision = result.skipped_collisions[0]
    assert collision.filename == "dup.jpg"
    assert collision.head_name == "hardhat"
    assert collision.conflicting_classes == ["helmet", "no_helmet"]
    assert len(collision.source_abs_paths) == 2

    # manifest 에는 dup.jpg 가 없어야 한다.
    manifest = _read_manifest(dest_root)
    assert [entry["filename"] for entry in manifest] == ["images/clean.jpg"]

    # 이미지 풀에도 dup.jpg 가 복사되지 않아야 한다 (skip 대상).
    assert not (dest_root / "images" / "dup.jpg").exists()
    assert (dest_root / "images" / "clean.jpg").exists()


# ─────────────────────────────────────────────────────────────────
# 5. null(unknown) — 한쪽 head 에만 등장한 이미지
# ─────────────────────────────────────────────────────────────────


def test_image_only_in_one_head_has_null_for_other_head(tmp_path: Path) -> None:
    """head A 에만 등장한 이미지는 head B 에 대해 labels[B] = null(unknown)."""
    source_root = tmp_path / "src"
    dest_root = tmp_path / "dest"

    # only_in_a.jpg 는 head_a 에만 존재, head_b 는 비어있다.
    _make_image_file(source_root / "helmet" / "only_in_a.jpg")

    head_a = ClassificationHeadInput(
        name="hardhat",
        multi_label=False,
        classes=["helmet", "no_helmet"],
        source_class_paths=[
            str(source_root / "helmet"),
            str(source_root / "no_helmet"),
        ],
    )
    head_b = ClassificationHeadInput(
        name="visibility",
        multi_label=False,
        classes=["seen", "unseen"],
        source_class_paths=[
            str(source_root / "seen"),
            str(source_root / "unseen"),
        ],
    )

    result = ingest_classification(dest_root=dest_root, heads=[head_a, head_b])

    assert result.image_count == 1
    manifest = _read_manifest(dest_root)
    labels = manifest[0]["labels"]
    assert labels["hardhat"] == ["helmet"]
    # head_b 에는 아예 등장하지 않았으므로 unknown(null).
    assert labels["visibility"] is None
