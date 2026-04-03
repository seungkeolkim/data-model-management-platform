"""
포맷 변환 Manipulator 테스트.

FormatConvertToYolo, FormatConvertToCoco의 transform_annotation() 검증.
표준 COCO↔YOLO class ID 리매핑과 IO 모듈 결합 round-trip 통합 테스트 포함.
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
# FormatConvertToYolo 테스트
# =============================================================================


class TestFormatConvertToYolo:
    """COCO → YOLO 변환 Manipulator 테스트."""

    def test_name_matches_db_seed(self):
        """name 속성이 DB seed의 manipulator name과 일치하는지 확인."""
        converter = FormatConvertToYolo()
        assert converter.name == "format_convert_to_yolo"

    def test_changes_format_to_yolo(self, sample_dataset_meta_coco: DatasetMeta):
        """변환 후 annotation_format이 'YOLO'인지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})
        assert result.annotation_format == "YOLO"

    def test_preserves_bbox_values(self, sample_dataset_meta_coco: DatasetMeta):
        """변환 후에도 bbox 값이 동일한지 확인 (내부 좌표 불변)."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})

        assert result.image_records[0].annotations[0].bbox == PERSON_BBOX
        assert result.image_records[0].annotations[1].bbox == CAR_BBOX
        assert result.image_records[1].annotations[0].bbox == PERSON_BBOX_2

    def test_remaps_category_ids(self, sample_dataset_meta_coco: DatasetMeta):
        """COCO 비순차 ID가 YOLO 0-based 순차 ID로 리매핑되는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})

        # person: coco 1 → yolo 0 (표준 순서 0번째)
        assert result.image_records[0].annotations[0].category_id == 0
        # car: coco 3 → yolo 1 (표준 순서 1번째, 2개 클래스만 있으므로)
        assert result.image_records[0].annotations[1].category_id == 1

    def test_preserves_category_names(self, sample_dataset_meta_coco: DatasetMeta):
        """리매핑 후에도 클래스 이름이 보존되는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})
        name_by_id = {cat["id"]: cat["name"] for cat in result.categories}
        assert name_by_id[0] == "person"
        assert name_by_id[1] == "car"

    def test_preserves_image_count(self, sample_dataset_meta_coco: DatasetMeta):
        """변환 후 이미지 수가 동일한지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(sample_dataset_meta_coco, params={})
        assert result.image_count == sample_dataset_meta_coco.image_count

    def test_does_not_mutate_input(self, sample_dataset_meta_coco: DatasetMeta):
        """원본 DatasetMeta가 변경되지 않는지 확인."""
        converter = FormatConvertToYolo()
        original_format = sample_dataset_meta_coco.annotation_format
        original_cat_id = sample_dataset_meta_coco.image_records[0].annotations[0].category_id
        converter.transform_annotation(sample_dataset_meta_coco, params={})
        assert sample_dataset_meta_coco.annotation_format == original_format
        assert sample_dataset_meta_coco.image_records[0].annotations[0].category_id == original_cat_id

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
# FormatConvertToCoco 테스트
# =============================================================================


