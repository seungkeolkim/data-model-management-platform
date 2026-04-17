"""
cls_sample_n_images Manipulator 단위 테스트.

커버 영역:
  1. 기본 샘플링 — N장 추출, 나머지 제거
  2. 총 이미지 수 <= N → 전체 유지
  3. seed 고정 시 재현성 보장
  4. head_schema 변경 없음
  5. null(unknown) labels 보존
  6. 입력 검증 에러
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_sample_n_images import SampleNImagesClassification
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord


# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    sha: str,
    labels: dict[str, list[str] | None],
) -> ImageRecord:
    return ImageRecord(
        image_id=1,
        file_name=f"images/{sha}.jpg",
        width=640,
        height=480,
        sha=sha,
        labels=labels,
    )


def _make_meta(
    head_schema: list[HeadSchema],
    records: list[ImageRecord],
) -> DatasetMeta:
    return DatasetMeta(
        dataset_id="test-ds",
        storage_uri="/fake/test-ds",
        categories=[],
        image_records=records,
        head_schema=head_schema,
    )


_MANIPULATOR = SampleNImagesClassification()

_HEAD_SCHEMA = [
    HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
]


def _make_ten_records() -> list[ImageRecord]:
    """테스트용 10장 레코드 생성."""
    return [
        _make_record(f"sha{i:02d}", {"vehicle": ["sedan"] if i % 2 == 0 else ["truck"]})
        for i in range(10)
    ]


# ─────────────────────────────────────────────────────────────────
# 1. 기본 샘플링
# ─────────────────────────────────────────────────────────────────


def test_sample_basic() -> None:
    """10장에서 3장 추출 — 결과는 3장."""
    meta = _make_meta(_HEAD_SCHEMA, _make_ten_records())

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"n": 3, "seed": 42},
    )

    assert len(result.image_records) == 3


def test_sample_reduces_image_count() -> None:
    """샘플 후 이미지 수가 N 과 같다."""
    meta = _make_meta(_HEAD_SCHEMA, _make_ten_records())

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"n": 5, "seed": 0},
    )

    assert len(result.image_records) == 5


# ─────────────────────────────────────────────────────────────────
# 2. 총 이미지 수 <= N → 전체 유지
# ─────────────────────────────────────────────────────────────────


def test_sample_count_equal_to_total() -> None:
    """N == 총 이미지 수 → 전체 유지."""
    records = _make_ten_records()
    meta = _make_meta(_HEAD_SCHEMA, records)

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"n": 10, "seed": 42},
    )

    assert len(result.image_records) == 10


def test_sample_count_greater_than_total() -> None:
    """N > 총 이미지 수 → 전체 유지."""
    records = _make_ten_records()
    meta = _make_meta(_HEAD_SCHEMA, records)

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"n": 100, "seed": 42},
    )

    assert len(result.image_records) == 10


# ─────────────────────────────────────────────────────────────────
# 3. seed 재현성
# ─────────────────────────────────────────────────────────────────


def test_same_seed_same_result() -> None:
    """동일 seed → 동일 결과."""
    meta = _make_meta(_HEAD_SCHEMA, _make_ten_records())

    result_a = _MANIPULATOR.transform_annotation(meta, {"n": 3, "seed": 7})
    result_b = _MANIPULATOR.transform_annotation(meta, {"n": 3, "seed": 7})

    shas_a = [r.sha for r in result_a.image_records]
    shas_b = [r.sha for r in result_b.image_records]
    assert shas_a == shas_b


def test_different_seed_different_result() -> None:
    """다른 seed → (높은 확률로) 다른 결과."""
    meta = _make_meta(_HEAD_SCHEMA, _make_ten_records())

    result_a = _MANIPULATOR.transform_annotation(meta, {"n": 3, "seed": 1})
    result_b = _MANIPULATOR.transform_annotation(meta, {"n": 3, "seed": 999})

    shas_a = [r.sha for r in result_a.image_records]
    shas_b = [r.sha for r in result_b.image_records]
    # 10장 중 3장 — seed 가 다르면 거의 확실히 다른 결과
    assert shas_a != shas_b


# ─────────────────────────────────────────────────────────────────
# 4. head_schema 변경 없음
# ─────────────────────────────────────────────────────────────────


def test_head_schema_preserved() -> None:
    """샘플링 후 head_schema 는 원본과 동일."""
    meta = _make_meta(
        [
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
            HeadSchema(name="color", multi_label=True, classes=["red", "blue"]),
        ],
        _make_ten_records(),
    )

    result = _MANIPULATOR.transform_annotation(meta, {"n": 2, "seed": 42})

    assert len(result.head_schema) == 2
    assert result.head_schema[0].name == "vehicle"
    assert result.head_schema[0].classes == ["sedan", "truck"]
    assert result.head_schema[1].name == "color"
    assert result.head_schema[1].multi_label is True


# ─────────────────────────────────────────────────────────────────
# 5. null(unknown) labels 보존
# ─────────────────────────────────────────────────────────────────


def test_null_labels_preserved() -> None:
    """null(unknown) labels 가 샘플링 후에도 보존."""
    records = [
        _make_record("sha1", {"vehicle": None}),
        _make_record("sha2", {"vehicle": ["sedan"]}),
        _make_record("sha3", {"vehicle": None}),
    ]
    meta = _make_meta(_HEAD_SCHEMA, records)

    # N=3 → 전체 유지
    result = _MANIPULATOR.transform_annotation(meta, {"n": 3, "seed": 42})

    null_records = [r for r in result.image_records if r.labels["vehicle"] is None]
    assert len(null_records) == 2


# ─────────────────────────────────────────────────────────────────
# 6. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_list_input() -> None:
    """list 입력은 TypeError."""
    meta = _make_meta(_HEAD_SCHEMA, [])
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation(
            [meta],
            {"n": 1, "seed": 42},
        )


def test_error_n_less_than_one() -> None:
    """n < 1 이면 ValueError."""
    meta = _make_meta(_HEAD_SCHEMA, _make_ten_records())
    with pytest.raises(ValueError, match="1 미만"):
        _MANIPULATOR.transform_annotation(meta, {"n": 0, "seed": 42})


def test_error_no_head_schema() -> None:
    """head_schema 가 None 이면 ValueError."""
    meta = DatasetMeta(
        dataset_id="test",
        storage_uri="/fake",
        categories=["cat"],
        image_records=[],
    )
    with pytest.raises(ValueError, match="head_schema 가 None"):
        _MANIPULATOR.transform_annotation(meta, {"n": 1, "seed": 42})


def test_deep_copy_isolation() -> None:
    """샘플링 결과 수정이 원본에 영향을 주지 않는다."""
    records = _make_ten_records()
    meta = _make_meta(_HEAD_SCHEMA, records)

    result = _MANIPULATOR.transform_annotation(meta, {"n": 3, "seed": 42})
    result.image_records.clear()

    assert len(meta.image_records) == 10
