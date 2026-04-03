"""
COCO IO 모듈 테스트.

parse_coco_json()과 write_coco_json()의 정확성을 검증한다.
장난감 데이터(2장, 3개 annotation, 2개 category)를 사용.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.io.coco_io import parse_coco_json, write_coco_json
from app.pipeline.models import DatasetMeta
from tests.conftest import (
    CAR_BBOX,
    IMAGE_1_HEIGHT,
    IMAGE_1_WIDTH,
    IMAGE_2_HEIGHT,
    IMAGE_2_WIDTH,
    PERSON_BBOX,
    PERSON_BBOX_2,
)


# =============================================================================
# parse_coco_json 테스트
# =============================================================================


class TestParseCoco:
    """COCO JSON 파싱 테스트."""

    def test_parse_image_count(self, sample_coco_file: Path):
        """이미지 수가 정확히 파싱되는지 확인."""
        meta = parse_coco_json(sample_coco_file)
        assert meta.image_count == 2

    def test_parse_annotation_count(self, sample_coco_file: Path):
        """각 이미지의 annotation 수가 정확한지 확인."""
        meta = parse_coco_json(sample_coco_file)
        assert len(meta.image_records[0].annotations) == 2  # image_001: person + car
        assert len(meta.image_records[1].annotations) == 1  # image_002: person

    def test_parse_category_names(self, sample_coco_file: Path):
        """category name이 정확히 파싱되는지 확인."""
        meta = parse_coco_json(sample_coco_file)
        assert meta.category_names == ["person", "car"]

    def test_parse_bbox_values(self, sample_coco_file: Path):
        """bbox 좌표값이 원본 COCO absolute 그대로인지 확인."""
        meta = parse_coco_json(sample_coco_file)
        first_annotation = meta.image_records[0].annotations[0]
        assert first_annotation.bbox == PERSON_BBOX

    def test_parse_image_dimensions(self, sample_coco_file: Path):
        """이미지 width/height가 정확히 파싱되는지 확인."""
        meta = parse_coco_json(sample_coco_file)
        assert meta.image_records[0].width == IMAGE_1_WIDTH
        assert meta.image_records[0].height == IMAGE_1_HEIGHT
        assert meta.image_records[1].width == IMAGE_2_WIDTH
        assert meta.image_records[1].height == IMAGE_2_HEIGHT

    def test_parse_preserves_extra_fields(self, sample_coco_file: Path):
        """area, iscrowd 등 추가 필드가 Annotation.extra에 보존되는지 확인."""
        meta = parse_coco_json(sample_coco_file)
        first_annotation = meta.image_records[0].annotations[0]
        assert "area" in first_annotation.extra
        assert first_annotation.extra["area"] == PERSON_BBOX[2] * PERSON_BBOX[3]
        assert first_annotation.extra["iscrowd"] == 0

    def test_parse_supercategory_preserved(self, sample_coco_file: Path):
        """categories의 supercategory 필드가 보존되는지 확인."""
        meta = parse_coco_json(sample_coco_file)
        assert meta.categories[0]["supercategory"] == "human"
        assert meta.categories[1]["supercategory"] == "vehicle"

    def test_parse_annotation_format_is_coco(self, sample_coco_file: Path):
        """annotation_format이 'COCO'로 설정되는지 확인."""
        meta = parse_coco_json(sample_coco_file)
        assert meta.annotation_format == "COCO"

    def test_parse_dataset_id_and_storage_uri(self, sample_coco_file: Path):
        """dataset_id와 storage_uri가 인자값 그대로 설정되는지 확인."""
        meta = parse_coco_json(sample_coco_file, dataset_id="abc", storage_uri="raw/test")
        assert meta.dataset_id == "abc"
        assert meta.storage_uri == "raw/test"

    def test_parse_empty_annotations_image(self, tmp_path: Path):
        """annotation이 없는 이미지도 ImageRecord로 생성되는지 확인."""
        coco_data = {
            "images": [{"id": 1, "file_name": "empty.jpg", "width": 100, "height": 100}],
            "annotations": [],
            "categories": [{"id": 0, "name": "person"}],
        }
        json_path = tmp_path / "empty.json"
        json_path.write_text(json.dumps(coco_data))

        meta = parse_coco_json(json_path)
        assert meta.image_count == 1
        assert len(meta.image_records[0].annotations) == 0

    def test_parse_missing_required_keys(self, tmp_path: Path):
        """필수 키가 없으면 ValueError를 발생시키는지 확인."""
        bad_data = {"images": []}
        json_path = tmp_path / "bad.json"
        json_path.write_text(json.dumps(bad_data))

        with pytest.raises(ValueError, match="필수 키"):
            parse_coco_json(json_path)

    def test_parse_nonexistent_file(self):
        """존재하지 않는 파일 경로에 대해 FileNotFoundError를 발생시키는지 확인."""
        with pytest.raises(FileNotFoundError):
            parse_coco_json(Path("/nonexistent/path.json"))


# =============================================================================
# write_coco_json 테스트
# =============================================================================


class TestWriteCoco:
    """COCO JSON 쓰기 테스트."""

    def test_write_creates_valid_json(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """유효한 JSON 파일이 생성되는지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        assert "images" in data
        assert "annotations" in data
        assert "categories" in data

    def test_write_image_count(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """images 배열의 항목 수가 정확한지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        assert len(data["images"]) == 2

    def test_write_annotation_count(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """annotations 배열의 항목 수가 정확한지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        assert len(data["annotations"]) == 3

    def test_write_annotation_ids_sequential(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """annotation id가 1부터 순차적으로 생성되는지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        annotation_ids = [ann["id"] for ann in data["annotations"]]
        assert annotation_ids == [1, 2, 3]

    def test_write_area_computed(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """area 필드가 bbox w*h로 계산되는지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        first_annotation = data["annotations"][0]
        expected_area = PERSON_BBOX[2] * PERSON_BBOX[3]
        assert first_annotation["area"] == expected_area

    def test_write_iscrowd_default(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """iscrowd가 기본값 0으로 출력되는지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        for annotation in data["annotations"]:
            assert annotation["iscrowd"] == 0

    def test_write_categories(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """categories가 정확히 출력되는지 확인."""
        output_path = tmp_path / "output.json"
        write_coco_json(sample_dataset_meta_coco, output_path)

        with open(output_path, "r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        category_names = [cat["name"] for cat in data["categories"]]
        assert category_names == ["person", "car"]


# =============================================================================
# round-trip 테스트
# =============================================================================


class TestCocoRoundTrip:
    """COCO parse → write → re-parse round-trip 검증."""

    def test_roundtrip_preserves_data(self, sample_coco_file: Path, tmp_path: Path):
        """parse → write → re-parse 후 핵심 데이터가 동일한지 확인."""
        # 1단계: 원본 파싱
        original_meta = parse_coco_json(sample_coco_file)

        # 2단계: 쓰기
        output_path = tmp_path / "roundtrip.json"
        write_coco_json(original_meta, output_path)

        # 3단계: 재파싱
        reparsed_meta = parse_coco_json(output_path)

        # 검증: 이미지 수
        assert reparsed_meta.image_count == original_meta.image_count

        # 검증: 각 이미지의 annotation 수
        for idx in range(original_meta.image_count):
            assert len(reparsed_meta.image_records[idx].annotations) == len(
                original_meta.image_records[idx].annotations
            )

        # 검증: category names
        assert reparsed_meta.category_names == original_meta.category_names

        # 검증: bbox 값 동일
        for img_idx in range(original_meta.image_count):
            for ann_idx in range(len(original_meta.image_records[img_idx].annotations)):
                original_bbox = original_meta.image_records[img_idx].annotations[ann_idx].bbox
                reparsed_bbox = reparsed_meta.image_records[img_idx].annotations[ann_idx].bbox
                assert original_bbox == reparsed_bbox

        # 검증: file_name 동일
        for idx in range(original_meta.image_count):
            assert (
                reparsed_meta.image_records[idx].file_name
                == original_meta.image_records[idx].file_name
            )
