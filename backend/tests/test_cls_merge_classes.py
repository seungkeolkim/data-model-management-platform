"""
cls_merge_classes Manipulator 단위 테스트.

커버 영역:
  1. single-label head — source class 병합 → target class 로 교체
  2. multi-label head — source 중 하나라도 pos 이면 OR 병합
  3. null(unknown) 보존
  4. head_schema classes 배열 재구성 (순서/위치)
  5. target_class 가 source_classes 중 하나인 경우 (흡수)
  6. target_class 가 신규 이름인 경우
  7. 입력 검증 에러
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_merge_classes import MergeClassesClassification
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord


# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    tag: str,
    labels: dict[str, list[str] | None],
) -> ImageRecord:
    """tag 는 테스트 내 이미지 식별용 임의 문자열 — file_name 생성에만 쓰임."""
    return ImageRecord(
        image_id=1,
        file_name=f"images/{tag}.jpg",
        width=640,
        height=480,
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


# ─────────────────────────────────────────────────────────────────
# 1. single-label — 기본 병합
# ─────────────────────────────────────────────────────────────────


def test_single_label_merge_source_to_target() -> None:
    """source_classes 중 하나가 라벨이면 target_class 로 교체."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "suv", "van", "truck"]),
        ],
        records=[
            _make_record("sha1", {"vehicle": ["sedan"]}),
            _make_record("sha2", {"vehicle": ["suv"]}),
            _make_record("sha3", {"vehicle": ["van"]}),
            _make_record("sha4", {"vehicle": ["truck"]}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "vehicle", "source_classes": ["sedan", "suv", "van"], "target_class": "car"},
    )

    # sedan, suv, van → car. truck 은 그대로.
    assert result.image_records[0].labels["vehicle"] == ["car"]
    assert result.image_records[1].labels["vehicle"] == ["car"]
    assert result.image_records[2].labels["vehicle"] == ["car"]
    assert result.image_records[3].labels["vehicle"] == ["truck"]


def test_single_label_non_source_unchanged() -> None:
    """source_classes 에 포함되지 않는 라벨은 변경되지 않는다."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="color", multi_label=False, classes=["red", "blue", "green"]),
        ],
        records=[
            _make_record("sha1", {"color": ["green"]}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "color", "source_classes": ["red", "blue"], "target_class": "warm"},
    )

    assert result.image_records[0].labels["color"] == ["green"]


# ─────────────────────────────────────────────────────────────────
# 2. multi-label — OR 병합
# ─────────────────────────────────────────────────────────────────


def test_multi_label_or_merge() -> None:
    """source 중 하나라도 있으면 target 으로 병합 (OR)."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["hat", "cap", "helmet", "glasses"]),
        ],
        records=[
            _make_record("sha1", {"attrs": ["hat", "glasses"]}),
            _make_record("sha2", {"attrs": ["cap"]}),
            _make_record("sha3", {"attrs": ["glasses"]}),  # source 없음
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "attrs", "source_classes": ["hat", "cap", "helmet"], "target_class": "headwear"},
    )

    # sha1: hat(source) + glasses → headwear + glasses
    assert set(result.image_records[0].labels["attrs"]) == {"headwear", "glasses"}
    # sha2: cap(source) → headwear
    assert result.image_records[1].labels["attrs"] == ["headwear"]
    # sha3: glasses(비source) → 그대로
    assert result.image_records[2].labels["attrs"] == ["glasses"]


def test_multi_label_multiple_sources_no_duplicate() -> None:
    """source 가 여러 개 있어도 target 은 1개만 추가된다."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["hat", "cap", "helmet"]),
        ],
        records=[
            _make_record("sha1", {"attrs": ["hat", "cap"]}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "attrs", "source_classes": ["hat", "cap", "helmet"], "target_class": "headwear"},
    )

    assert result.image_records[0].labels["attrs"] == ["headwear"]


def test_multi_label_empty_list_unchanged() -> None:
    """[] (explicit empty = 전부 neg) 는 source 가 없으므로 그대로 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["hat", "cap", "glasses"]),
        ],
        records=[
            _make_record("sha1", {"attrs": []}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "attrs", "source_classes": ["hat", "cap"], "target_class": "headwear"},
    )

    assert result.image_records[0].labels["attrs"] == []


# ─────────────────────────────────────────────────────────────────
# 3. null(unknown) 보존
# ─────────────────────────────────────────────────────────────────


def test_null_unknown_preserved() -> None:
    """labels[head] = null(unknown) 이면 병합 대상이 아니고 null 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "suv", "van"]),
        ],
        records=[
            _make_record("sha1", {"vehicle": None}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "vehicle", "source_classes": ["sedan", "suv"], "target_class": "car"},
    )

    assert result.image_records[0].labels["vehicle"] is None


def test_other_head_null_preserved() -> None:
    """다른 head 의 null 은 병합과 무관하게 보존."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "suv"]),
            HeadSchema(name="color", multi_label=False, classes=["red"]),
        ],
        records=[
            _make_record("sha1", {"vehicle": ["sedan"], "color": None}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "vehicle", "source_classes": ["sedan", "suv"], "target_class": "car"},
    )

    assert result.image_records[0].labels["vehicle"] == ["car"]
    assert result.image_records[0].labels["color"] is None


