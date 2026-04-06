"""
merge_datasets Manipulator 단위 테스트.

테스트 영역:
  1. 카테고리 통합 (동일/겹침/충돌)
  2. 파일명 충돌 감지 + prefix (충돌만 적용, 비충돌 원본 유지)
  3. 이미지 레코드 병합 (image_id 재번호, extra 출처 정보, annotation remap)
  4. 매핑 테이블 구조 (rename 건만 기록)
  5. 에러 처리 (타입, 소스 수, 포맷 불일치)
"""
from __future__ import annotations

import hashlib

import pytest

from lib.manipulators.merge_datasets import (
    MergeDatasets,
    _build_dataset_hash_table,
    _build_unified_categories,
    _detect_file_name_collisions,
    _remap_annotations,
    _validate_annotation_formats,
)
from lib.pipeline.pipeline_data_models import Annotation, DatasetMeta, ImageRecord


# ─────────────────────────────────────────────────────────────────
# 테스트용 팩토리 헬퍼
# ─────────────────────────────────────────────────────────────────


def _make_annotation(category_id: int, bbox: list[float] | None = None) -> Annotation:
    return Annotation(
        annotation_type="BBOX",
        category_id=category_id,
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
    categories: list[dict],
    image_records: list[ImageRecord],
    annotation_format: str = "COCO",
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
        annotation_format=annotation_format,
        categories=categories,
        image_records=image_records,
        extra=extra,
    )


# ─────────────────────────────────────────────────────────────────
# 1. 카테고리 통합 테스트
# ─────────────────────────────────────────────────────────────────


class TestBuildUnifiedCategories:
    """카테고리 이름 기준 통합 + category_id 재매핑 테스트."""

    def test_identical_categories_across_sources(self):
        """동일 카테고리를 가진 두 소스 → 중복 없이 하나로 통합."""
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "person"}, {"id": 1, "name": "car"}], [])
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "person"}, {"id": 1, "name": "car"}], [])

        unified, remap = _build_unified_categories([meta_a, meta_b])

        assert len(unified) == 2
        assert unified[0] == {"id": 0, "name": "person"}
        assert unified[1] == {"id": 1, "name": "car"}
        # 매핑 변경 없음
        assert remap["ds-a"] == {0: 0, 1: 1}
        assert remap["ds-b"] == {0: 0, 1: 1}

    def test_disjoint_categories(self):
        """완전히 다른 카테고리 → union으로 합침."""
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "person"}], [])
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "dog"}], [])

        unified, remap = _build_unified_categories([meta_a, meta_b])

        assert len(unified) == 2
        names = {c["name"] for c in unified}
        assert names == {"person", "dog"}
        # COCO ID 보존: person이 id=0을 먼저 차지, dog의 id=0은 충돌 → 91 할당
        assert remap["ds-a"][0] == 0
        assert remap["ds-b"][0] == 91

    def test_same_id_different_name_conflict(self):
        """동일 ID에 다른 이름 → 이름 기준으로 각각 새 ID 할당."""
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "person"}, {"id": 1, "name": "car"}], [])
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "car"}, {"id": 1, "name": "truck"}], [])

        unified, remap = _build_unified_categories([meta_a, meta_b])

        # person(0), car(1), truck(2)
        assert len(unified) == 3
        name_to_id = {c["name"]: c["id"] for c in unified}

        # ds-a: person 0→0, car 1→1
        assert remap["ds-a"][0] == name_to_id["person"]
        assert remap["ds-a"][1] == name_to_id["car"]
        # ds-b: car 0→car의 통합 id, truck 1→truck의 통합 id
        assert remap["ds-b"][0] == name_to_id["car"]
        assert remap["ds-b"][1] == name_to_id["truck"]

    def test_three_sources_overlapping(self):
        """3개 소스의 겹치는 카테고리 통합."""
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "person"}], [])
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "person"}, {"id": 1, "name": "car"}], [])
        meta_c = _make_meta("ds-c", [{"id": 5, "name": "car"}, {"id": 6, "name": "bicycle"}], [])

        unified, remap = _build_unified_categories([meta_a, meta_b, meta_c])

        assert len(unified) == 3
        name_to_id = {c["name"]: c["id"] for c in unified}
        assert remap["ds-c"][5] == name_to_id["car"]
        assert remap["ds-c"][6] == name_to_id["bicycle"]


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
            _make_record(2, "000001.jpg"),  # 같은 소스 내 중복 (비정상이지만 충돌은 아님)
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
# 4. annotation 재매핑 테스트
# ─────────────────────────────────────────────────────────────────


