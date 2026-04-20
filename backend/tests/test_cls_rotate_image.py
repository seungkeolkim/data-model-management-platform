"""
cls_rotate_image Manipulator 단위 테스트.

커버 영역:
  1. 각도별 기본 동작 (90 / 180 / 270) — file_name rename + width/height 처리
  2. head_schema / labels 보존 (None 포함)
  3. image_manipulation_specs 누적 (기존 spec 이 있으면 append)
  4. extra.source_storage_uri / original_file_name 최초 1회 기록
  5. merge 등으로 extra 가 이미 채워진 경우 덮어쓰지 않음
  6. deep copy 격리
  7. 기본값 (degrees 누락 시 180)
  8. 입력 검증 에러 (list, invalid degrees)
  9. build_image_manipulation 반환 스펙
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_rotate_image import (
    RotateImageClassification,
    _append_postfix_to_filename,
)
from lib.pipeline.pipeline_data_models import (
    DatasetMeta,
    HeadSchema,
    ImageManipulationSpec,
    ImageRecord,
)


# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    file_name: str,
    labels: dict[str, list[str] | None] | None = None,
    width: int | None = 640,
    height: int | None = 480,
    extra: dict | None = None,
) -> ImageRecord:
    return ImageRecord(
        image_id=1,
        file_name=file_name,
        width=width,
        height=height,
        labels=labels if labels is not None else {"vehicle": ["sedan"]},
        extra=extra if extra is not None else {},
    )


def _make_meta(
    records: list[ImageRecord],
    storage_uri: str = "processed/src/1.0",
) -> DatasetMeta:
    return DatasetMeta(
        dataset_id="test-ds",
        storage_uri=storage_uri,
        categories=[],
        image_records=records,
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
        ],
    )


_MANIPULATOR = RotateImageClassification()


# ─────────────────────────────────────────────────────────────────
# 1. 각도별 기본 동작
# ─────────────────────────────────────────────────────────────────


def test_rotate_180_preserves_dimensions() -> None:
    """180° 회전 — width/height 유지."""
    meta = _make_meta([_make_record("images/truck_001.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})

    record = result.image_records[0]
    assert record.width == 640
    assert record.height == 480
    assert record.file_name == "images/truck_001_rotated_180.jpg"


def test_rotate_90_swaps_dimensions() -> None:
    """90° 회전 — width/height 교환."""
    meta = _make_meta([_make_record("images/truck_001.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 90})

    record = result.image_records[0]
    assert record.width == 480
    assert record.height == 640
    assert record.file_name == "images/truck_001_rotated_90.jpg"


def test_rotate_270_swaps_dimensions() -> None:
    """270° 회전 — width/height 교환."""
    meta = _make_meta([_make_record("images/truck_001.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 270})

    record = result.image_records[0]
    assert record.width == 480
    assert record.height == 640
    assert record.file_name == "images/truck_001_rotated_270.jpg"


def test_rotate_90_without_dimensions() -> None:
    """width/height 가 None 이면 swap 로직을 건너뜀."""
    meta = _make_meta([_make_record("images/x.jpg", width=None, height=None)])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 90})

    record = result.image_records[0]
    assert record.width is None
    assert record.height is None
    assert record.file_name == "images/x_rotated_90.jpg"


# ─────────────────────────────────────────────────────────────────
# 2. head_schema / labels 보존
# ─────────────────────────────────────────────────────────────────


def test_head_schema_preserved() -> None:
    """회전은 head_schema 를 건드리지 않는다."""
    meta = _make_meta([_make_record("images/a.jpg")])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})

    assert result.head_schema == meta.head_schema


def test_labels_preserved_with_null() -> None:
    """null(unknown) labels 도 그대로 보존된다."""
    meta = _make_meta([
        _make_record("images/a.jpg", labels={"vehicle": None}),
        _make_record("images/b.jpg", labels={"vehicle": ["sedan"]}),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})

    assert result.image_records[0].labels == {"vehicle": None}
    assert result.image_records[1].labels == {"vehicle": ["sedan"]}


# ─────────────────────────────────────────────────────────────────
# 3. image_manipulation_specs 누적
# ─────────────────────────────────────────────────────────────────


def test_spec_pushed_to_extra() -> None:
    """extra.image_manipulation_specs 에 rotate spec 이 1건 쌓인다."""
    meta = _make_meta([_make_record("images/a.jpg")])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})

    specs = result.image_records[0].extra["image_manipulation_specs"]
    assert len(specs) == 1
    assert specs[0] == {"operation": "rotate_image", "params": {"degrees": 180}}


def test_spec_appends_to_existing() -> None:
    """이미 다른 변환 spec 이 있으면 뒤에 append 한다."""
    prior_spec = {"operation": "crop_image", "params": {"top_pct": 10}}
    meta = _make_meta([
        _make_record(
            "images/a.jpg",
            extra={"image_manipulation_specs": [prior_spec]},
        ),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 90})

    specs = result.image_records[0].extra["image_manipulation_specs"]
    assert len(specs) == 2
    assert specs[0] == prior_spec
    assert specs[1]["operation"] == "rotate_image"
    assert specs[1]["params"] == {"degrees": 90}


# ─────────────────────────────────────────────────────────────────
# 4. extra.source_storage_uri / original_file_name 최초 기록
# ─────────────────────────────────────────────────────────────────


def test_extra_source_tracking_initialized() -> None:
    """최초 변형 시 source_storage_uri 와 original_file_name 을 기록."""
    meta = _make_meta(
        [_make_record("images/truck_001.jpg")],
        storage_uri="source/A/1.0",
    )

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})

    record = result.image_records[0]
    assert record.extra["source_storage_uri"] == "source/A/1.0"
    # original_file_name 은 rename 이전의 파일명이어야 한다.
    assert record.extra["original_file_name"] == "images/truck_001.jpg"


# ─────────────────────────────────────────────────────────────────
# 5. 기존 extra 보존 (merge 경로 시나리오)
# ─────────────────────────────────────────────────────────────────


def test_existing_extra_is_preserved() -> None:
    """merge 등으로 extra 가 이미 채워진 경우, rotate 가 덮어쓰지 않는다."""
    prior_extra = {
        "source_storage_uri": "source/A/1.0",
        "original_file_name": "images/truck_001.jpg",
    }
    meta = _make_meta(
        [_make_record("images/A_abcd_truck_001.jpg", extra=prior_extra)],
        storage_uri="fusion/merged/1.0",   # 현재 dataset (merge 결과)
    )

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})

    record = result.image_records[0]
    # 원본 추적 체인을 끊지 않기 위해 보존되어야 한다.
    assert record.extra["source_storage_uri"] == "source/A/1.0"
    assert record.extra["original_file_name"] == "images/truck_001.jpg"
    # file_name 은 rename 된 결과.
    assert record.file_name == "images/A_abcd_truck_001_rotated_180.jpg"


# ─────────────────────────────────────────────────────────────────
# 6. deep copy 격리
# ─────────────────────────────────────────────────────────────────


def test_deep_copy_isolation() -> None:
    """결과 수정이 원본 meta 에 영향 주지 않는다."""
    meta = _make_meta([_make_record("images/a.jpg")])
    original_file_name = meta.image_records[0].file_name

    result = _MANIPULATOR.transform_annotation(meta, {"degrees": 180})
    result.image_records[0].file_name = "MUTATED"

    assert meta.image_records[0].file_name == original_file_name


# ─────────────────────────────────────────────────────────────────
# 7. 기본값
# ─────────────────────────────────────────────────────────────────


def test_default_degrees_is_180() -> None:
    """degrees 파라미터를 생략하면 180° 로 처리."""
    meta = _make_meta([_make_record("images/a.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(meta, {})

    record = result.image_records[0]
    assert record.file_name == "images/a_rotated_180.jpg"
    assert record.width == 640
    assert record.height == 480


# ─────────────────────────────────────────────────────────────────
# 8. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_list_input() -> None:
    """list 입력은 TypeError."""
    meta = _make_meta([_make_record("images/a.jpg")])
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation([meta], {"degrees": 180})


@pytest.mark.parametrize("bad_degrees", [0, 45, 360, -90, 181])
def test_error_invalid_degrees(bad_degrees: int) -> None:
    """VALID_DEGREES 밖의 각도는 ValueError."""
    meta = _make_meta([_make_record("images/a.jpg")])
    with pytest.raises(ValueError, match="degrees"):
        _MANIPULATOR.transform_annotation(meta, {"degrees": bad_degrees})


# ─────────────────────────────────────────────────────────────────
# 9. build_image_manipulation
# ─────────────────────────────────────────────────────────────────


def test_build_image_manipulation_returns_rotate_spec() -> None:
    """build_image_manipulation 은 rotate_image spec 을 반환한다."""
    record = _make_record("images/a.jpg")

    specs = _MANIPULATOR.build_image_manipulation(record, {"degrees": 270})

    assert specs == [
        ImageManipulationSpec(operation="rotate_image", params={"degrees": 270})
    ]


def test_build_image_manipulation_default_180() -> None:
    """build_image_manipulation 도 degrees 기본 180."""
    record = _make_record("images/a.jpg")

    specs = _MANIPULATOR.build_image_manipulation(record, {})

    assert specs[0].params == {"degrees": 180}


# ─────────────────────────────────────────────────────────────────
# 10. _append_postfix_to_filename 헬퍼 단위
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "file_name,postfix,expected",
    [
        ("images/truck_001.jpg", "_rotated_180", "images/truck_001_rotated_180.jpg"),
        ("truck_001.jpg", "_rotated_90", "truck_001_rotated_90.jpg"),
        ("a.png", "_x", "a_x.png"),
        ("noext", "_y", "noext_y"),
        ("images/deep/nested/a.jpg", "_rotated_270", "images/deep/nested/a_rotated_270.jpg"),
    ],
)
def test_append_postfix_to_filename(file_name: str, postfix: str, expected: str) -> None:
    assert _append_postfix_to_filename(file_name, postfix) == expected
