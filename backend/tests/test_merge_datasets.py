"""
det_merge_datasets Manipulator 단위 테스트.

통일포맷 전환 후:
  - categories는 list[str] (이름 기반, ID 없음)
  - annotation.category_name은 그대로 보존 (리매핑 불필요)
  - annotation_format 검증 삭제

테스트 영역:
  1. 카테고리 통합 (name union, 등장 순서 보존)
  2. 파일명 충돌 감지 + prefix (충돌만 적용, 비충돌 원본 유지)
  3. 이미지 레코드 병합 (image_id 재번호, extra 출처 정보)
  4. 매핑 테이블 구조 (rename 건만 기록)
  5. 에러 처리 (타입, 소스 수)
"""
from __future__ import annotations

import hashlib

import pytest

from lib.manipulators.det_merge_datasets import (
    MergeDatasets,
    _build_dataset_hash_table,
    _detect_file_name_collisions,
)
from lib.pipeline.pipeline_data_models import Annotation, DatasetMeta, ImageRecord


# ─────────────────────────────────────────────────────────────────
# 테스트용 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_annotation(category_name: str, bbox: list[float] | None = None) -> Annotation:
    return Annotation(
        annotation_type="BBOX",
        category_name=category_name,
        bbox=bbox or [10.0, 20.0, 30.0, 40.0],
    )


def _make_record(
    image_id: int,
    file_name: str,
    annotations: list[Annotation] | None = None,
    width: int = 640,
    height: int = 480,
) -> ImageRecord:
    return ImageRecord(
        image_id=image_id,
        file_name=file_name,
        width=width,
        height=height,
        annotations=annotations or [],
    )


def _make_meta(
    dataset_id: str,
    categories: list[str],
    image_records: list[ImageRecord],
    storage_uri: str = "",
    dataset_name: str | None = None,
) -> DatasetMeta:
    extra = {}
    if dataset_name:
        extra["dataset_name"] = dataset_name
    if not storage_uri:
        storage_uri = f"source/{dataset_id}/train/v1.0.0"
    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=storage_uri,
        categories=categories,
        image_records=image_records,
        extra=extra,
    )


# ─────────────────────────────────────────────────────────────────
# 1. 카테고리 통합 테스트
# ─────────────────────────────────────────────────────────────────


class TestCategoryUnification:
    """카테고리 이름 기준 union (등장 순서 보존) 테스트."""

    def test_identical_categories_across_sources(self):
        """동일 카테고리를 가진 두 소스 → 중복 없이 하나로 통합."""
        meta_a = _make_meta("ds-a", ["person", "car"], [_make_record(1, "a.jpg")])
        meta_b = _make_meta("ds-b", ["person", "car"], [_make_record(1, "b.jpg")])

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        assert result.categories == ["person", "car"]

    def test_disjoint_categories(self):
        """완전히 다른 카테고리 → union."""
        meta_a = _make_meta("ds-a", ["person"], [_make_record(1, "a.jpg")])
        meta_b = _make_meta("ds-b", ["dog"], [_make_record(1, "b.jpg")])

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        assert set(result.categories) == {"person", "dog"}

    def test_overlapping_categories_preserve_order(self):
        """겹치는 카테고리 → 등장 순서 보존, 중복 제거."""
        meta_a = _make_meta("ds-a", ["person", "car"], [_make_record(1, "a.jpg")])
        meta_b = _make_meta("ds-b", ["car", "truck"], [_make_record(1, "b.jpg")])

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        assert result.categories == ["person", "car", "truck"]

    def test_three_sources_overlapping(self):
        """3개 소스의 겹치는 카테고리 통합."""
        meta_a = _make_meta("ds-a", ["person"], [_make_record(1, "a.jpg")])
        meta_b = _make_meta("ds-b", ["person", "car"], [_make_record(1, "b.jpg")])
        meta_c = _make_meta("ds-c", ["car", "bicycle"], [_make_record(1, "c.jpg")])

        result = MergeDatasets().transform_annotation([meta_a, meta_b, meta_c], {})

        assert result.categories == ["person", "car", "bicycle"]

    def test_cross_format_merge_preserves_annotations(self):
        """
        통일포맷 핵심 시나리오: COCO 기원 + YOLO 기원 데이터를 merge할 때
        category_name이 동일하면 자연스럽게 통합되고, annotation이 모두 보존된다.

        내부적으로 annotation_format 구분이 없으므로 별도 검증/변환 없이 merge됨.
        """
        # COCO에서 파싱된 데이터 (person, car)
        coco_origin = _make_meta(
            "ds-coco",
            ["person", "car"],
            [
                _make_record(1, "coco_001.jpg", [
                    _make_annotation("person", [100, 200, 50, 80]),
                    _make_annotation("car", [300, 100, 120, 60]),
                ]),
            ],
            dataset_name="coco_dataset",
        )
        # YOLO에서 파싱된 데이터 (person, truck — car 대신 truck)
        yolo_origin = _make_meta(
            "ds-yolo",
            ["person", "truck"],
            [
                _make_record(1, "yolo_001.jpg", [
                    _make_annotation("person", [50, 60, 40, 70]),
                    _make_annotation("truck", [200, 150, 100, 80]),
                ]),
            ],
            dataset_name="yolo_dataset",
        )

        result = MergeDatasets().transform_annotation([coco_origin, yolo_origin], {})

        # 카테고리: union 순서 보존
        assert result.categories == ["person", "car", "truck"]
        # 전체 이미지 2장, annotation 4개 보존
        assert result.image_count == 2
        all_annotations = [ann for rec in result.image_records for ann in rec.annotations]
        assert len(all_annotations) == 4
        annotation_names = [ann.category_name for ann in all_annotations]
        assert annotation_names.count("person") == 2
        assert annotation_names.count("car") == 1
        assert annotation_names.count("truck") == 1


