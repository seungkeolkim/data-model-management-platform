"""
cls_merge_datasets Manipulator 단위 테스트.

정책 참조: `objective_n_plan_7th.md §2-8 (filename identity)` + §2-11.

§2-8 확정 이후 동작:
    - 이미지 identity = file_name (과거 SHA 기반 content dedup 폐지).
    - 같은 파일명이 2개 이상 입력에 존재하면 detection 과 동일한
      `{display_name}_{md5_4자리}_{basename}` prefix 를 부착해 공존시킨다.
    - label 충돌 판정 및 drop 로직은 제거되었다 (파일명이 달라지므로 충돌 불가).

커버 영역:
  1. Head / Class union + multi_label_union 승격
  2. fill_empty 가 만들어낸 head 의 누락값은 None(unknown) 으로 채워진다 (§2-12).
  3. 동일 파일명 충돌 → prefix rename 으로 공존.
  4. 파일명이 겹치지 않으면 모두 그대로 유지.
  5. Phase B 실체화를 위한 extra 필드(source_storage_uri, original_file_name,
     source_dataset_id) 가 올바르게 세팅된다.
  6. 입력 정규화 에러.
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_merge_datasets import MergeDatasetsClassification
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord


# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    file_name: str,
    labels: dict[str, list[str] | None],
    image_id: int | str = 1,
) -> ImageRecord:
    return ImageRecord(
        image_id=image_id,
        file_name=file_name,
        width=640,
        height=480,
        labels=labels,
    )


def _make_meta(
    dataset_id: str,
    head_schema: list[HeadSchema],
    records: list[ImageRecord],
    storage_uri: str | None = None,
) -> DatasetMeta:
    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=storage_uri or f"/fake/{dataset_id}",
        categories=[],
        image_records=records,
        head_schema=head_schema,
    )


def _permissive_params() -> dict[str, str]:
    return {
        "on_head_mismatch": "fill_empty",
        "on_class_set_mismatch": "multi_label_union",
    }


# ─────────────────────────────────────────────────────────────────
# 1. Head / Class union
# ─────────────────────────────────────────────────────────────────


def test_head_union_with_fill_empty() -> None:
    """서로 다른 head 집합을 fill_empty 로 병합하면 union 순서가 보존된다.

    (compat 검증상 공통 head 가 최소 1개 필요해 'shared' 를 양쪽에 둔다.)
    """
    shared = HeadSchema(name="shared", multi_label=False, classes=["s"])
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[
            HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"]),
            shared,
        ],
        records=[
            _make_record("images/a1.jpg", {"wear": ["helmet"], "shared": ["s"]})
        ],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[
            HeadSchema(name="visibility", multi_label=False, classes=["seen", "unseen"]),
            shared,
        ],
        records=[
            _make_record("images/b1.jpg", {"visibility": ["seen"], "shared": ["s"]})
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    head_names = [head.name for head in result.head_schema]
    # A 먼저, B 의 신규 head 가 뒤에.
    assert head_names == ["wear", "shared", "visibility"]
    # 파일명이 겹치지 않으므로 그대로 2장 유지.
    assert len(result.image_records) == 2


def test_class_set_union_promotes_to_multi_label() -> None:
    """class 집합이 다르면 multi_label_union 옵션이 multi_label 을 True 로 승격.

    (compat 검증상 공통 class 1개 필요해 'common' 을 양쪽에 둔다.)
    """
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[HeadSchema(name="tag", multi_label=False, classes=["common", "x"])],
        records=[_make_record("images/a.jpg", {"tag": ["x"]})],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[HeadSchema(name="tag", multi_label=False, classes=["common", "y"])],
        records=[_make_record("images/b.jpg", {"tag": ["y"]})],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    assert len(result.head_schema) == 1
    assert result.head_schema[0].multi_label is True
    assert result.head_schema[0].classes == ["common", "x", "y"]


# ─────────────────────────────────────────────────────────────────
# 2. fill_empty: 누락된 head 는 None(unknown) 으로 채워진다
# ─────────────────────────────────────────────────────────────────


def test_fill_empty_missing_head_is_unknown_not_empty_list() -> None:
    """한쪽에만 존재하는 head 는 상대 입력 레코드에서 None(unknown) 으로 채워진다.

    (compat 검증상 공통 head 1개 필요.)
    """
    shared = HeadSchema(name="shared", multi_label=False, classes=["s"])
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[
            HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"]),
            shared,
        ],
        records=[
            _make_record(
                "images/a.jpg", {"wear": ["helmet"], "shared": ["s"]},
            ),
        ],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[
            HeadSchema(name="visibility", multi_label=False, classes=["seen", "unseen"]),
            shared,
        ],
        records=[
            _make_record(
                "images/b.jpg", {"visibility": ["seen"], "shared": ["s"]},
            ),
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    by_name = {rec.file_name: rec for rec in result.image_records}
    assert by_name["images/a.jpg"].labels["wear"] == ["helmet"]
    # B 쪽에 없는 head 'wear' 는 A 레코드만 값이 있고, B 레코드에서는 None(unknown).
    assert by_name["images/b.jpg"].labels["wear"] is None
    # 반대로 A 에는 없는 'visibility' 는 A 레코드에서 None.
    assert by_name["images/a.jpg"].labels["visibility"] is None
    assert by_name["images/b.jpg"].labels["visibility"] == ["seen"]


# ─────────────────────────────────────────────────────────────────
# 3. 파일명 충돌 → prefix rename 으로 공존
# ─────────────────────────────────────────────────────────────────


def test_filename_collision_renames_with_prefix() -> None:
    """같은 파일명이 두 입력에 존재하면 양쪽 모두 prefix 부착된 이름으로 rename 되어 공존한다."""
    head = HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"])
    meta_a = _make_meta(
        dataset_id="dataset-a",
        head_schema=[head],
        records=[_make_record("images/shared.jpg", {"wear": ["helmet"]})],
        storage_uri="/fake/raw_a",
    )
    meta_b = _make_meta(
        dataset_id="dataset-b",
        head_schema=[head],
        records=[_make_record("images/shared.jpg", {"wear": ["no_helmet"]})],
        storage_uri="/fake/raw_b",
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    # 드롭 없이 2장 모두 유지.
    assert len(result.image_records) == 2
    file_names = {rec.file_name for rec in result.image_records}
    # 두 파일명 모두 rename 되어 원본 이름은 남지 않는다.
    assert "images/shared.jpg" not in file_names
    # 경로 prefix "images/" 는 유지되고 basename 만 변경.
    for name in file_names:
        assert name.startswith("images/")
        assert name.endswith("_shared.jpg")


def test_filename_unique_across_inputs_kept_as_is() -> None:
    """각 입력에 파일명이 겹치지 않으면 rename 없이 그대로 결과에 들어간다."""
    head = HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"])
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[head],
        records=[_make_record("images/a1.jpg", {"wear": ["helmet"]})],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[head],
        records=[_make_record("images/b1.jpg", {"wear": ["no_helmet"]})],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    assert {rec.file_name for rec in result.image_records} == {
        "images/a1.jpg",
        "images/b1.jpg",
    }


# ─────────────────────────────────────────────────────────────────
# 4. Phase B 용 extra 메타 세팅
# ─────────────────────────────────────────────────────────────────


def test_extra_fields_populated_for_phase_b_materialization() -> None:
    """rename 여부와 무관하게 extra 에 source 경로/원본 파일명이 기록된다."""
    head = HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"])
    meta_a = _make_meta(
        dataset_id="dataset-a",
        head_schema=[head],
        records=[_make_record("images/shared.jpg", {"wear": ["helmet"]})],
        storage_uri="/fake/raw_a",
    )
    meta_b = _make_meta(
        dataset_id="dataset-b",
        head_schema=[head],
        records=[_make_record("images/shared.jpg", {"wear": ["no_helmet"]})],
        storage_uri="/fake/raw_b",
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    # 결과 2장 각각에 대해 extra 필드 검증.
    by_source = {rec.extra["source_dataset_id"]: rec for rec in result.image_records}
    assert by_source["dataset-a"].extra["source_storage_uri"] == "/fake/raw_a"
    assert by_source["dataset-a"].extra["original_file_name"] == "images/shared.jpg"
    assert by_source["dataset-b"].extra["source_storage_uri"] == "/fake/raw_b"
    assert by_source["dataset-b"].extra["original_file_name"] == "images/shared.jpg"


def test_preserves_upstream_source_tracking_for_transformed_records() -> None:
    """
    상류 이미지 변형 manipulator (cls_crop_image / cls_rotate_image 등 §6-1) 가
    이미 세팅해 둔 source_storage_uri / original_file_name 은 merge 가 덮어쓰지
    않고 그대로 보존해야 한다.

    이것이 깨지면 Phase B 가 "존재하지 않는 (postfix 가 붙은) src 경로" 를
    생성해 전량 skip 된다 — 파이프라인 0e6585cf 에서 실제 발생한 회귀.
    """
    head = HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"])

    # 입력 A: crop 이 적용된 기록 (file_name 은 post-crop, extra 에는 pre-crop 원본 정보).
    cropped_record = ImageRecord(
        image_id=1,
        file_name="images/photo_crop_up_030.jpg",
        width=640,
        height=336,
        labels={"wear": ["helmet"]},
        extra={
            "source_storage_uri": "/fake/truly_original_a",
            "original_file_name": "images/photo.jpg",
            "image_manipulation_specs": [
                {
                    "operation": "crop_image_vertical",
                    "params": {"direction": "up", "crop_pct": 30},
                }
            ],
        },
    )
    meta_a = _make_meta(
        dataset_id="dataset-a",
        head_schema=[head],
        records=[cropped_record],
        storage_uri="/fake/intermediate_a",  # crop 중간 meta — 실제 파일 없음
    )

    # 입력 B: 변형 없이 raw 그대로. extra 에 출처 정보가 없는 기본 케이스.
    meta_b = _make_meta(
        dataset_id="dataset-b",
        head_schema=[head],
        records=[_make_record("images/raw_only.jpg", {"wear": ["no_helmet"]})],
        storage_uri="/fake/raw_b",
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    by_source = {rec.extra["source_dataset_id"]: rec for rec in result.image_records}

    # A: upstream 이 심어둔 진짜 원본을 보존해야 한다 (meta.storage_uri 로 덮어쓰면 안 됨).
    a_record = by_source["dataset-a"]
    assert a_record.extra["source_storage_uri"] == "/fake/truly_original_a"
    assert a_record.extra["original_file_name"] == "images/photo.jpg"
    # file_name 은 post-crop 그대로 유지 (충돌 없음 → rename 없음).
    assert a_record.file_name == "images/photo_crop_up_030.jpg"
    # 변형 spec 도 유실되지 않아야 Phase B 에서 crop 이 다시 적용된다.
    assert a_record.extra.get("image_manipulation_specs") == [
        {"operation": "crop_image_vertical", "params": {"direction": "up", "crop_pct": 30}}
    ]

    # B: upstream 정보가 없으므로 merge 가 기본값으로 채운다 (setdefault 의 fallback 분기).
    b_record = by_source["dataset-b"]
    assert b_record.extra["source_storage_uri"] == "/fake/raw_b"
    assert b_record.extra["original_file_name"] == "images/raw_only.jpg"


# ─────────────────────────────────────────────────────────────────
# 5. 입력 정규화 에러
# ─────────────────────────────────────────────────────────────────


def test_requires_multi_input_list() -> None:
    """단일 DatasetMeta 가 들어오면 TypeError."""
    meta = _make_meta(
        dataset_id="a",
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["x"])],
        records=[],
    )
    with pytest.raises(TypeError):
        MergeDatasetsClassification().transform_annotation(meta, _permissive_params())


def test_requires_at_least_two_inputs() -> None:
    """입력이 1개만 있으면 ValueError."""
    meta = _make_meta(
        dataset_id="a",
        head_schema=[HeadSchema(name="h", multi_label=False, classes=["x"])],
        records=[],
    )
    with pytest.raises(ValueError):
        MergeDatasetsClassification().transform_annotation([meta], _permissive_params())
