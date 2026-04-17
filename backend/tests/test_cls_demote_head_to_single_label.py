"""
cls_demote_head_to_single_label Manipulator 단위 테스트.

커버 영역:
  1. 정상 강등 — multi_label=True → False, single-label 적합 이미지 전부 유지
  2. null(unknown) 보존 (§2-12)
  3. on_violation="skip" — 위반 이미지([class 2개 이상], []) 제외 + 나머지 유지
  4. on_violation="fail" — 위반 이미지 발견 시 즉시 ValueError
  5. 이미 single-label 인 head → passthrough (에러 아님)
  6. 다른 head 는 변경되지 않음
  7. 입력 검증 에러 (head 미존재, head_schema None, list 입력 등)
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_demote_head_to_single_label import (
    DemoteHeadToSingleLabelClassification,
)
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


_MANIPULATOR = DemoteHeadToSingleLabelClassification()


# ─────────────────────────────────────────────────────────────────
# 1. 정상 강등 — 모든 이미지가 single-label 적합
# ─────────────────────────────────────────────────────────────────


def test_demote_basic_all_single_label_compatible() -> None:
    """모든 이미지가 class 1개이면 multi_label 플래그만 변경, 이미지 전부 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=True, classes=["sedan", "truck"]),
        ],
        records=[
            _make_record("sha1", {"vehicle": ["sedan"]}),
            _make_record("sha2", {"vehicle": ["truck"]}),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "on_violation": "skip"},
    )

    assert result.head_schema[0].multi_label is False
    assert len(result.image_records) == 2
    assert result.image_records[0].labels["vehicle"] == ["sedan"]
    assert result.image_records[1].labels["vehicle"] == ["truck"]


def test_demote_classes_preserved() -> None:
    """강등 후 head.classes 배열은 변경되지 않는다."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="color", multi_label=True, classes=["red", "blue", "green"]),
        ],
        records=[],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "color", "on_violation": "fail"},
    )

    assert result.head_schema[0].classes == ["red", "blue", "green"]
    assert result.head_schema[0].multi_label is False


# ─────────────────────────────────────────────────────────────────
# 2. null(unknown) 보존
# ─────────────────────────────────────────────────────────────────


def test_null_unknown_preserved() -> None:
    """labels[head] = null(unknown) 이면 single-label 에서도 유효 — 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=True, classes=["sedan", "truck"]),
        ],
        records=[
            _make_record("sha1", {"vehicle": None}),
            _make_record("sha2", {"vehicle": ["sedan"]}),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "on_violation": "fail"},
    )

    assert result.image_records[0].labels["vehicle"] is None
    assert result.image_records[1].labels["vehicle"] == ["sedan"]
    assert len(result.image_records) == 2


# ─────────────────────────────────────────────────────────────────
# 3. on_violation="skip" — 위반 이미지 제외
# ─────────────────────────────────────────────────────────────────


def test_skip_multi_label_images() -> None:
    """class 2개 이상인 이미지는 skip 되고, 나머지만 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="attr", multi_label=True, classes=["hat", "glasses", "scarf"]),
        ],
        records=[
            _make_record("sha1", {"attr": ["hat"]}),           # 적합
            _make_record("sha2", {"attr": ["hat", "glasses"]}), # 위반: 2개
            _make_record("sha3", {"attr": ["scarf"]}),          # 적합
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "attr", "on_violation": "skip"},
    )

    assert len(result.image_records) == 2
    shas = [r.sha for r in result.image_records]
    assert "sha1" in shas
    assert "sha3" in shas
    assert "sha2" not in shas


def test_skip_empty_list_images() -> None:
    """[] (explicit empty) 는 single-label 에서 허용 안 됨 → skip."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="color", multi_label=True, classes=["red", "blue"]),
        ],
        records=[
            _make_record("sha1", {"color": ["red"]}),  # 적합
            _make_record("sha2", {"color": []}),        # 위반: explicit empty
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "color", "on_violation": "skip"},
    )

    assert len(result.image_records) == 1
    assert result.image_records[0].sha == "sha1"


def test_skip_mixed_violations() -> None:
    """null, 1개, 2개, 0개가 섞인 경우 — null 과 1개만 유지."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="h", multi_label=True, classes=["a", "b", "c"]),
        ],
        records=[
            _make_record("sha1", {"h": None}),          # null → 유지
            _make_record("sha2", {"h": ["a"]}),          # 1개 → 유지
            _make_record("sha3", {"h": ["a", "b"]}),     # 2개 → skip
            _make_record("sha4", {"h": []}),             # 0개 → skip
            _make_record("sha5", {"h": ["c"]}),          # 1개 → 유지
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "h", "on_violation": "skip"},
    )

    assert len(result.image_records) == 3
    shas = [r.sha for r in result.image_records]
    assert shas == ["sha1", "sha2", "sha5"]


# ─────────────────────────────────────────────────────────────────
# 4. on_violation="fail" — 위반 시 즉시 ValueError
# ─────────────────────────────────────────────────────────────────


def test_fail_on_multi_label_image() -> None:
    """class 2개 이상 이미지가 있으면 ValueError."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="h", multi_label=True, classes=["a", "b"]),
        ],
        records=[
            _make_record("sha1", {"h": ["a", "b"]}),
        ],
    )

    with pytest.raises(ValueError, match="single-label 위반"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "h", "on_violation": "fail"},
        )