# ─────────────────────────────────────────────────────────────────
# 2. 파일명 충돌 감지 테스트
# ─────────────────────────────────────────────────────────────────


class TestDetectFileNameCollisions:
    """파일명 충돌 감지 로직 테스트."""

    def test_no_collision(self):
        """충돌 없음 → 빈 집합."""
        meta_a = _make_meta("ds-a", [], [_make_record(1, "img_a.jpg")])
        meta_b = _make_meta("ds-b", [], [_make_record(1, "img_b.jpg")])

        collisions = _detect_file_name_collisions([meta_a, meta_b])
        assert collisions == set()

    def test_single_collision(self):
        """동일 파일명이 2개 소스에 존재."""
        meta_a = _make_meta("ds-a", [], [_make_record(1, "000001.jpg")])
        meta_b = _make_meta("ds-b", [], [_make_record(1, "000001.jpg")])

        collisions = _detect_file_name_collisions([meta_a, meta_b])
        assert collisions == {"000001.jpg"}

    def test_three_way_collision(self):
        """동일 파일명이 3개 소스에 존재."""
        meta_a = _make_meta("ds-a", [], [_make_record(1, "000001.jpg")])
        meta_b = _make_meta("ds-b", [], [_make_record(1, "000001.jpg")])
        meta_c = _make_meta("ds-c", [], [_make_record(1, "000001.jpg")])

        collisions = _detect_file_name_collisions([meta_a, meta_b, meta_c])
        assert collisions == {"000001.jpg"}

    def test_partial_collision(self):
        """일부만 충돌하는 경우."""
        meta_a = _make_meta("ds-a", [], [
            _make_record(1, "000001.jpg"),
            _make_record(2, "unique_a.jpg"),
        ])
        meta_b = _make_meta("ds-b", [], [
            _make_record(1, "000001.jpg"),
            _make_record(2, "unique_b.jpg"),
        ])

        collisions = _detect_file_name_collisions([meta_a, meta_b])
        assert collisions == {"000001.jpg"}

    def test_same_dataset_duplicate_not_collision(self):
        """같은 소스 내 동일 파일명은 충돌로 감지하지 않음 (단일 소스)."""
        meta_a = _make_meta("ds-a", [], [
            _make_record(1, "000001.jpg"),
            _make_record(2, "000001.jpg"),
        ])
        meta_b = _make_meta("ds-b", [], [_make_record(1, "unique.jpg")])

        collisions = _detect_file_name_collisions([meta_a, meta_b])
        assert collisions == set()


# ─────────────────────────────────────────────────────────────────
# 3. dataset hash 테스트
# ─────────────────────────────────────────────────────────────────