class TestRemapAnnotations:
    """annotation category_id 재매핑 테스트."""

    def test_remap_category_ids(self):
        """category_id가 매핑 테이블에 따라 변경된다."""
        annotations = [_make_annotation(0), _make_annotation(1)]
        remap = {0: 5, 1: 10}

        result = _remap_annotations(annotations, remap)

        assert result[0].category_id == 5
        assert result[1].category_id == 10

    def test_remap_preserves_other_fields(self):
        """재매핑 시 bbox 등 다른 필드는 보존된다."""
        annotation = Annotation(
            annotation_type="BBOX",
            category_id=0,
            bbox=[1.0, 2.0, 3.0, 4.0],
            extra={"area": 12.0, "iscrowd": 0},
        )
        result = _remap_annotations([annotation], {0: 99})

        assert result[0].bbox == [1.0, 2.0, 3.0, 4.0]
        assert result[0].extra == {"area": 12.0, "iscrowd": 0}
        assert result[0].annotation_type == "BBOX"

    def test_remap_missing_id_keeps_original(self):
        """매핑에 없는 category_id는 원본 유지."""
        annotations = [_make_annotation(999)]
        result = _remap_annotations(annotations, {0: 5})

        assert result[0].category_id == 999

    def test_remap_does_not_mutate_original(self):
        """원본 annotation은 수정되지 않는다."""
        original = _make_annotation(0)
        _remap_annotations([original], {0: 99})

        assert original.category_id == 0


# ─────────────────────────────────────────────────────────────────
# 5. 포맷 검증 테스트
# ─────────────────────────────────────────────────────────────────


class TestValidateAnnotationFormats:
    """annotation_format 일치 검증 테스트."""

    def test_same_format_passes(self):
        """동일 포맷 → 통과."""
        meta_a = _make_meta("ds-a", [], [], annotation_format="COCO")
        meta_b = _make_meta("ds-b", [], [], annotation_format="COCO")

        _validate_annotation_formats([meta_a, meta_b])  # 예외 없으면 성공

    def test_case_insensitive_comparison(self):
        """대소문자 무관하게 비교."""
        meta_a = _make_meta("ds-a", [], [], annotation_format="COCO")
        meta_b = _make_meta("ds-b", [], [], annotation_format="coco")

        _validate_annotation_formats([meta_a, meta_b])

    def test_different_formats_raises(self):
        """다른 포맷 → ValueError."""
        meta_a = _make_meta("ds-a", [], [], annotation_format="COCO")
        meta_b = _make_meta("ds-b", [], [], annotation_format="YOLO")

        with pytest.raises(ValueError, match="annotation_format"):
            _validate_annotation_formats([meta_a, meta_b])


# ─────────────────────────────────────────────────────────────────
# 6. MergeDatasets 통합 테스트 (transform_annotation)
# ─────────────────────────────────────────────────────────────────


