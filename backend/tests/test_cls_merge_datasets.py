"""
cls_merge_datasets Manipulator 단위 테스트.

정책 참조: `objective_n_plan_7th.md §2-11`.

커버 영역:
  1. Head/Class union + multi_label_union 승격
  2. SHA dedup + fill_empty 가 만들어낸 head 의 "unknown 취급" (회귀 테스트)
  3. single-label 실제 충돌 → drop
  4. multi-label pos/explicit_neg/unknown 3값 충돌 판정
  5. 입력 정규화 에러

회귀 테스트 배경 (2번):
  서로 다른 head 이름(예: A=wear, B=hardhat_wear) 을 가진 두 입력을
  fill_empty + merge_if_compatible 로 병합할 때, 과거 구현은 "해당 head 가 없는
  입력" 을 `[]` (explicit-empty) 로 간주해 single_label_mismatch 로 3천여 장을
  드롭하는 버그가 있었다. 이제는 원본 스키마에 head 가 없으면 판정에서 제외
  (unknown) 하도록 `_resolve_label_conflict` 가 수정됐다.
"""
from __future__ import annotations

import pytest

from lib.manipulators.cls_merge_datasets import MergeDatasetsClassification
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

# ─────────────────────────────────────────────────────────────────
# 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_record(
    sha: str,
    file_name: str,
    labels: dict[str, list[str]],
    image_id: int | str = 1,
) -> ImageRecord:
    return ImageRecord(
        image_id=image_id,
        file_name=file_name,
        width=640,
        height=480,
        sha=sha,
        labels=labels,
    )


def _make_meta(
    dataset_id: str,
    head_schema: list[HeadSchema],
    records: list[ImageRecord],
) -> DatasetMeta:
    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=f"/fake/{dataset_id}",
        categories=[],
        image_records=records,
        head_schema=head_schema,
    )


def _permissive_params() -> dict[str, str]:
    return {
        "on_head_mismatch": "fill_empty",
        "on_class_set_mismatch": "multi_label_union",
        "on_label_conflict": "merge_if_compatible",
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
            _make_record("sha-a1", "images/sha-a1.jpg", {"wear": ["helmet"], "shared": ["s"]})
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
                "sha-b1", "images/sha-b1.jpg", {"visibility": ["seen"], "shared": ["s"]}
            )
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    head_names = [head.name for head in result.head_schema]
    # A 먼저, B 의 신규 head 가 뒤에.
    assert head_names == ["wear", "shared", "visibility"]
    # 이미지 2장 (SHA 겹치지 않음) — 모두 생존.
    assert len(result.image_records) == 2


def test_class_set_union_promotes_to_multi_label() -> None:
    """class 집합이 다르면 multi_label_union 옵션이 multi_label 을 True 로 승격.

    (compat 검증상 공통 class 1개 필요해 'common' 을 양쪽에 둔다.)
    """
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[HeadSchema(name="tag", multi_label=False, classes=["common", "x"])],
        records=[_make_record("sha-1", "images/sha-1.jpg", {"tag": ["x"]})],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[HeadSchema(name="tag", multi_label=False, classes=["common", "y"])],
        records=[_make_record("sha-2", "images/sha-2.jpg", {"tag": ["y"]})],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    assert len(result.head_schema) == 1
    assert result.head_schema[0].multi_label is True
    assert result.head_schema[0].classes == ["common", "x", "y"]


# ─────────────────────────────────────────────────────────────────
# 2. 회귀: fill_empty 가 만들어낸 head 는 unknown 취급 (버그 수정 보호)
# ─────────────────────────────────────────────────────────────────


