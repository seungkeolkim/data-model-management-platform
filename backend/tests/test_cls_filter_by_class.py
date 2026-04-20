"""
cls_filter_by_class Manipulator 단위 테스트.

커버 영역:
  1. include 모드 — class 매칭 이미지만 남음
  2. exclude 모드 — class 매칭 이미지 drop
  3. unknown 토글 — null labels 처리 (§2-12)
  4. [] (explicit empty) 는 unknown 으로 취급되지 않음
  5. multi-label any-policy — 하나라도 겹치면 match
  6. "label 없는 이미지 제거" 통합 use case (기존 cls_remove_images_without_label 대체)
  7. head_schema / categories / storage_uri 보존
  8. deep copy 격리
  9. 입력 검증 에러 (list, invalid params)
 10. validate_filter_by_class_params 순수 함수 테스트
 11. 내부 파싱 헬퍼 단위
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_filter_by_class import (
    FilterByClassClassification,
    _parse_classes,
    _parse_include_unknown,
    _parse_mode,
    validate_filter_by_class_params,
)
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord


# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    file_name: str,
    labels: dict[str, list[str] | None] | None = None,
    image_id: int = 1,
) -> ImageRecord:
    return ImageRecord(
        image_id=image_id,
        file_name=file_name,
        width=640,
        height=480,
        labels=labels if labels is not None else {"vehicle": ["sedan"]},
        extra={},
    )


def _make_meta(
    records: list[ImageRecord],
    head_schema: list[HeadSchema] | None = None,
) -> DatasetMeta:
    if head_schema is None:
        head_schema = [
            HeadSchema(
                name="vehicle",
                multi_label=False,
                classes=["sedan", "truck", "boat", "ship"],
            ),
        ]
    return DatasetMeta(
        dataset_id="test-ds",
        storage_uri="processed/src/1.0",
        categories=[],
        image_records=records,
        head_schema=head_schema,
    )


_MANIPULATOR = FilterByClassClassification()


# ─────────────────────────────────────────────────────────────────
# 1. include 모드
# ─────────────────────────────────────────────────────────────────


def test_include_keeps_only_matching_classes() -> None:
    """include + classes=[truck] → vehicle=truck 만 남음."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": ["sedan"]}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
        _make_record("c.jpg", labels={"vehicle": ["boat"]}, image_id=3),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["truck"],
    })

    assert [r.image_id for r in result.image_records] == [2]


def test_include_multiple_classes() -> None:
    """include + classes=[truck, boat] → 둘 중 하나라도 매칭."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": ["sedan"]}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
        _make_record("c.jpg", labels={"vehicle": ["boat"]}, image_id=3),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["truck", "boat"],
    })

    assert sorted(r.image_id for r in result.image_records) == [2, 3]


# ─────────────────────────────────────────────────────────────────
# 2. exclude 모드
# ─────────────────────────────────────────────────────────────────


def test_exclude_drops_matching_classes() -> None:
    """exclude + classes=[boat, ship] → 해당 class 이미지 drop."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": ["sedan"]}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["boat"]}, image_id=2),
        _make_record("c.jpg", labels={"vehicle": ["ship"]}, image_id=3),
        _make_record("d.jpg", labels={"vehicle": ["truck"]}, image_id=4),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "exclude",
        "classes": ["boat", "ship"],
    })

    assert sorted(r.image_id for r in result.image_records) == [1, 4]


# ─────────────────────────────────────────────────────────────────
# 3. unknown 토글 — null labels
# ─────────────────────────────────────────────────────────────────


def test_include_unknown_true_matches_null_labels() -> None:
    """include_unknown=True 면 null 도 match 로 간주."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": None}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["truck"],
        "include_unknown": True,
    })

    # include 이므로 match=True 모두 keep — null 과 truck 둘 다.
    assert sorted(r.image_id for r in result.image_records) == [1, 2]


def test_exclude_unknown_true_drops_null_labels() -> None:
    """exclude + include_unknown=True + classes=[] → null 만 drop."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": None}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
        _make_record("c.jpg", labels={"vehicle": ["sedan"]}, image_id=3),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "exclude",
        "classes": [],
        "include_unknown": True,
    })

    # unknown(null) 만 drop, 나머지 keep.
    assert sorted(r.image_id for r in result.image_records) == [2, 3]


