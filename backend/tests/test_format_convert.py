"""
포맷 변환 Manipulator 테스트.

통일포맷 전환 이후 det_format_convert_to_yolo/coco는 no-op이다.
입력을 deep copy하여 그대로 반환하는지만 검증한다.
IO round-trip 통합 테스트는 별도로 유지.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.manipulators.format_convert import FormatConvertToCoco, FormatConvertToYolo
from app.pipeline.io.coco_io import parse_coco_json, write_coco_json
from app.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from app.pipeline.pipeline_data_models import DatasetMeta
from tests.conftest import (
    CAR_BBOX,
    IMAGE_1_HEIGHT,
    IMAGE_1_WIDTH,
    IMAGE_2_HEIGHT,
    IMAGE_2_WIDTH,
    PERSON_BBOX,
    PERSON_BBOX_2,
)

_COORD_TOLERANCE = 1e-3


# =============================================================================
# FormatConvertToYolo 테스트 (no-op)
# =============================================================================


class TestFormatConvertToYolo:
    """COCO → YOLO 변환 Manipulator 테스트 (통일포맷: no-op)."""

    def test_name_matches_db_seed(self):
        """name 속성이 DB seed의 manipulator name과 일치하는지 확인."""
        converter = FormatConvertToYolo()
        assert converter.name == "det_format_convert_to_yolo"

    def test_noop_returns_identical_data(self, sample_dataset_meta_coco: DatasetMeta):
        """통일포맷에서 no-op: 입력과 동일한 데이터를 반환."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})

        assert result.categories == sample_dataset_meta_coco.categories
        assert result.image_count == sample_dataset_meta_coco.image_count

    def test_preserves_bbox_values(self, sample_dataset_meta_coco: DatasetMeta):
        """변환 후에도 bbox 값이 동일한지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})

        assert result.image_records[0].annotations[0].bbox == PERSON_BBOX
        assert result.image_records[0].annotations[1].bbox == CAR_BBOX
        assert result.image_records[1].annotations[0].bbox == PERSON_BBOX_2

    def test_preserves_category_names(self, sample_dataset_meta_coco: DatasetMeta):
        """category_name이 그대로 보존되는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})

        assert result.image_records[0].annotations[0].category_name == "person"
        assert result.image_records[0].annotations[1].category_name == "car"

    def test_does_not_mutate_input(self, sample_dataset_meta_coco: DatasetMeta):
        """원본 DatasetMeta가 변경되지 않는지 확인 (deep copy)."""
        converter = FormatConvertToYolo()
        original_categories = sample_dataset_meta_coco.categories[:]
        original_category_name = sample_dataset_meta_coco.image_records[0].annotations[0].category_name
        converter.transform_annotation(sample_dataset_meta_coco, params={})
        assert sample_dataset_meta_coco.categories == original_categories
        assert sample_dataset_meta_coco.image_records[0].annotations[0].category_name == original_category_name

    def test_no_image_manipulation(self, sample_dataset_meta_coco: DatasetMeta):
        """build_image_manipulation()이 빈 리스트를 반환하는지 확인."""
        converter = FormatConvertToYolo()
        specs = converter.build_image_manipulation(
            sample_dataset_meta_coco.image_records[0], params={},
        )
        assert specs == []

    def test_rejects_list_input(self, sample_dataset_meta_coco: DatasetMeta):
        """list 입력 시 TypeError를 발생시키는지 확인 (PER_SOURCE 전용)."""
        converter = FormatConvertToYolo()
        with pytest.raises(TypeError, match="PER_SOURCE"):
            converter.transform_annotation([sample_dataset_meta_coco], params={})


# =============================================================================
# FormatConvertToCoco 테스트 (no-op)
# =============================================================================


class TestFormatConvertToCoco:
    """YOLO → COCO 변환 Manipulator 테스트 (통일포맷: no-op)."""

    def test_name_matches_db_seed(self):
        """name 속성이 DB seed의 manipulator name과 일치하는지 확인."""
        converter = FormatConvertToCoco()
        assert converter.name == "det_format_convert_to_coco"

    def test_noop_returns_identical_data(self, sample_dataset_meta_yolo: DatasetMeta):
        """통일포맷에서 no-op: 입력과 동일한 데이터를 반환."""
        converter = FormatConvertToCoco()
        result = converter.transform_annotation(sample_dataset_meta_yolo, params={})

        assert result.categories == sample_dataset_meta_yolo.categories
        assert result.image_count == sample_dataset_meta_yolo.image_count

    def test_preserves_category_names(self, sample_dataset_meta_yolo: DatasetMeta):
        """category_name이 그대로 보존되는지 확인."""
        converter = FormatConvertToCoco()
        result = converter.transform_annotation(sample_dataset_meta_yolo, params={})

        assert result.image_records[0].annotations[0].category_name == "person"

    def test_does_not_mutate_input(self, sample_dataset_meta_yolo: DatasetMeta):
        """원본 DatasetMeta가 변경되지 않는지 확인."""
        converter = FormatConvertToCoco()
        original_categories = sample_dataset_meta_yolo.categories[:]
        converter.transform_annotation(sample_dataset_meta_yolo, params={})
        assert sample_dataset_meta_yolo.categories == original_categories

    def test_no_image_manipulation(self, sample_dataset_meta_yolo: DatasetMeta):
        """build_image_manipulation()이 빈 리스트를 반환하는지 확인."""
        converter = FormatConvertToCoco()
        specs = converter.build_image_manipulation(
            sample_dataset_meta_yolo.image_records[0], params={},
        )
        assert specs == []

    def test_rejects_list_input(self, sample_dataset_meta_yolo: DatasetMeta):
        """list 입력 시 TypeError를 발생시키는지 확인 (PER_SOURCE 전용)."""
        converter = FormatConvertToCoco()
        with pytest.raises(TypeError, match="PER_SOURCE"):
            converter.transform_annotation([sample_dataset_meta_yolo], params={})


