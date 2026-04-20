"""
cls_add_head Manipulator 단위 테스트.

커버 영역:
  1. head_schema 에 신규 head 가 맨 뒤로 추가된다
  2. 기존 head 는 변경 없이 보존
  3. 기존 이미지의 신규 head labels = null (unknown)
  4. 기존 이미지의 기존 head labels 는 원형 유지 (null / [] / [class 여러 개] 포함)
  5. multi_label 플래그 (기본 False / True 명시 / 문자열 "true" 수용)
  6. class_candidates 파싱 — textarea 줄바꿈, list, 공백 줄 제외
  7. 검증 에러:
     - head_name 누락/공백
     - head_name 이 기존 head 와 충돌
     - class_candidates 누락/1개 이하/중복
     - list 입력 (TypeError)
     - head_schema 가 None 인 DatasetMeta (detection)
  8. deep copy 격리 (결과 수정이 원본 meta 에 전파되지 않음)
  9. file_name / width / height / extra 보존 (이미지 바이너리 불변)
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_add_head import AddHeadClassification
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


_MANIPULATOR = AddHeadClassification()


# ─────────────────────────────────────────────────────────────────
# 1. head_schema 에 신규 head 가 맨 뒤로 추가
# ─────────────────────────────────────────────────────────────────


def test_new_head_appended_to_end() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
            HeadSchema(name="color", multi_label=False, classes=["red", "blue"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "weather",
            "multi_label": False,
            "class_candidates": "sunny\ncloudy\nrainy",
        },
    )

    assert result.head_schema is not None
    assert [head.name for head in result.head_schema] == ["vehicle", "color", "weather"]
    new_head = result.head_schema[-1]
    assert new_head.name == "weather"
    assert new_head.multi_label is False
    assert new_head.classes == ["sunny", "cloudy", "rainy"]


def test_existing_heads_preserved() -> None:
    """기존 head 의 multi_label / classes 는 그대로 유지된다."""
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan", "truck"]})],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=True, classes=["sedan", "truck"]),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "weather",
            "multi_label": False,
            "class_candidates": ["sunny", "rainy"],
        },
    )

    assert result.head_schema is not None
    existing = result.head_schema[0]
    assert existing.name == "vehicle"
    assert existing.multi_label is True
    assert existing.classes == ["sedan", "truck"]


# ─────────────────────────────────────────────────────────────────
# 2. 기존 이미지의 신규 head labels = null
# ─────────────────────────────────────────────────────────────────


def test_all_images_get_null_for_new_head() -> None:
    meta = _make_meta([
        _make_record("images/a.jpg", labels={"vehicle": ["sedan"]}),
        _make_record("images/b.jpg", labels={"vehicle": None}),  # 기존에도 unknown
        _make_record("images/c.jpg", labels={"vehicle": []}),    # explicit empty
    ])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "weather",
            "multi_label": False,
            "class_candidates": "sunny\nrainy",
        },
    )

    assert result.image_records[0].labels == {"vehicle": ["sedan"], "weather": None}
    assert result.image_records[1].labels == {"vehicle": None, "weather": None}
    assert result.image_records[2].labels == {"vehicle": [], "weather": None}


def test_empty_labels_dict_gets_null_for_new_head() -> None:
    """labels 가 빈 dict 인 이미지도 신규 head 가 null 로 채워진다."""
    meta = _make_meta([_make_record("images/a.jpg", labels={})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "weather",
            "class_candidates": "sunny\nrainy",
        },
    )

    assert result.image_records[0].labels == {"weather": None}


# ─────────────────────────────────────────────────────────────────
# 3. multi_label 플래그
# ─────────────────────────────────────────────────────────────────


def test_multi_label_default_false() -> None:
    """multi_label 생략 시 False (single-label)."""
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "weather", "class_candidates": "sunny\nrainy"},
    )

    assert result.head_schema is not None
    assert result.head_schema[-1].multi_label is False


def test_multi_label_true_explicit() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "tags",
            "multi_label": True,
            "class_candidates": "a\nb\nc",
        },
    )

    assert result.head_schema is not None
    assert result.head_schema[-1].multi_label is True


@pytest.mark.parametrize("truthy", ["true", "True", "1", "yes", "on"])
def test_multi_label_string_truthy(truthy: str) -> None:
    """체크박스 값이 문자열로 직렬화되어 들어와도 수용한다."""
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "tags",
            "multi_label": truthy,
            "class_candidates": "a\nb",
        },
    )

    assert result.head_schema is not None
    assert result.head_schema[-1].multi_label is True


@pytest.mark.parametrize("falsy", ["false", "False", "0", "no", "off", ""])
def test_multi_label_string_falsy(falsy: str) -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "tags",
            "multi_label": falsy,
            "class_candidates": "a\nb",
        },
    )

    assert result.head_schema is not None
    assert result.head_schema[-1].multi_label is False


# ─────────────────────────────────────────────────────────────────
# 4. class_candidates 파싱
# ─────────────────────────────────────────────────────────────────


def test_class_candidates_textarea_splits_by_newline() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "weather",
            "class_candidates": "sunny\n  cloudy  \n\nrainy\n",
        },
    )

    assert result.head_schema is not None
    assert result.head_schema[-1].classes == ["sunny", "cloudy", "rainy"]


def test_class_candidates_list_input() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(
        meta,
        {
            "head_name": "weather",
            "class_candidates": [" sunny ", "rainy", ""],
        },
    )

    assert result.head_schema is not None
    assert result.head_schema[-1].classes == ["sunny", "rainy"]


# ─────────────────────────────────────────────────────────────────
# 5. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_head_name_missing() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="head_name"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"class_candidates": "a\nb"},
        )


def test_error_head_name_whitespace() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="공백"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "   ", "class_candidates": "a\nb"},
        )


def test_error_head_name_collision() -> None:
    meta = _make_meta(
        [_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})],
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
        ],
    )
    with pytest.raises(ValueError, match="이미 존재"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "vehicle", "class_candidates": "a\nb"},
        )


def test_error_class_candidates_missing() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="class_candidates"):
        _MANIPULATOR.transform_annotation(meta, {"head_name": "weather"})


def test_error_class_candidates_too_few() -> None:
    """class 가 1개 이하면 에러 (2개 이상 필수)."""
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="2개 이상"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "weather", "class_candidates": "sunny"},
        )


def test_error_class_candidates_duplicate() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(ValueError, match="중복"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "weather", "class_candidates": "sunny\nrainy\nsunny"},
        )


def test_error_list_input() -> None:
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation(
            [meta],
            {"head_name": "weather", "class_candidates": "a\nb"},
        )


def test_error_detection_dataset() -> None:
    """head_schema 가 None 인 detection DatasetMeta 는 거부한다."""
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
            {"head_name": "weather", "class_candidates": "a\nb"},
        )


# ─────────────────────────────────────────────────────────────────
# 6. deep copy 격리 + 이미지 메타 보존
# ─────────────────────────────────────────────────────────────────


def test_original_meta_not_mutated() -> None:
    """결과 수정이 원본 meta 에 영향을 주지 않는다."""
    meta = _make_meta([_make_record("images/a.jpg", labels={"vehicle": ["sedan"]})])
    original_head_count = len(meta.head_schema or [])
    original_labels = dict(meta.image_records[0].labels or {})

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "weather", "class_candidates": "a\nb"},
    )
    # 결과 조작
    result.head_schema.append(
        HeadSchema(name="junk", multi_label=False, classes=["x", "y"])
    )
    result.image_records[0].labels["vehicle"] = ["truck"]  # type: ignore[index]

    # 원본 불변
    assert len(meta.head_schema or []) == original_head_count
    assert meta.image_records[0].labels == original_labels


def test_image_metadata_preserved() -> None:
    """이미지 바이너리 불변 — file_name / width / height / extra 그대로 유지."""
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
        {"head_name": "weather", "class_candidates": "a\nb"},
    )

    out_record = result.image_records[0]
    assert out_record.image_id == 42
    assert out_record.file_name == "images/deep/truck_001.jpg"
    assert out_record.width == 1920
    assert out_record.height == 1080
    assert out_record.extra == {"source_storage_uri": "source/A/1.0"}