def test_fill_empty_head_treated_as_unknown_not_conflict() -> None:
    """
    입력 A 는 head 'wear' 만, 입력 B 는 head 'hardhat_wear' 만 가진 상태에서
    동일 SHA 이미지가 양쪽에 있을 때, fill_empty + merge_if_compatible 가
    single_label_mismatch 로 드롭하지 않아야 한다.

    기대:
      - 드롭 0건
      - 결과 레코드 labels 에 wear/hardhat_wear 양쪽 모두 상대 쪽 값이 채워짐
    """
    shared_sha = "abc123"
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[
            HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"]),
            HeadSchema(name="visibility", multi_label=False, classes=["seen", "unseen"]),
        ],
        records=[
            _make_record(
                sha=shared_sha,
                file_name=f"images/{shared_sha}.jpg",
                labels={"wear": ["no_helmet"], "visibility": ["seen"]},
            ),
        ],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[
            HeadSchema(name="hardhat_wear", multi_label=False, classes=["no_helmet", "helmet"]),
            HeadSchema(name="visibility", multi_label=False, classes=["seen", "unseen"]),
        ],
        records=[
            _make_record(
                sha=shared_sha,
                file_name=f"images/{shared_sha}.jpg",
                labels={"hardhat_wear": ["no_helmet"], "visibility": ["seen"]},
            ),
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    # SHA dedup + 드롭 없음 → 1장만 남아야 한다.
    assert len(result.image_records) == 1
    merged = result.image_records[0]
    # 각 입력의 라벨이 상대 head 에도 채워져야 한다.
    assert merged.labels["wear"] == ["no_helmet"]
    assert merged.labels["hardhat_wear"] == ["no_helmet"]
    assert merged.labels["visibility"] == ["seen"]


def test_fill_empty_single_source_occurrence_keeps_label() -> None:
    """
    한쪽 입력에만 존재하는 SHA 는 단일 occurrence 이므로 충돌 경로에 들어가지 않고
    merged_head_names 에 맞춰 빈 head 가 [] 로 채워진 채 그대로 살아남는다.

    (compat 검증상 공통 head 1개 필요.)
    """
    shared = HeadSchema(name="shared", multi_label=False, classes=["s"])
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[
            HeadSchema(name="wear", multi_label=False, classes=["a"]),
            shared,
        ],
        records=[
            _make_record("sha-a", "images/sha-a.jpg", {"wear": ["a"], "shared": ["s"]}),
        ],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[
            HeadSchema(name="hardhat_wear", multi_label=False, classes=["a"]),
            shared,
        ],
        records=[
            _make_record(
                "sha-b", "images/sha-b.jpg", {"hardhat_wear": ["a"], "shared": ["s"]}
            ),
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    assert len(result.image_records) == 2
    by_sha = {rec.sha: rec for rec in result.image_records}
    # A 만 있던 SHA → hardhat_wear 는 fill_empty 로 [] 채워짐.
    assert by_sha["sha-a"].labels["wear"] == ["a"]
    assert by_sha["sha-a"].labels["hardhat_wear"] == []
    # B 만 있던 SHA → wear 는 fill_empty 로 [] 채워짐.
    assert by_sha["sha-b"].labels["hardhat_wear"] == ["a"]
    assert by_sha["sha-b"].labels["wear"] == []


# ─────────────────────────────────────────────────────────────────
# 3. 실제 single-label 충돌 → 드롭
# ─────────────────────────────────────────────────────────────────


def test_single_label_real_conflict_drops_image() -> None:
    """양쪽 입력 모두 head 가 있는데 값이 다르면 drop."""
    shared_sha = "conflict-sha"
    head = HeadSchema(name="wear", multi_label=False, classes=["no_helmet", "helmet"])
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[head],
        records=[_make_record(shared_sha, "images/x.jpg", {"wear": ["helmet"]})],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[head],
        records=[_make_record(shared_sha, "images/x.jpg", {"wear": ["no_helmet"]})],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    # single-label 실제 충돌 → 드롭되어 결과 비어있어야 한다.
    assert result.image_records == []


# ─────────────────────────────────────────────────────────────────
# 4. multi-label pos / explicit_neg / unknown
# ─────────────────────────────────────────────────────────────────


def test_multi_label_pos_neg_conflict_drops_image() -> None:
    """
    A 입력 원본 classes 에 'helmet' 이 있는데 라벨에는 없음(explicit_neg),
    B 입력에서는 라벨에 'helmet' 있음(pos) → 상충으로 drop.
    """
    shared_sha = "multi-sha"
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["helmet", "glasses"])
        ],
        records=[
            _make_record(
                shared_sha, "images/x.jpg", {"attrs": ["glasses"]}
            )
        ],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["helmet", "glasses"])
        ],
        records=[
            _make_record(
                shared_sha, "images/x.jpg", {"attrs": ["helmet"]}
            )
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    assert result.image_records == []


def test_multi_label_unknown_vs_pos_merges_to_union() -> None:
    """
    B 입력 원본 classes 에 'glasses' 자체가 없음(unknown) → A 의 pos 가 그대로 살아남음.
    """
    shared_sha = "unknown-sha"
    meta_a = _make_meta(
        dataset_id="a",
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["helmet", "glasses"])
        ],
        records=[
            _make_record(
                shared_sha, "images/x.jpg", {"attrs": ["helmet", "glasses"]}
            )
        ],
    )
    meta_b = _make_meta(
        dataset_id="b",
        head_schema=[
            HeadSchema(name="attrs", multi_label=True, classes=["helmet"])
        ],
        records=[
            _make_record(shared_sha, "images/x.jpg", {"attrs": ["helmet"]})
        ],
    )

    result = MergeDatasetsClassification().transform_annotation(
        [meta_a, meta_b], _permissive_params()
    )

    # 'glasses' 는 B 에게 unknown 이므로 충돌 아님 → union 결과 유지.
    assert len(result.image_records) == 1
    assert set(result.image_records[0].labels["attrs"]) == {"helmet", "glasses"}


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