# =============================================================================
# IO Round-Trip 통합 테스트
# =============================================================================


class TestIOWriteRoundTrip:
    """
    IO 모듈 write 통합 테스트.
    통일포맷 DatasetMeta → write → 파일 포맷 검증.
    format_convert는 no-op이므로 IO 직접 호출로 검증한다.
    """

    def test_write_coco_json_from_unified(
        self, sample_dataset_meta_coco: DatasetMeta, tmp_path: Path,
    ):
        """통일포맷 DatasetMeta → COCO JSON write → 포맷 검증."""
        coco_output_path = tmp_path / "coco_output" / "annotations.json"
        write_coco_json(sample_dataset_meta_coco, coco_output_path)

        with open(coco_output_path, "r", encoding="utf-8") as file_handle:
            coco_data = json.load(file_handle)

        assert "images" in coco_data
        assert "annotations" in coco_data
        assert "categories" in coco_data
        assert len(coco_data["images"]) == 2
        assert len(coco_data["annotations"]) == 3

        # category name 보존
        category_names = {c["name"] for c in coco_data["categories"]}
        assert "person" in category_names
        assert "car" in category_names

        # bbox가 absolute 좌표 (COCO 표준)
        for annotation in coco_data["annotations"]:
            bbox = annotation["bbox"]
            assert len(bbox) == 4
            assert any(coord > 1.0 for coord in bbox), (
                f"bbox가 normalized 좌표로 보입니다: {bbox}"
            )

    def test_write_yolo_from_unified(
        self, sample_dataset_meta_coco: DatasetMeta, tmp_path: Path,
    ):
        """통일포맷 DatasetMeta → YOLO write → 포맷 검증."""
        yolo_output_dir = tmp_path / "yolo_output"
        write_yolo_dir(sample_dataset_meta_coco, yolo_output_dir)

        txt_files = [f for f in yolo_output_dir.glob("*.txt") if f.name != "classes.txt"]
        assert len(txt_files) == 2

        for txt_file in txt_files:
            content = txt_file.read_text().strip()
            if not content:
                continue
            for line in content.split("\n"):
                parts = line.split()
                assert len(parts) == 5, f"필드 수 오류: {line}"
                int(parts[0])  # class_id는 정수
                for coord_str in parts[1:]:
                    coord_value = float(coord_str)
                    assert 0.0 <= coord_value <= 1.0, (
                        f"좌표 범위 초과: {coord_value}"
                    )

    def test_coco_parse_write_roundtrip_preserves_data(
        self, sample_coco_file: Path, tmp_path: Path,
    ):
        """COCO file → parse → write → re-parse → 데이터 보존 확인."""
        # 1. COCO JSON 파싱 (통일포맷으로 로드)
        original_meta = parse_coco_json(sample_coco_file)

        # 2. COCO JSON 쓰기
        coco_output = tmp_path / "coco_output.json"
        write_coco_json(original_meta, coco_output)

        # 3. 재파싱
        reparsed_meta = parse_coco_json(coco_output)

        # 이미지 수 보존
        assert reparsed_meta.image_count == original_meta.image_count

        # annotation 수 보존
        for img_idx in range(original_meta.image_count):
            assert len(reparsed_meta.image_records[img_idx].annotations) == len(
                original_meta.image_records[img_idx].annotations
            )

        # category_name 보존
        original_cat_names = sorted(
            {ann.category_name for rec in original_meta.image_records for ann in rec.annotations}
        )
        reparsed_cat_names = sorted(
            {ann.category_name for rec in reparsed_meta.image_records for ann in rec.annotations}
        )
        assert reparsed_cat_names == original_cat_names

        # bbox 좌표 보존 (float 변환 오차 허용)
        for img_idx in range(original_meta.image_count):
            for ann_idx in range(len(original_meta.image_records[img_idx].annotations)):
                original_bbox = original_meta.image_records[img_idx].annotations[ann_idx].bbox
                reparsed_bbox = reparsed_meta.image_records[img_idx].annotations[ann_idx].bbox
                for coord_idx in range(4):
                    assert abs(original_bbox[coord_idx] - reparsed_bbox[coord_idx]) < _COORD_TOLERANCE
