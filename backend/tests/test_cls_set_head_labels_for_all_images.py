"""
cls_set_head_labels_for_all_images Manipulator 단위 테스트.

커버 영역:
  1. set_unknown=True — 모든 이미지의 target head 가 null 로 교체, 다른 head 는 그대로.
     (classes 가 함께 들어와도 무시)
  2. set_unknown=False + classes — target head 만 교체, 다른 head 는 그대로.
  3. single-label head + classes 1개 → OK.
  4. multi-label head + classes 0/1/다개 → OK (빈 리스트 = explicit empty §2-12).
  5. 파싱 — textarea 줄바꿈, list, 공백 trim, set_unknown 문자열 수용.
  6. 검증 에러:
     - head_name 누락/공백
     - head_name 이 head_schema 에 없음
     - single-label head + 0개 or 2개+ classes
     - classes 에 head_schema 바깥 이름
     - classes 중복
     - list 입력 (TypeError)
     - detection DatasetMeta (head_schema None)
  7. 원본 meta 불변 / 이미지 바이너리 메타 보존.
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_set_head_labels_for_all_images import (
    SetHeadLabelsForAllImagesClassification,
)
from lib.pipeline.pipeline_data_models import (
    DatasetMeta,
    HeadSchema,
    ImageRecord,
)


# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    file_name: str,
    labels: dict[str, list[str] | None] | None,
    image_id: int = 1,
) -> ImageRecord:
    return ImageRecord(
        image_id=image_id,
        file_name=file_name,
        width=640,
        height=480,
        labels=labels,
        extra={},
    )


def _make_meta(
    records: list[ImageRecord],
    head_schema: list[HeadSchema] | None = None,
) -> DatasetMeta:
    return DatasetMeta(
        dataset_id="test-ds",
        storage_uri="processed/src/1.0",
        categories=[],
        image_records=records,
        head_schema=head_schema if head_schema is not None else [
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
        ],
    )


_MANIPULATOR = SetHeadLabelsForAllImagesClassification()


# ─────────────────────────────────────────────────────────────────
# 1. set_unknown=True — null 일괄 교체
# ─────────────────────────────────────────────────────────────────


def test_set_unknown_replaces_target_head_with_null() -> None:
    meta = _make_meta(
        [
            _make_record("images/a.jpg", labels={"vehicle": ["sedan"], "color": ["red"]}, image_id=1),
            _make_record("images/b.jpg", labels={"vehicle": ["truck"], "color": None}, image_id=2),
            _make_record("images/c.jpg", labels={"vehicle": None, "color": ["blue"]}, image_id=3),
        ],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
            HeadSchema(name="color", multi_label=False, classes=["red", "blue"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "set_unknown": True},
    )

    # vehicle 은 전부 null, color 는 원형 유지.
    assert result.image_records[0].labels == {"vehicle": None, "color": ["red"]}
    assert result.image_records[1].labels == {"vehicle": None, "color": None}
    assert result.image_records[2].labels == {"vehicle": None, "color": ["blue"]}


def test_set_unknown_ignores_classes_param() -> None:
    """set_unknown=True 면 classes 가 들어와도 무시 (unknown 이 우선)."""
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "set_unknown": True, "classes": "sedan"},
    )

    assert result.image_records[0].labels == {"vehicle": None}


# ─────────────────────────────────────────────────────────────────
# 2. set_unknown=False + classes — 지정 class 로 일괄 교체
# ─────────────────────────────────────────────────────────────────


def test_single_label_set_to_one_class() -> None:
    meta = _make_meta(
        [
            _make_record("images/a.jpg", labels={"vehicle": ["sedan"]}, image_id=1),
            _make_record("images/b.jpg", labels={"vehicle": None}, image_id=2),
            _make_record("images/c.jpg", labels={"vehicle": []}, image_id=3),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "set_unknown": False, "classes": "truck"},
    )

    for record in result.image_records:
        assert record.labels == {"vehicle": ["truck"]}


def test_multi_label_set_to_multiple_classes() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"tags": ["x"]})],
        head_schema=[
            HeadSchema(name="tags", multi_label=True, classes=["x", "y", "z"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "tags", "classes": "y\nz"},
    )

    assert result.image_records[0].labels == {"tags": ["y", "z"]}


def test_multi_label_set_to_empty_list_is_explicit_empty() -> None:
    """multi-label head 에 빈 classes → [] (explicit empty, §2-12)."""
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"tags": ["x", "y"]})],
        head_schema=[
            HeadSchema(name="tags", multi_label=True, classes=["x", "y", "z"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "tags", "classes": ""},
    )

    assert result.image_records[0].labels == {"tags": []}


def test_other_heads_preserved() -> None:
    """대상 head 외의 head labels 는 원형 유지."""
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"], "color": ["red", "blue"]})],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
            HeadSchema(name="color", multi_label=True, classes=["red", "blue"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "classes": "truck"},
    )

    assert result.image_records[0].labels == {
        "vehicle": ["truck"],
        "color": ["red", "blue"],
    }


def test_target_head_added_when_missing_in_source_labels() -> None:
    """
    원본 labels 에 target_head 키가 없어도(예: cls_add_head 직후 아직 전파 안된 경우)
    이번 단계에서 값이 채워진다.
    """
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
            HeadSchema(name="new_head", multi_label=False, classes=["a", "b"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "new_head", "set_unknown": True},
    )

    assert result.image_records[0].labels == {"vehicle": ["sedan"], "new_head": None}


# ─────────────────────────────────────────────────────────────────
# 3. head_schema 보존
# ─────────────────────────────────────────────────────────────────


def test_head_schema_unchanged() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"], "color": ["red"]})],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
            HeadSchema(name="color", multi_label=True, classes=["red", "blue"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "classes": "truck"},
    )

    assert result.head_schema is not None
    assert [h.name for h in result.head_schema] == ["vehicle", "color"]
    assert result.head_schema[0].multi_label is False
    assert result.head_schema[0].classes == ["sedan", "truck"]
    assert result.head_schema[1].multi_label is True
    assert result.head_schema[1].classes == ["red", "blue"]


# ─────────────────────────────────────────────────────────────────
# 4. 파싱
# ─────────────────────────────────────────────────────────────────


def test_classes_textarea_trim_and_filter_empty_lines() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"tags": ["x"]})],
        head_schema=[HeadSchema(name="tags", multi_label=True, classes=["x", "y", "z"])],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "tags", "classes": "  y  \n\n z \n"},
    )

    assert result.image_records[0].labels == {"tags": ["y", "z"]}


def test_classes_list_input() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"tags": ["x"]})],
        head_schema=[HeadSchema(name="tags", multi_label=True, classes=["x", "y", "z"])],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "tags", "classes": [" y ", "z", ""]},
    )

    assert result.image_records[0].labels == {"tags": ["y", "z"]}


@pytest.mark.parametrize("truthy", ["true", "True", "1", "yes", "on"])
def test_set_unknown_string_truthy(truthy: str) -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "set_unknown": truthy},
    )

    assert result.image_records[0].labels == {"vehicle": None}


@pytest.mark.parametrize("falsy", ["false", "False", "0", "no", "off", ""])
def test_set_unknown_string_falsy(falsy: str) -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "set_unknown": falsy, "classes": "truck"},
    )

    assert result.image_records[0].labels == {"vehicle": ["truck"]}


def test_set_unknown_default_false() -> None:
    """set_unknown 생략 시 False — classes 입력이 필요."""
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "classes": "truck"},
    )

    assert result.image_records[0].labels == {"vehicle": ["truck"]}


# ─────────────────────────────────────────────────────────────────
# 5. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_head_name_missing() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="head_name"):
        _MANIPULATOR.transform_annotation(meta, {"set_unknown": True})


def test_error_head_name_whitespace() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="공백"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "   ", "set_unknown": True},
        )


def test_error_head_name_not_in_schema() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="찾지 못했"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "nonexistent", "set_unknown": True},
        )


def test_error_single_label_with_multiple_classes() -> None:
    """single-label head 에 2개+ class → ValueError (writer assert 이전 차단)."""
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})],
        head_schema=[HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"])],
    )
    with pytest.raises(ValueError, match="single-label"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "vehicle", "classes": "sedan\ntruck"},
        )


def test_error_single_label_with_zero_classes() -> None:
    """single-label head + classes 비어있음 → ValueError (set_unknown 을 명시하라는 안내)."""
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})],
        head_schema=[HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"])],
    )
    with pytest.raises(ValueError, match="single-label"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "vehicle", "classes": ""},
        )


def test_error_class_not_in_head_schema() -> None:
    """head_schema.classes 바깥 이름 → ValueError."""
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})],
        head_schema=[HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"])],
    )
    with pytest.raises(ValueError, match="head_schema 에 없는"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "vehicle", "classes": "suv"},
        )


def test_error_classes_duplicate() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"tags": ["x"]})],
        head_schema=[HeadSchema(name="tags", multi_label=True, classes=["x", "y"])],
    )
    with pytest.raises(ValueError, match="중복"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "tags", "classes": "x\ny\nx"},
        )


def test_error_list_input() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation(
            [meta],
            {"head_name": "vehicle", "set_unknown": True},
        )


def test_error_detection_dataset() -> None:
    detection_meta = DatasetMeta(
        dataset_id="det-ds",
        storage_uri="raw/det/1.0",
        categories=["person", "car"],
        image_records=[],
        head_schema=None,
    )
    with pytest.raises(ValueError, match="classification"):
        _MANIPULATOR.transform_annotation(
            detection_meta,
            {"head_name": "vehicle", "set_unknown": True},
        )


# ─────────────────────────────────────────────────────────────────
# 6. 원본 meta 불변 / 이미지 메타 보존
# ─────────────────────────────────────────────────────────────────


def test_original_meta_not_mutated() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    original_labels = dict(meta.image_records[0].labels or {})

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "classes": "truck"},
    )
    # 결과 조작
    result.image_records[0].labels["vehicle"] = ["junk"]  # type: ignore[index]

    assert meta.image_records[0].labels == original_labels


def test_image_metadata_preserved() -> None:
    record = ImageRecord(
        image_id=42,
        file_name="images/deep/truck_001.jpg",
        width=1920,
        height=1080,
        labels={"vehicle": ["sedan"]},
        extra={"source_storage_uri": "source/A/1.0"},
    )
    meta = _make_meta([record])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "classes": "truck"},
    )

    out = result.image_records[0]
    assert out.image_id == 42
    assert out.file_name == "images/deep/truck_001.jpg"
    assert out.width == 1920
    assert out.height == 1080
    assert out.extra == {"source_storage_uri": "source/A/1.0"}