def test_include_unknown_false_drops_null_in_include_mode() -> None:
    """include + include_unknown=False 면 null labels 는 drop."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": None}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["truck"],
        "include_unknown": False,
    })

    # null 은 match False → include 는 drop. truck 만 keep.
    assert [r.image_id for r in result.image_records] == [2]


# ─────────────────────────────────────────────────────────────────
# 4. [] (explicit empty) 는 unknown 이 아님
# ─────────────────────────────────────────────────────────────────


def test_empty_list_is_not_unknown() -> None:
    """
    labels=[] 는 "class 없음" 이 확정된 상태. include_unknown 에 영향받지 않고
    classes 와 교집합 기준으로만 판정된다 (§2-12).
    """
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": []}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
    ], head_schema=[
        HeadSchema(name="vehicle", multi_label=True, classes=["truck", "boat"]),
    ])

    # include_unknown=True 에도 [] 는 match=False 유지.
    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "exclude",
        "classes": [],
        "include_unknown": True,
    })

    # exclude + classes=[] + unknown=True → null 만 drop. [] 는 안 drop.
    assert sorted(r.image_id for r in result.image_records) == [1, 2]


def test_empty_list_not_matched_by_classes() -> None:
    """
    labels=[] vs classes=[truck] → 교집합 False → include 모드에서 drop.
    """
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": []}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": ["truck"]}, image_id=2),
    ], head_schema=[
        HeadSchema(name="vehicle", multi_label=True, classes=["truck", "boat"]),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["truck"],
    })

    assert [r.image_id for r in result.image_records] == [2]


# ─────────────────────────────────────────────────────────────────
# 5. multi-label any-policy
# ─────────────────────────────────────────────────────────────────


def test_multi_label_any_match() -> None:
    """labels=[truck, red] vs classes=[red] → 교집합 있음 → match."""
    meta = _make_meta([
        _make_record("a.jpg", labels={"attr": ["truck", "red"]}, image_id=1),
        _make_record("b.jpg", labels={"attr": ["sedan"]}, image_id=2),
    ], head_schema=[
        HeadSchema(
            name="attr", multi_label=True,
            classes=["truck", "sedan", "red", "blue"],
        ),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "attr",
        "mode": "include",
        "classes": ["red"],
    })

    assert [r.image_id for r in result.image_records] == [1]


# ─────────────────────────────────────────────────────────────────
# 6. "label 없는 이미지 제거" 통합 use case
# ─────────────────────────────────────────────────────────────────


def test_use_case_remove_images_without_label() -> None:
    """
    기존 cls_remove_images_without_label 의 완전한 대체:
    exclude + classes=[] + include_unknown=True → null labels 이미지만 drop.
    """
    meta = _make_meta([
        _make_record("a.jpg", labels={"vehicle": None}, image_id=1),
        _make_record("b.jpg", labels={"vehicle": []}, image_id=2),
        _make_record("c.jpg", labels={"vehicle": ["truck"]}, image_id=3),
    ], head_schema=[
        HeadSchema(name="vehicle", multi_label=True, classes=["truck", "boat"]),
    ])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "exclude",
        "classes": [],
        "include_unknown": True,
    })

    # null(image_id=1) 만 drop. [] 와 [truck] 은 keep.
    assert sorted(r.image_id for r in result.image_records) == [2, 3]


# ─────────────────────────────────────────────────────────────────
# 7. head_schema / storage_uri / categories 보존
# ─────────────────────────────────────────────────────────────────


def test_head_schema_preserved() -> None:
    meta = _make_meta([_make_record("a.jpg")])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["sedan"],
    })

    assert [h.name for h in result.head_schema] == ["vehicle"]
    assert result.storage_uri == meta.storage_uri
    assert result.dataset_id == meta.dataset_id


# ─────────────────────────────────────────────────────────────────
# 8. deep copy 격리
# ─────────────────────────────────────────────────────────────────


def test_deep_copy_isolation() -> None:
    """result 수정이 원본 meta 에 영향 주지 않는다."""
    meta = _make_meta([_make_record("a.jpg", labels={"vehicle": ["sedan"]})])

    result = _MANIPULATOR.transform_annotation(meta, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["sedan"],
    })
    result.image_records[0].labels["vehicle"] = ["MUTATED"]

    assert meta.image_records[0].labels["vehicle"] == ["sedan"]


# ─────────────────────────────────────────────────────────────────
# 9. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_list_input() -> None:
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation([meta], {
            "head_name": "vehicle",
            "mode": "include",
            "classes": ["sedan"],
        })


def test_error_head_name_missing() -> None:
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(ValueError, match="head_name"):
        _MANIPULATOR.transform_annotation(meta, {
            "mode": "include", "classes": ["sedan"],
        })


def test_error_head_name_not_found() -> None:
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(ValueError, match="head_schema"):
        _MANIPULATOR.transform_annotation(meta, {
            "head_name": "nonexistent",
            "mode": "include",
            "classes": ["sedan"],
        })


def test_error_class_not_in_schema() -> None:
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(ValueError, match="head_schema"):
        _MANIPULATOR.transform_annotation(meta, {
            "head_name": "vehicle",
            "mode": "include",
            "classes": ["mystery_class"],
        })


def test_error_no_op_classes_empty_unknown_false() -> None:
    """classes=[] ∧ include_unknown=False 는 no-op → 차단."""
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(ValueError, match="매칭되는 이미지가 없"):
        _MANIPULATOR.transform_annotation(meta, {
            "head_name": "vehicle",
            "mode": "include",
            "classes": [],
            "include_unknown": False,
        })


def test_error_invalid_mode() -> None:
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(ValueError, match="mode"):
        _MANIPULATOR.transform_annotation(meta, {
            "head_name": "vehicle",
            "mode": "keep",
            "classes": ["sedan"],
        })


def test_error_duplicate_classes() -> None:
    meta = _make_meta([_make_record("a.jpg")])
    with pytest.raises(ValueError, match="중복"):
        _MANIPULATOR.transform_annotation(meta, {
            "head_name": "vehicle",
            "mode": "include",
            "classes": ["sedan", "sedan"],
        })


# ─────────────────────────────────────────────────────────────────
# 10. validate_filter_by_class_params 순수 함수
# ─────────────────────────────────────────────────────────────────


_SIMPLE_SCHEMA = [
    HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
]


def test_validate_head_schema_missing() -> None:
    issues = validate_filter_by_class_params(None, {
        "head_name": "vehicle", "mode": "include", "classes": ["sedan"],
    })
    assert len(issues) == 1
    assert issues[0][0] == "HEAD_SCHEMA_MISSING"


def test_validate_head_name_missing() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "mode": "include", "classes": ["sedan"],
    })
    assert len(issues) == 1
    assert issues[0][0] == "HEAD_NAME_MISSING"


def test_validate_head_name_not_found() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "color", "mode": "include", "classes": ["red"],
    })
    assert len(issues) == 1
    assert issues[0][0] == "HEAD_NAME_NOT_FOUND"


def test_validate_mode_invalid() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "vehicle", "mode": "bogus", "classes": ["sedan"],
    })
    assert len(issues) == 1
    assert issues[0][0] == "MODE_INVALID"


def test_validate_classes_not_in_schema() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "vehicle", "mode": "include", "classes": ["ufo"],
    })
    codes = [c for c, _ in issues]
    assert "CLASSES_NOT_IN_SCHEMA" in codes


def test_validate_classes_duplicate() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "vehicle",
        "mode": "include",
        "classes": ["sedan", "sedan"],
    })
    codes = [c for c, _ in issues]
    assert "CLASSES_DUPLICATE" in codes


def test_validate_no_op_classes_empty_unknown_false() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "vehicle", "mode": "include",
        "classes": [], "include_unknown": False,
    })
    codes = [c for c, _ in issues]
    assert "FILTER_MATCHES_NOTHING" in codes


def test_validate_ok_returns_empty() -> None:
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "vehicle", "mode": "include", "classes": ["sedan"],
    })
    assert issues == []


def test_validate_ok_empty_classes_with_unknown() -> None:
    """classes=[] 라도 include_unknown=True 면 unknown-only 판정이라 OK."""
    issues = validate_filter_by_class_params(_SIMPLE_SCHEMA, {
        "head_name": "vehicle", "mode": "exclude",
        "classes": [], "include_unknown": True,
    })
    assert issues == []


def test_validate_multi_issue_accumulation() -> None:
    """duplicate 와 SSOT 위반이 동시에 있으면 둘 다 issue 로 반환."""
    schema_with_alpha = [
        HeadSchema(name="vehicle", multi_label=True,
                   classes=["sedan", "truck"]),
    ]
    issues = validate_filter_by_class_params(schema_with_alpha, {
        "head_name": "vehicle", "mode": "include",
        "classes": ["sedan", "sedan", "ufo"],
    })
    codes = [c for c, _ in issues]
    assert "CLASSES_DUPLICATE" in codes
    assert "CLASSES_NOT_IN_SCHEMA" in codes


# ─────────────────────────────────────────────────────────────────
# 11. 내부 파싱 헬퍼 단위
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("include", "include"),
    ("exclude", "exclude"),
    ("  INCLUDE  ", "include"),
    (None, "include"),
])
def test_parse_mode(raw, expected) -> None:
    assert _parse_mode(raw) == expected


@pytest.mark.parametrize("raw", ["keep", "", "discard", 123])
def test_parse_mode_rejects_invalid(raw) -> None:
    with pytest.raises(ValueError):
        _parse_mode(raw)


@pytest.mark.parametrize("raw,expected", [
    (None, []),
    ("", []),
    ("a\nb\nc", ["a", "b", "c"]),
    ("a\n\n b \n", ["a", "b"]),
    (["a", "b"], ["a", "b"]),
    ([" a ", "", "b"], ["a", "b"]),
])
def test_parse_classes(raw, expected) -> None:
    assert _parse_classes(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (True, True),
    (False, False),
    (None, False),
    ("true", True),
    ("false", False),
    ("1", True),
    ("0", False),
    ("on", True),
    ("", False),
])
def test_parse_include_unknown(raw, expected) -> None:
    assert _parse_include_unknown(raw) == expected


@pytest.mark.parametrize("raw", ["maybe", 42, [1, 2]])
def test_parse_include_unknown_rejects_invalid(raw) -> None:
    with pytest.raises(ValueError):
        _parse_include_unknown(raw)