class TestBuildDatasetHashTable:
    """소스별 hash 생성 테스트."""

    def test_hash_deterministic(self):
        """동일 dataset_id → 동일 hash."""
        meta = _make_meta("test-id-123", [], [], dataset_name="coco8")
        table = _build_dataset_hash_table([meta])

        expected_hash = hashlib.md5("test-id-123".encode()).hexdigest()[:4]
        assert table["test-id-123"] == ("coco8", expected_hash)

    def test_hash_uses_dataset_name_from_extra(self):
        """extra["dataset_name"]이 있으면 표시용 이름으로 사용."""
        meta = _make_meta("abc-123", [], [], dataset_name="my_dataset")
        table = _build_dataset_hash_table([meta])

        display_name, _ = table["abc-123"]
        assert display_name == "my_dataset"

    def test_hash_fallback_to_dataset_id_prefix(self):
        """extra["dataset_name"]이 없으면 dataset_id[:8] 사용."""
        meta = _make_meta("abcdefgh-1234-5678", [], [])
        table = _build_dataset_hash_table([meta])

        display_name, _ = table["abcdefgh-1234-5678"]
        assert display_name == "abcdefgh"

    def test_different_ids_produce_different_hashes(self):
        """다른 dataset_id → 다른 hash (높은 확률)."""
        meta_a = _make_meta("dataset-aaa", [], [])
        meta_b = _make_meta("dataset-bbb", [], [])
        table = _build_dataset_hash_table([meta_a, meta_b])

        _, hash_a = table["dataset-aaa"]
        _, hash_b = table["dataset-bbb"]
        assert hash_a != hash_b


# ─────────────────────────────────────────────────────────────────
# 4. MergeDatasets 통합 테스트 (transform_annotation)
# ─────────────────────────────────────────────────────────────────


