"""
cls_crop_image Manipulator 단위 테스트.

커버 영역:
  1. 방향별 기본 동작 — file_name rename + height 축소
  2. head_schema / labels 보존 (None 포함)
  3. image_manipulation_specs 누적 (기존 spec 이 있으면 append)
  4. extra.source_storage_uri / original_file_name 최초 1회 기록
  5. merge 등으로 extra 가 이미 채워진 경우 덮어쓰지 않음
  6. deep copy 격리
  7. 기본값 (direction=상단, crop_pct=30)
  8. 입력 검증 에러 (list, invalid direction, invalid crop_pct)
  9. build_image_manipulation 반환 스펙
 10. _append_postfix_to_filename 헬퍼 단위
 11. direction 파싱 (Korean + English 양쪽 허용)
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_crop_image import (
    CropImageClassification,
    _append_postfix_to_filename,
    _parse_crop_pct,
    _parse_direction,
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


_MANIPULATOR = CropImageClassification()


# ─────────────────────────────────────────────────────────────────
# 1. 방향별 기본 동작
# ─────────────────────────────────────────────────────────────────


def test_crop_up_30_reduces_height_and_renames() -> None:
    """상단 30% crop — height 는 70% 로, file_name 은 postfix 추가."""
    meta = _make_meta([_make_record("images/truck_001.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )

    record = result.image_records[0]
    assert record.width == 640
    assert record.height == 336  # int(480 * 0.7)
    assert record.file_name == "images/truck_001_crop_up_030.jpg"


def test_crop_down_50_reduces_height_and_renames() -> None:
    """하단 50% crop — height 는 50% 로, postfix 는 _crop_down_050."""
    meta = _make_meta([_make_record("images/truck_002.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "하단", "crop_pct": 50}
    )

    record = result.image_records[0]
    assert record.width == 640
    assert record.height == 240
    assert record.file_name == "images/truck_002_crop_down_050.jpg"


def test_crop_postfix_zero_pads_to_three_digits() -> None:
    """crop_pct 가 한 자리/두 자리여도 postfix 는 항상 3자리 zero-pad."""
    meta = _make_meta([
        _make_record("images/a.jpg"),
        _make_record("images/b.jpg"),
    ])

    result_1 = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 5}
    )
    assert result_1.image_records[0].file_name == "images/a_crop_up_005.jpg"

    result_2 = _MANIPULATOR.transform_annotation(
        meta, {"direction": "하단", "crop_pct": 99}
    )
    assert result_2.image_records[1].file_name == "images/b_crop_down_099.jpg"


def test_crop_without_height() -> None:
    """height 가 None 이면 축소 계산을 건너뛴다 (file_name 은 rename)."""
    meta = _make_meta([_make_record("images/x.jpg", width=None, height=None)])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )

    record = result.image_records[0]
    assert record.width is None
    assert record.height is None
    assert record.file_name == "images/x_crop_up_030.jpg"


def test_crop_small_image_keeps_at_least_one_pixel() -> None:
    """아주 작은 height 에서도 결과 height ≥ 1 보장."""
    meta = _make_meta([_make_record("images/tiny.jpg", width=10, height=3)])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 99}
    )

    record = result.image_records[0]
    assert record.height >= 1


# ─────────────────────────────────────────────────────────────────
# 2. head_schema / labels 보존
# ─────────────────────────────────────────────────────────────────


def test_head_schema_preserved() -> None:
    """crop 은 head_schema 를 건드리지 않는다."""
    meta = _make_meta([_make_record("images/a.jpg")])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )

    assert result.head_schema == meta.head_schema


def test_labels_preserved_with_null() -> None:
    """null(unknown) labels 도 그대로 보존된다."""
    meta = _make_meta([
        _make_record("images/a.jpg", labels={"vehicle": None}),
        _make_record("images/b.jpg", labels={"vehicle": ["sedan"]}),
    ])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "하단", "crop_pct": 10}
    )

    assert result.image_records[0].labels == {"vehicle": None}
    assert result.image_records[1].labels == {"vehicle": ["sedan"]}


# ─────────────────────────────────────────────────────────────────
# 3. image_manipulation_specs 누적
# ─────────────────────────────────────────────────────────────────


def test_spec_pushed_to_extra() -> None:
    """extra.image_manipulation_specs 에 crop spec 이 1건 쌓인다."""
    meta = _make_meta([_make_record("images/a.jpg")])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )

    specs = result.image_records[0].extra["image_manipulation_specs"]
    assert len(specs) == 1
    assert specs[0] == {
        "operation": "crop_image_vertical",
        "params": {"direction": "up", "crop_pct": 30},
    }


def test_spec_appends_to_existing() -> None:
    """이미 다른 변환 spec 이 있으면 뒤에 append 한다."""
    prior_spec = {"operation": "rotate_image", "params": {"degrees": 90}}
    meta = _make_meta([
        _make_record(
            "images/a.jpg",
            extra={"image_manipulation_specs": [prior_spec]},
        ),
    ])

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "하단", "crop_pct": 20}
    )

    specs = result.image_records[0].extra["image_manipulation_specs"]
    assert len(specs) == 2
    assert specs[0] == prior_spec
    assert specs[1]["operation"] == "crop_image_vertical"
    assert specs[1]["params"] == {"direction": "down", "crop_pct": 20}


# ─────────────────────────────────────────────────────────────────
# 4. extra.source_storage_uri / original_file_name 최초 기록
# ─────────────────────────────────────────────────────────────────


def test_extra_source_tracking_initialized() -> None:
    """최초 변형 시 source_storage_uri 와 original_file_name 을 기록."""
    meta = _make_meta(
        [_make_record("images/truck_001.jpg")],
        storage_uri="source/A/1.0",
    )

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )

    record = result.image_records[0]
    assert record.extra["source_storage_uri"] == "source/A/1.0"
    # original_file_name 은 rename 이전의 파일명이어야 한다.
    assert record.extra["original_file_name"] == "images/truck_001.jpg"


# ─────────────────────────────────────────────────────────────────
# 5. 기존 extra 보존 (merge 경로 시나리오)
# ─────────────────────────────────────────────────────────────────


def test_existing_extra_is_preserved() -> None:
    """merge 등으로 extra 가 이미 채워진 경우, crop 이 덮어쓰지 않는다."""
    prior_extra = {
        "source_storage_uri": "source/A/1.0",
        "original_file_name": "images/truck_001.jpg",
    }
    meta = _make_meta(
        [_make_record("images/A_abcd_truck_001.jpg", extra=prior_extra)],
        storage_uri="fusion/merged/1.0",   # 현재 dataset (merge 결과)
    )

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )

    record = result.image_records[0]
    assert record.extra["source_storage_uri"] == "source/A/1.0"
    assert record.extra["original_file_name"] == "images/truck_001.jpg"
    # file_name 은 rename 된 결과.
    assert record.file_name == "images/A_abcd_truck_001_crop_up_030.jpg"


# ─────────────────────────────────────────────────────────────────
# 6. deep copy 격리
# ─────────────────────────────────────────────────────────────────


def test_deep_copy_isolation() -> None:
    """결과 수정이 원본 meta 에 영향 주지 않는다."""
    meta = _make_meta([_make_record("images/a.jpg")])
    original_file_name = meta.image_records[0].file_name
    original_height = meta.image_records[0].height

    result = _MANIPULATOR.transform_annotation(
        meta, {"direction": "상단", "crop_pct": 30}
    )
    result.image_records[0].file_name = "MUTATED"

    assert meta.image_records[0].file_name == original_file_name
    assert meta.image_records[0].height == original_height


# ─────────────────────────────────────────────────────────────────
# 7. 기본값
# ─────────────────────────────────────────────────────────────────


def test_defaults_direction_up_crop_pct_30() -> None:
    """direction / crop_pct 둘 다 생략하면 상단 30% 로 처리."""
    meta = _make_meta([_make_record("images/a.jpg", width=640, height=480)])

    result = _MANIPULATOR.transform_annotation(meta, {})

    record = result.image_records[0]
    assert record.file_name == "images/a_crop_up_030.jpg"
    assert record.height == 336


# ─────────────────────────────────────────────────────────────────
# 8. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_list_input() -> None:
    """list 입력은 TypeError."""
    meta = _make_meta([_make_record("images/a.jpg")])
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation(
            [meta], {"direction": "상단", "crop_pct": 30}
        )


@pytest.mark.parametrize("bad_direction", ["좌측", "top", "", "   ", "bottom", 123, None])
def test_error_invalid_direction(bad_direction) -> None:
    """허용 외 direction 값은 ValueError."""
    meta = _make_meta([_make_record("images/a.jpg")])
    with pytest.raises(ValueError, match="direction"):
        _MANIPULATOR.transform_annotation(
            meta, {"direction": bad_direction, "crop_pct": 30}
        )


@pytest.mark.parametrize("bad_pct", [0, 100, -5, 150, 30.5, True, False])
def test_error_invalid_crop_pct(bad_pct) -> None:
    """허용 외 crop_pct 값은 ValueError."""
    meta = _make_meta([_make_record("images/a.jpg")])
    with pytest.raises(ValueError, match="crop_pct"):
        _MANIPULATOR.transform_annotation(
            meta, {"direction": "상단", "crop_pct": bad_pct}
        )


# ─────────────────────────────────────────────────────────────────
# 9. build_image_manipulation
# ─────────────────────────────────────────────────────────────────


def test_build_image_manipulation_returns_crop_spec() -> None:
    """build_image_manipulation 은 crop_image_vertical spec 을 반환한다."""
    record = _make_record("images/a.jpg")

    specs = _MANIPULATOR.build_image_manipulation(
        record, {"direction": "하단", "crop_pct": 25}
    )

    assert specs == [
        ImageManipulationSpec(
            operation="crop_image_vertical",
            params={"direction": "down", "crop_pct": 25},
        )
    ]


def test_build_image_manipulation_defaults() -> None:
    """params 누락 시 direction=up, crop_pct=30."""
    record = _make_record("images/a.jpg")

    specs = _MANIPULATOR.build_image_manipulation(record, {})

    assert specs[0].params == {"direction": "up", "crop_pct": 30}


# ─────────────────────────────────────────────────────────────────
# 10. _append_postfix_to_filename 헬퍼 단위
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "file_name,postfix,expected",
    [
        ("images/truck_001.jpg", "_crop_up_030", "images/truck_001_crop_up_030.jpg"),
        ("truck_001.jpg", "_crop_down_050", "truck_001_crop_down_050.jpg"),
        ("a.png", "_crop_up_010", "a_crop_up_010.png"),
        ("noext", "_crop_up_030", "noext_crop_up_030"),
        ("images/deep/nested/a.jpg", "_crop_down_099", "images/deep/nested/a_crop_down_099.jpg"),
    ],
)
def test_append_postfix_to_filename(file_name: str, postfix: str, expected: str) -> None:
    assert _append_postfix_to_filename(file_name, postfix) == expected


# ─────────────────────────────────────────────────────────────────
# 11. _parse_direction / _parse_crop_pct 파싱 단위
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("상단", "up"),
        ("하단", "down"),
        ("up", "up"),
        ("down", "down"),
        ("  상단  ", "up"),
    ],
)
def test_parse_direction_accepts_both_languages(raw: str, expected: str) -> None:
    assert _parse_direction(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (30, 30),
        (1, 1),
        (99, 99),
        (30.0, 30),
        ("45", 45),
    ],
)
def test_parse_crop_pct_accepts_int_like(raw, expected: int) -> None:
    assert _parse_crop_pct(raw) == expected