def test_fail_on_empty_list_image() -> None:
    """[] (explicit empty) 가 있으면 ValueError."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="h", multi_label=True, classes=["a", "b"]),
        ],
        records=[
            _make_record("sha1", {"h": []}),
        ],
    )

    with pytest.raises(ValueError, match="single-label 위반"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "h", "on_violation": "fail"},
        )


def test_fail_default_on_violation() -> None:
    """on_violation 미지정 시 기본값 'fail' — 위반 이미지가 있으면 ValueError."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="h", multi_label=True, classes=["a", "b"]),
        ],
        records=[
            _make_record("sha1", {"h": ["a", "b"]}),
        ],
    )

    with pytest.raises(ValueError, match="single-label 위반"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "h"},  # on_violation 생략 → "fail"
        )


# ─────────────────────────────────────────────────────────────────
# 5. 이미 single-label → passthrough
# ─────────────────────────────────────────────────────────────────


def test_already_single_label_passthrough() -> None:
    """이미 single-label 인 head → 변경 없이 그대로 반환."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="vehicle", multi_label=False, classes=["sedan", "truck"]),
        ],
        records=[
            _make_record("sha1", {"vehicle": ["sedan"]}),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "vehicle", "on_violation": "fail"},
    )

    assert result.head_schema[0].multi_label is False
    assert len(result.image_records) == 1
    assert result.image_records[0].labels["vehicle"] == ["sedan"]


# ─────────────────────────────────────────────────────────────────
# 6. 다른 head 는 변경되지 않음
# ─────────────────────────────────────────────────────────────────


def test_other_head_unchanged() -> None:
    """대상이 아닌 head 의 schema, labels 는 변경되지 않는다."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="attr", multi_label=True, classes=["hat", "glasses"]),
            HeadSchema(name="color", multi_label=True, classes=["red", "blue"]),
        ],
        records=[
            _make_record("sha1", {"attr": ["hat"], "color": ["red", "blue"]}),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "attr", "on_violation": "skip"},
    )

    # attr: multi_label → False
    assert result.head_schema[0].multi_label is False
    # color: multi_label 그대로 True
    assert result.head_schema[1].multi_label is True
    assert result.head_schema[1].classes == ["red", "blue"]
    # labels: color 는 그대로
    assert result.image_records[0].labels["color"] == ["red", "blue"]


def test_other_head_null_preserved() -> None:
    """다른 head 의 null(unknown) labels 보존."""
    meta = _make_meta(
        head_schema=[
            HeadSchema(name="attr", multi_label=True, classes=["hat"]),
            HeadSchema(name="color", multi_label=False, classes=["red"]),
        ],
        records=[
            _make_record("sha1", {"attr": ["hat"], "color": None}),
        ],
    )

    result = _MANIPULATOR.transform_annotation(
        meta,
        {"head_name": "attr", "on_violation": "skip"},
    )

    assert result.image_records[0].labels["color"] is None


# ─────────────────────────────────────────────────────────────────
# 7. 입력 검증 에러
# ─────────────────────────────────────────────────────────────────


def test_error_list_input() -> None:
    """list 입력은 TypeError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=True, classes=["a"])],
        records=[],
    )
    with pytest.raises(TypeError):
        _MANIPULATOR.transform_annotation(
            [meta],
            {"head_name": "h", "on_violation": "skip"},
        )


def test_error_head_not_found() -> None:
    """존재하지 않는 head_name 이면 ValueError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=True, classes=["a"])],
        records=[],
    )
    with pytest.raises(ValueError, match="head_schema 에 없습니다"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "nonexistent", "on_violation": "skip"},
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
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "h", "on_violation": "skip"},
        )


def test_error_empty_head_name() -> None:
    """head_name 이 빈 문자열이면 ValueError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=True, classes=["a"])],
        records=[],
    )
    with pytest.raises(ValueError, match="head_name 이 비어있습니다"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "", "on_violation": "skip"},
        )


def test_error_invalid_on_violation() -> None:
    """on_violation 값이 skip/fail 이 아니면 ValueError."""
    meta = _make_meta(
        head_schema=[HeadSchema(name="h", multi_label=True, classes=["a"])],
        records=[],
    )
    with pytest.raises(ValueError, match="skip.*fail"):
        _MANIPULATOR.transform_annotation(
            meta,
            {"head_name": "h", "on_violation": "invalid"},
        )