class TestMergeDatasetsTransformAnnotation:
    """MergeDatasets.transform_annotation() 전체 흐름 테스트."""

    def _build_two_source_metas(self) -> tuple[DatasetMeta, DatasetMeta]:
        """공통 테스트용 2개 소스 생성 (파일명 충돌 포함)."""
        meta_a = _make_meta(
            dataset_id="ds-a",
            categories=[{"id": 0, "name": "person"}, {"id": 1, "name": "car"}],
            image_records=[
                _make_record(1, "000001.jpg", [_make_annotation(0), _make_annotation(1)]),
                _make_record(2, "unique_a.jpg", [_make_annotation(0)]),
            ],
            dataset_name="coco8",
            storage_uri="source/coco8/train/v1.0.0",
        )
        meta_b = _make_meta(
            dataset_id="ds-b",
            categories=[{"id": 0, "name": "person"}, {"id": 1, "name": "truck"}],
            image_records=[
                _make_record(1, "000001.jpg", [_make_annotation(0), _make_annotation(1)]),
                _make_record(2, "unique_b.jpg", [_make_annotation(1)]),
            ],
            dataset_name="visdrone",
            storage_uri="source/visdrone/train/v1.0.0",
        )
        return meta_a, meta_b

    def test_basic_merge_image_count(self):
        """2개 소스 병합 → 총 이미지 수 = 합계."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        assert result.image_count == 4  # 2 + 2

    def test_image_ids_sequential(self):
        """병합 후 image_id가 1부터 순차적으로 재번호."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        image_ids = [r.image_id for r in result.image_records]
        assert image_ids == [1, 2, 3, 4]

    def test_colliding_file_names_get_prefix(self):
        """충돌 파일명에만 prefix가 적용된다."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        file_names = [r.file_name for r in result.image_records]
        hash_a = hashlib.md5("ds-a".encode()).hexdigest()[:4]
        hash_b = hashlib.md5("ds-b".encode()).hexdigest()[:4]

        # 충돌 파일: prefix ���용
        assert f"coco8_{hash_a}_000001.jpg" in file_names
        assert f"visdrone_{hash_b}_000001.jpg" in file_names
        # 비충돌 파일: 원본 유지
        assert "unique_a.jpg" in file_names
        assert "unique_b.jpg" in file_names

    def test_non_colliding_file_names_unchanged(self):
        """충돌 없는 파일명은 원본 그대로 유지."""
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "cat"}], [
            _make_record(1, "alpha.jpg"),
        ], dataset_name="alpha_ds")
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "cat"}], [
            _make_record(1, "beta.jpg"),
        ], dataset_name="beta_ds")

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        file_names = [r.file_name for r in result.image_records]
        assert file_names == ["alpha.jpg", "beta.jpg"]

    def test_file_name_mapping_only_renamed_files(self):
        """매핑 테이블에는 rename된 파일만 기록된다."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        mapping = result.extra["file_name_mapping"]
        # 충돌 파일(000001.jpg)만 기록
        assert "000001.jpg" in mapping.get("ds-a", {})
        assert "000001.jpg" in mapping.get("ds-b", {})
        # 비충돌 파일은 기록 안 됨
        assert "unique_a.jpg" not in mapping.get("ds-a", {})
        assert "unique_b.jpg" not in mapping.get("ds-b", {})

    def test_categories_unified_by_name(self):
        """카테고리가 이름 기준으로 통합된다."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        category_names = {c["name"] for c in result.categories}
        assert category_names == {"person", "car", "truck"}
        # COCO 포맷: 원본 ID 보존 — person=0, car=1, truck은 id=1 충돌이므로 91 할당
        name_to_id = {c["name"]: c["id"] for c in result.categories}
        assert name_to_id["person"] == 0
        assert name_to_id["car"] == 1
        assert name_to_id["truck"] == 91

    def test_annotation_category_ids_remapped(self):
        """병합 후 annotation의 category_id가 통합된 ID로 재매핑."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        name_to_id = {c["name"]: c["id"] for c in result.categories}

        # ds-a의 첫 이미지: person(0→person_id), car(1→car_id)
        record_a_first = result.image_records[0]
        assert record_a_first.annotations[0].category_id == name_to_id["person"]
        assert record_a_first.annotations[1].category_id == name_to_id["car"]

        # ds-b의 첫 이미지: person(0→person_id), truck(1→truck_id)
        record_b_first = result.image_records[2]
        assert record_b_first.annotations[0].category_id == name_to_id["person"]
        assert record_b_first.annotations[1].category_id == name_to_id["truck"]

    def test_extra_contains_source_info_for_all_records(self):
        """모든 ImageRecord.extra에 출처 정보가 포함된다 (rename 여부 무관)."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        for record in result.image_records:
            assert "source_dataset_id" in record.extra
            assert "source_storage_uri" in record.extra
            assert "original_file_name" in record.extra

        # ds-a 레코드 확인
        assert result.image_records[0].extra["source_dataset_id"] == "ds-a"
        assert result.image_records[0].extra["source_storage_uri"] == "source/coco8/train/v1.0.0"
        assert result.image_records[0].extra["original_file_name"] == "000001.jpg"

        # ds-b 레코드 확인
        assert result.image_records[2].extra["source_dataset_id"] == "ds-b"
        assert result.image_records[2].extra["source_storage_uri"] == "source/visdrone/train/v1.0.0"

    def test_extra_source_dataset_ids(self):
        """��합 결과 extra에 source_dataset_ids 목록 포함."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        assert result.extra["source_dataset_ids"] == ["ds-a", "ds-b"]

    def test_annotation_format_preserved(self):
        """병합 결과의 annotation_format은 소스와 동일."""
        meta_a, meta_b = self._build_two_source_metas()
        manipulator = MergeDatasets()

        result = manipulator.transform_annotation([meta_a, meta_b], {})

        assert result.annotation_format == "COCO"

    def test_three_sources_merge(self):
        """3개 소스 병합 + 3-way 파일명 충돌."""
        common_record = lambda ds_id: _make_record(1, "shared.jpg", [_make_annotation(0)])
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "cat"}], [common_record("ds-a")], dataset_name="alpha")
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "cat"}], [common_record("ds-b")], dataset_name="beta")
        meta_c = _make_meta("ds-c", [{"id": 0, "name": "cat"}], [common_record("ds-c")], dataset_name="gamma")

        result = MergeDatasets().transform_annotation([meta_a, meta_b, meta_c], {})

        assert result.image_count == 3
        file_names = [r.file_name for r in result.image_records]
        # 모든 파일이 prefix 적용 (3-way 충돌)
        assert all("shared.jpg" in fn for fn in file_names)
        assert len(set(file_names)) == 3  # 전부 고유

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
        meta_a = _make_meta("ds-a", [{"id": 0, "name": "cat"}], [record_with_extra], dataset_name="alpha")
        meta_b = _make_meta("ds-b", [{"id": 0, "name": "cat"}], [
            _make_record(1, "other.jpg"),
        ], dataset_name="beta")

        result = MergeDatasets().transform_annotation([meta_a, meta_b], {})

        # 기존 extra 필드 보존 + 새 출처 정보 추가
        first_record = result.image_records[0]
        assert first_record.extra["custom_field"] == "preserved_value"
        assert first_record.extra["source_dataset_id"] == "ds-a"


# ─────────────────────────────────────────────────────────────────
# 7. 에러 처리 테스트
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
        meta = _make_meta("ds-a", [{"id": 0, "name": "cat"}], [_make_record(1, "a.jpg")])
        with pytest.raises(ValueError, match="2개 이상"):
            MergeDatasets().transform_annotation([meta], {})

    def test_format_mismatch_raises_value_error(self):
        """annotation_format 불일치 → ValueError."""
        meta_a = _make_meta("ds-a", [], [], annotation_format="COCO")
        meta_b = _make_meta("ds-b", [], [], annotation_format="YOLO")

        with pytest.raises(ValueError, match="annotation_format"):
            MergeDatasets().transform_annotation([meta_a, meta_b], {})

    def test_accepts_multi_input_attribute(self):
        """accepts_multi_input 클래스 속성이 True."""
        assert MergeDatasets.accepts_multi_input is True

    def test_name_property(self):
        """name 속성이 'merge_datasets'."""
        assert MergeDatasets().name == "merge_datasets"