class TestFormatConvertToCoco:
    """YOLO → COCO 변환 Manipulator 테스트."""

    def test_name_matches_db_seed(self):
        """name 속성이 DB seed의 manipulator name과 일치하는지 확인."""
        converter = FormatConvertToCoco()
        assert converter.name == "format_convert_to_coco"

    def test_changes_format_to_coco(self, sample_dataset_meta_yolo: DatasetMeta):
        """변환 후 annotation_format이 'COCO'인지 확인."""
        converter = FormatConvertToCoco()
        result = converter.transform_annotation(sample_dataset_meta_yolo, params={})
        assert result.annotation_format == "COCO"

    def test_remaps_yolo_to_coco_ids(self, sample_dataset_meta_yolo: DatasetMeta):
        """YOLO 순차 ID가 COCO 표준 ID로 리매핑되는지 확인 (이름 기반)."""
        converter = FormatConvertToCoco()
        result = converter.transform_annotation(sample_dataset_meta_yolo, params={})

        # person: yolo 0, name="person" → NAME_TO_COCO_ID["person"] = 1
        assert result.image_records[0].annotations[0].category_id == 1
        # car: yolo 1, name="car" → NAME_TO_COCO_ID["car"] = 3
        assert result.image_records[0].annotations[1].category_id == 3

    def test_sets_category_names_via_params(self, sample_dataset_meta_yolo: DatasetMeta):
        """params['category_names']로 이름이 업데이트되는지 확인."""
        converter = FormatConvertToCoco()
        result = converter.transform_annotation(
            sample_dataset_meta_yolo,
            params={"category_names": ["pedestrian", "vehicle"]},
        )
        name_by_id = {cat["id"]: cat["name"] for cat in result.categories}
        # "pedestrian", "vehicle"은 표준 COCO 클래스가 아니므로 91, 92 할당
        assert name_by_id[91] == "pedestrian"  # yolo 0, name="pedestrian" → 미지 → 91
        assert name_by_id[92] == "vehicle"     # yolo 1, name="vehicle" → 미지 → 92

    def test_preserves_bbox_values(self, sample_dataset_meta_yolo: DatasetMeta):
        """변환 후에도 bbox 값이 동일한지 확인."""
        converter = FormatConvertToCoco()
        result = converter.transform_annotation(sample_dataset_meta_yolo, params={})
        assert result.image_records[0].annotations[0].bbox == PERSON_BBOX

    def test_does_not_mutate_input(self, sample_dataset_meta_yolo: DatasetMeta):
        """원본 DatasetMeta가 변경되지 않는지 확인."""
        converter = FormatConvertToCoco()
        original_format = sample_dataset_meta_yolo.annotation_format
        original_cat_names = sample_dataset_meta_yolo.category_names[:]
        converter.transform_annotation(
            sample_dataset_meta_yolo, params={"category_names": ["a", "b"]},
        )
        assert sample_dataset_meta_yolo.annotation_format == original_format
        assert sample_dataset_meta_yolo.category_names == original_cat_names

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
# Full Round-Trip 통합 테스트
# =============================================================================