# ─────────────────────────────────────────────────────────────────
# 4. head_schema classes 배열 재구성
# ─────────────────────────────────────────────────────────────────


def test_classes_order_target_at_first_source_position() -> None:
    """target_class 가 첫 번째 source_class 위치에 삽입된다."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="v", multi_label=False, classes=["a", "b", "c", "d", "e"]),
        ],
        records=[],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "v", "source_classes": ["b", "d"], "target_class": "merged"},
    )

    # b 위치(index 1)에 merged 삽입, d 제거. a 와 c, e 는 유지.
    assert result.head_schema[0].classes == ["a", "merged", "c", "e"]


def test_classes_order_target_is_source_member() -> None:
    """target_class 가 source_classes 중 하나이면 해당 위치에 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="v", multi_label=False, classes=["a", "b", "c", "d"]),
        ],
        records=[],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "v", "source_classes": ["b", "d"], "target_class": "b"},
    )

    # b 는 원래 위치(index 1) 유지, d 제거.
    assert result.head_schema[0].classes == ["a", "b", "c"]


def test_other_head_schema_unchanged() -> None:
    """대상이 아닌 head 의 schema 는 변경되지 않는다."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "suv"]),
            HeadSchema(name="color", multi_label=False, classes=["red", "blue"]),
        ],
        records=[],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "vehicle", "source_classes": ["sedan", "suv"], "target_class": "car"},
    )

    assert result.head_schema[1].classes == ["red", "blue"]


# ─────────────────────────────────────────────────────────────────
# 5. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_source_classes_as_newline_string() -> None:
    """DynamicParamForm textarea 에서 줄바꿈 구분 문자열로 올 때 정상 파싱."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="v", multi_label=False, classes=["sedan", "suv", "truck"]),
        ],
        records=[
            _make_record("sha1", {"v": ["sedan"]}),
        ],
    )

    result = MergeClassesClassification().transform_annotation(
        meta,
        {"head_name": "v", "source_classes": "sedan\nsuv", "target_class": "car"},
    )

    assert result.image_records[0].labels["v"] == ["car"]
    assert result.head_schema[0].classes == ["car", "truck"]


def test_error_list_input() -> None:
    """list 입력은 TypeError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["a", "b"])],
        records=[],
    )
    with pytest.raises(TypeError):
        MergeClassesClassification().transform_annotation(
            [meta],
            {"head_name": "h", "source_classes": ["a", "b"], "target_class": "c"},
        )


def test_error_source_classes_less_than_two() -> None:
    """source_classes 가 2개 미만이면 ValueError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["a", "b"])],
        records=[],
    )
    with pytest.raises(ValueError, match="2개 이상"):
        MergeClassesClassification().transform_annotation(
            meta,
            {"head_name": "h", "source_classes": ["a"], "target_class": "c"},
        )


def test_error_source_class_not_in_head() -> None:
    """source_classes 에 head.classes 에 없는 이름이 있으면 ValueError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["a", "b"])],
        records=[],
    )
    with pytest.raises(ValueError, match="classes 에 없는 이름"):
        MergeClassesClassification().transform_annotation(
            meta,
            {"head_name": "h", "source_classes": ["a", "x"], "target_class": "merged"},
        )


def test_error_target_class_already_exists_not_in_source() -> None:
    """target_class 가 이미 classes 에 있지만 source_classes 가 아니면 중복 에러."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["a", "b", "c"])],
        records=[],
    )
    with pytest.raises(ValueError, match="중복이 발생"):
        MergeClassesClassification().transform_annotation(
            meta,
            {"head_name": "h", "source_classes": ["a", "b"], "target_class": "c"},
        )


def test_error_head_not_found() -> None:
    """존재하지 않는 head_name 이면 ValueError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["a", "b"])],
        records=[],
    )
    with pytest.raises(ValueError, match="head_schema 에 없습니다"):
        MergeClassesClassification().transform_annotation(
            meta,
            {"head_name": "nonexistent", "source_classes": ["a", "b"], "target_class": "c"},
        )


def test_error_no_head_schema() -> None:
    """head_schema 가 None 이면 ValueError."""
    meta = DatasetMeta(
        dataset_id="test",
        storage_uri="/fake",
        categories=["cat"],
        image_records=[],
    )
    with pytest.raises(ValueError, match="head_schema 가 None"):
        MergeClassesClassification().transform_annotation(
            meta,
            {"head_name": "h", "source_classes": ["a", "b"], "target_class": "c"},
        )