class TestMergeDatasetsTransformAnnotation:
    """MergeDatasets.transform_annotation() 전체 흐름 테스트."""

    def _build_two_source_metas(self) -> tuple[DatasetMeta, DatasetMeta]:
        """공통 테스트용 2개 소스 생성 (파일명 충돌 포함)."""
        meta_a = _make_meta(
            dataset_id="ds-a",
            categories=["person", "car"],
            image_records=[
                _make_record(1, "000001.jpg", [_make_annotation("person"), _make_annotation("car")]),
                _make_record(2, "unique_a.jpg", [_make_annotation("person")]),
            ],
            dataset_name="coco8",
            storage_uri="source/coco8/train/v1.0.0",
        )
        meta_b = _make_meta(
            dataset_id="ds-b",
            categories=["person", "truck"],
            image_records=[
                _make_record(1, "000001.jpg", [_make_annotation("person"), _make_annotation("truck")]),
                _make_record(2, "unique_b.jpg", [_make_annotation("truck")]),
            ],
            dataset_name="visdrone",
            storage_uri="source/visdrone/train/v1.0.0",
        )
        return meta_a, meta_b

    def test_basic_merge_image_count(self):
        """2개 소스 병합 → 총 이미지 수 = 합계."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})
        assert result.image_count == 4

    def test_image_ids_sequential(self):
        """병합 후 image_id가 1부터 순차적으로 재번호."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        image_ids = [r.image_id for r in result.image_records]
        assert image_ids == [1, 2, 3, 4]

    def test_colliding_file_names_get_prefix(self):
        """충돌 파일명에만 prefix가 적용된다."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        file_names = [r.file_name for r in result.image_records]
        hash_a = hashlib.md5("ds-a".encode()).hexdigest()[:4]
        hash_b = hashlib.md5("ds-b".encode()).hexdigest()[:4]

        assert f"coco8_{hash_a}_000001.jpg" in file_names
        assert f"visdrone_{hash_b}_000001.jpg" in file_names
        assert "unique_a.jpg" in file_names
        assert "unique_b.jpg" in file_names

    def test_non_colliding_file_names_unchanged(self):
        """충돌 없는 파일명은 원본 그대로 유지."""
        meta_a = _make_meta("ds-a", ["cat"], [
            _make_record(1, "alpha.jpg"),
        ], dataset_name="alpha_ds")
        meta_b = _make_meta("ds-b", ["cat"], [
            _make_record(1, "beta.jpg"),
        ], dataset_name="beta_ds")

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        file_names = [r.file_name for r in result.image_records]
        assert file_names == ["alpha.jpg", "beta.jpg"]

    def test_file_name_mapping_only_renamed_files(self):
        """매핑 테이블에는 rename된 파일만 기록된다."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        mapping = result.extra["file_name_mapping"]
        assert "000001.jpg" in mapping.get("ds-a", {})
        assert "000001.jpg" in mapping.get("ds-b", {})
        assert "unique_a.jpg" not in mapping.get("ds-a", {})
        assert "unique_b.jpg" not in mapping.get("ds-b", {})

    def test_categories_unified_by_name(self):
        """카테고리가 이름 기준으로 통합된다 (등장 순서 보존)."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        assert set(result.categories) == {"person", "car", "truck"}
        # 등장 순서: person, car (ds-a), truck (ds-b)
        assert result.categories == ["person", "car", "truck"]

    def test_annotation_category_names_preserved(self):
        """병합 후 annotation의 category_name이 그대로 보존."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        # ds-a 첫 이미지: person, car
        record_a_first = result.image_records[0]
        assert record_a_first.annotations[0].category_name == "person"
        assert record_a_first.annotations[1].category_name == "car"

        # ds-b 첫 이미지: person, truck
        record_b_first = result.image_records[2]
        assert record_b_first.annotations[0].category_name == "person"
        assert record_b_first.annotations[1].category_name == "truck"

    def test_extra_contains_source_info_for_all_records(self):
        """모든 ImageRecord.extra에 출처 정보가 포함된다."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        for record in result.image_records:
            assert "source_dataset_id" in record.extra
            assert "source_storage_uri" in record.extra
            assert "original_file_name" in record.extra

        assert result.image_records[0].extra["source_dataset_id"] == "ds-a"
        assert result.image_records[0].extra["source_storage_uri"] == "source/coco8/train/v1.0.0"
        assert result.image_records[0].extra["original_file_name"] == "000001.jpg"

        assert result.image_records[2].extra["source_dataset_id"] == "ds-b"
        assert result.image_records[2].extra["source_storage_uri"] == "source/visdrone/train/v1.0.0"

    def test_extra_source_dataset_ids(self):
        """병합 결과 extra에 source_dataset_ids 목록 포함."""
        meta_a, meta_b = self._build_two_source_metas()
        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})
        assert result.extra["source_dataset_ids"] == ["ds-a", "ds-b"]

    def test_three_sources_merge(self):
        """3개 소스 병합 + 3-way 파일명 충돌."""
        common_record = lambda: _make_record(1, "shared.jpg", [_make_annotation("cat")])
        meta_a = _make_meta("ds-a", ["cat"], [common_record()], dataset_name="alpha")
        meta_b = _make_meta("ds-b", ["cat"], [common_record()], dataset_name="beta")
        meta_c = _make_meta("ds-c", ["cat"], [common_record()], dataset_name="gamma")

        result = MergeDatasets().transform_annotation([meta_a, meta_b, meta_c], {})

        assert result.image_count == 3
        file_names = [r.file_name for r in result.image_records]
        assert all("shared.jpg" in fn for fn in file_names)
        assert len(set(file_names)) == 3

    def test_preserves_existing_extra_fields(self):
        """기존 ImageRecord.extra 필드가 병합 후에도 보존된다."""
        record_with_extra = ImageRecord(
            image_id=1,
            file_name="test.jpg",
            width=640,
            height=480,
            annotations=[],
            extra={"custom_field": "preserved_value"},
        )
        meta_a = _make_meta("ds-a", ["cat"], [record_with_extra], dataset_name="alpha")
        meta_b = _make_meta("ds-b", ["cat"], [
            _make_record(1, "other.jpg"),
        ], dataset_name="beta")

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        first_record = result.image_records[0]
        assert first_record.extra["custom_field"] == "preserved_value"
        assert first_record.extra["source_dataset_id"] == "ds-a"


# ─────────────────────────────────────────────────────────────────
# 5. 에러 처리 테스트
# ─────────────────────────────────────────────────────────────────


class TestMergeDatasetsErrors:
    """에러 케이스 테스트."""

    def test_single_meta_raises_type_error(self):
        """단건 DatasetMeta 입력 → TypeError."""
        meta = _make_meta("ds-a", [], [])
        with pytest.raises(TypeError, match="list"):
            MergeDatasets().transform_annotation(meta, {})

    def test_single_element_list_raises_value_error(self):
        """리스트지만 1개뿐 → ValueError."""
        meta = _make_meta("ds-a", ["cat"], [_make_record(1, "a.jpg")])
        with pytest.raises(ValueError, match="2개 이상"):
            MergeDatasets().transform_annotation([meta], {})

    def test_accepts_multi_input_attribute(self):
        """accepts_multi_input 클래스 속성이 True."""
        assert MergeDatasets.accepts_multi_input is True

    def test_name_property(self):
        """name 속성이 'det_merge_datasets'."""
        assert MergeDatasets().name == "det_merge_datasets"