class TestFullRoundTrip:
    """
    IO + Manipulator 결합 통합 테스트.
    COCO file → parse → convert → write → 포맷 검증 (양방향).
    """

    def test_coco_to_yolo_full_roundtrip(
        self, sample_coco_file: Path, tmp_path: Path,
    ):
        """COCO JSON → parse → convert to YOLO → write YOLO files → 포맷 검증."""
        # 1. COCO JSON 파싱
        coco_meta = parse_coco_json(sample_coco_file)
        assert coco_meta.annotation_format == "COCO"

        # 2. Manipulator로 YOLO 변환 (ID 리매핑 포함)
        converter = FormatConvertToYolo()
        yolo_meta = converter.transform_annotation(coco_meta, params={})
        assert yolo_meta.annotation_format == "YOLO"

        # 3. YOLO 파일 쓰기
        yolo_output_dir = tmp_path / "yolo_output"
        write_yolo_dir(yolo_meta, yolo_output_dir)

        # 4. 출력 파일 포맷 검증
        txt_files = [f for f in yolo_output_dir.glob("*.txt") if f.name != "classes.txt"]
        assert len(txt_files) == 2

        for txt_file in txt_files:
            content = txt_file.read_text().strip()
            if not content:
                continue
            for line in content.split("\n"):
                parts = line.split()
                # 5개 필드: class_id cx cy w h
                assert len(parts) == 5, f"필드 수 오류: {line}"
                # class_id는 정수
                int(parts[0])
                # 좌표는 [0, 1] 범위
                for coord_str in parts[1:]:
                    coord_value = float(coord_str)
                    assert 0.0 <= coord_value <= 1.0, (
                        f"좌표 범위 초과: {coord_value}"
                    )

        # 5. classes.txt 검증
        classes_content = (yolo_output_dir / "classes.txt").read_text().strip().split("\n")
        assert "person" in classes_content
        assert "car" in classes_content

    def test_yolo_to_coco_full_roundtrip(
        self, sample_yolo_dir: tuple[Path, list[str]], tmp_path: Path,
    ):
        """YOLO files → parse → convert to COCO → write COCO JSON → 포맷 검증."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }

        # 1. YOLO 파싱
        yolo_meta = parse_yolo_dir(
            label_dir, image_sizes=image_sizes, class_names=class_names,
        )
        assert yolo_meta.annotation_format == "YOLO"

        # 2. Manipulator로 COCO 변환 (ID 리매핑 포함)
        converter = FormatConvertToCoco()
        coco_meta = converter.transform_annotation(
            yolo_meta, params={"category_names": class_names},
        )
        assert coco_meta.annotation_format == "COCO"

        # 3. COCO JSON 쓰기
        coco_output_path = tmp_path / "coco_output" / "annotations.json"
        write_coco_json(coco_meta, coco_output_path)

        # 4. 출력 파일 포맷 검증
        with open(coco_output_path, "r", encoding="utf-8") as file_handle:
            coco_data = json.load(file_handle)

        assert "images" in coco_data
        assert "annotations" in coco_data
        assert "categories" in coco_data
        assert len(coco_data["images"]) == 2
        assert len(coco_data["annotations"]) == 3

        # bbox가 absolute 좌표인지 확인
        for annotation in coco_data["annotations"]:
            bbox = annotation["bbox"]
            assert len(bbox) == 4
            assert any(coord > 1.0 for coord in bbox), (
                f"bbox가 normalized 좌표로 보입니다: {bbox}"
            )

        # area 필드 존재 및 양수
        for annotation in coco_data["annotations"]:
            assert "area" in annotation
            assert annotation["area"] > 0

    def test_coco_yolo_coco_preserves_data(
        self, sample_coco_file: Path, tmp_path: Path,
    ):
        """COCO → YOLO → COCO 왕복 후 데이터가 보존되는지 확인."""
        # 원본 COCO 파싱
        original_coco = parse_coco_json(sample_coco_file)

        # COCO → YOLO 변환 (ID 리매핑)
        to_yolo = FormatConvertToYolo()
        yolo_meta = to_yolo.transform_annotation(original_coco, params={})

        # YOLO 파일 쓰기
        yolo_dir = tmp_path / "yolo"
        write_yolo_dir(yolo_meta, yolo_dir)

        # YOLO 파일 재파싱
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        reparsed_yolo = parse_yolo_dir(yolo_dir, image_sizes=image_sizes)

        # YOLO → COCO 변환 (ID 복원)
        to_coco = FormatConvertToCoco()
        final_coco = to_coco.transform_annotation(reparsed_yolo, params={})

        # COCO JSON 쓰기
        coco_output = tmp_path / "coco_output.json"
        write_coco_json(final_coco, coco_output)

        # 재파싱하여 검증
        final_meta = parse_coco_json(coco_output)

        # 이미지 수 보존
        assert final_meta.image_count == original_coco.image_count

        # annotation 수 보존
        for img_idx in range(original_coco.image_count):
            assert len(final_meta.image_records[img_idx].annotations) == len(
                original_coco.image_records[img_idx].annotations
            )

        # bbox 좌표 보존 (float 변환 오차 허용)
        for img_idx in range(original_coco.image_count):
            for ann_idx in range(len(original_coco.image_records[img_idx].annotations)):
                original_bbox = original_coco.image_records[img_idx].annotations[ann_idx].bbox
                final_bbox = final_meta.image_records[img_idx].annotations[ann_idx].bbox
                for coord_idx in range(4):
                    assert abs(original_bbox[coord_idx] - final_bbox[coord_idx]) < _COORD_TOLERANCE

        # category_id 왕복 보존: 원래 COCO ID로 복원되었는지
        original_cat_ids = sorted(
            {ann.category_id for rec in original_coco.image_records for ann in rec.annotations}
        )
        final_cat_ids = sorted(
            {ann.category_id for rec in final_meta.image_records for ann in rec.annotations}
        )
        assert final_cat_ids == original_cat_ids
