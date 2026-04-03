"""
YOLO IO 모듈 테스트.

parse_yolo_dir()과 write_yolo_dir()의 정확성을 검증한다.
장난감 데이터(2장, 3개 annotation, 2개 category)를 사용.
좌표 변환(YOLO normalized ↔ COCO absolute) 정확도를 중점 검증한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from app.pipeline.models import DatasetMeta
from tests.conftest import (
    CAR_BBOX,
    CAR_YOLO,
    IMAGE_1_HEIGHT,
    IMAGE_1_WIDTH,
    IMAGE_2_HEIGHT,
    IMAGE_2_WIDTH,
    PERSON_BBOX,
    PERSON_BBOX_2,
    PERSON_2_YOLO,
    PERSON_YOLO,
)

# 좌표 비교 허용 오차 (float 연산 정밀도)
_COORD_TOLERANCE = 1e-3


def _assert_bbox_close(actual: list[float], expected: list[float], tolerance: float = _COORD_TOLERANCE):
    """두 bbox의 각 좌표가 허용 오차 이내인지 확인."""
    assert len(actual) == len(expected) == 4
    for idx in range(4):
        assert abs(actual[idx] - expected[idx]) < tolerance, (
            f"bbox[{idx}]: {actual[idx]} != {expected[idx]} (diff={abs(actual[idx] - expected[idx])})"
        )


# =============================================================================
# parse_yolo_dir 테스트
# =============================================================================


class TestParseYolo:
    """YOLO 라벨 디렉토리 파싱 테스트."""

    def test_parse_image_count(self, sample_yolo_dir: tuple[Path, list[str]]):
        """이미지 수가 정확히 파싱되는지 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=class_names)
        assert meta.image_count == 2

    def test_parse_annotation_count(self, sample_yolo_dir: tuple[Path, list[str]]):
        """각 이미지의 annotation 수가 정확한지 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=class_names)
        assert len(meta.image_records[0].annotations) == 2  # person + car
        assert len(meta.image_records[1].annotations) == 1  # person

    def test_parse_bbox_conversion(self, sample_yolo_dir: tuple[Path, list[str]]):
        """YOLO normalized → COCO absolute 좌표 변환 정확도 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=class_names)

        # 이미지 1, annotation 1: person
        _assert_bbox_close(meta.image_records[0].annotations[0].bbox, PERSON_BBOX)
        # 이미지 1, annotation 2: car
        _assert_bbox_close(meta.image_records[0].annotations[1].bbox, CAR_BBOX)
        # 이미지 2, annotation 1: person
        _assert_bbox_close(meta.image_records[1].annotations[0].bbox, PERSON_BBOX_2)

    def test_parse_categories_from_class_names(self, sample_yolo_dir: tuple[Path, list[str]]):
        """class_names 파라미터로 categories가 정확히 생성되는지 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=class_names)
        assert meta.category_names == ["person", "car"]

    def test_parse_categories_from_classes_txt(self, sample_yolo_dir: tuple[Path, list[str]]):
        """class_names=None이면 classes.txt에서 자동 로드하는지 확인."""
        label_dir, _ = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=None)
        assert meta.category_names == ["person", "car"]

    def test_parse_categories_fallback_numeric(self, tmp_path: Path):
        """class_names도 classes.txt도 없으면 숫자 이름으로 생성되는지 확인."""
        label_dir = tmp_path / "labels"
        label_dir.mkdir()
        (label_dir / "img.txt").write_text("0 0.5 0.5 0.2 0.3\n2 0.3 0.3 0.1 0.1\n")

        image_sizes = {"img": (640, 480)}
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=None)
        # 숫자 이름, class_id 순서
        assert meta.category_names == ["0", "2"]

    def test_parse_annotation_format_is_yolo(self, sample_yolo_dir: tuple[Path, list[str]]):
        """annotation_format이 'YOLO'로 설정되는지 확인."""
        label_dir, class_names = sample_yolo_dir
        meta = parse_yolo_dir(label_dir, class_names=class_names)
        assert meta.annotation_format == "YOLO"

    def test_parse_empty_txt_file(self, tmp_path: Path):
        """빈 .txt 파일이 annotation 없는 ImageRecord로 처리되는지 확인."""
        label_dir = tmp_path / "labels"
        label_dir.mkdir()
        (label_dir / "empty.txt").write_text("")

        image_sizes = {"empty": (640, 480)}
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes)
        assert meta.image_count == 1
        assert len(meta.image_records[0].annotations) == 0

    def test_parse_no_image_sizes_bbox_is_none(self, tmp_path: Path):
        """image_sizes가 없으면 bbox가 None인지 확인."""
        label_dir = tmp_path / "labels"
        label_dir.mkdir()
        (label_dir / "test.txt").write_text("0 0.5 0.5 0.2 0.3\n")

        meta = parse_yolo_dir(label_dir)
        assert meta.image_records[0].annotations[0].bbox is None

    def test_parse_image_dimensions_stored(self, sample_yolo_dir: tuple[Path, list[str]]):
        """image_sizes가 ImageRecord의 width/height에 저장되는지 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=class_names)
        assert meta.image_records[0].width == IMAGE_1_WIDTH
        assert meta.image_records[0].height == IMAGE_1_HEIGHT


# =============================================================================
# write_yolo_dir 테스트
# =============================================================================


class TestWriteYolo:
    """YOLO 라벨 디렉토리 쓰기 테스트."""

    def test_write_creates_txt_files(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """이미지 수만큼 .txt 파일이 생성되는지 확인."""
        output_dir = tmp_path / "output"
        write_yolo_dir(sample_dataset_meta_coco, output_dir)

        txt_files = sorted(output_dir.glob("*.txt"))
        # classes.txt 제외
        label_files = [f for f in txt_files if f.name != "classes.txt"]
        assert len(label_files) == 2

    def test_write_normalized_coords(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """출력된 YOLO 좌표가 정확한 normalized 값인지 확인."""
        output_dir = tmp_path / "output"
        write_yolo_dir(sample_dataset_meta_coco, output_dir)

        label_1_content = (output_dir / "image_001.txt").read_text().strip().split("\n")
        assert len(label_1_content) == 2

        # 첫 번째 행: person
        parts = label_1_content[0].split()
        assert int(parts[0]) == 0  # class_id
        assert abs(float(parts[1]) - PERSON_YOLO[0]) < _COORD_TOLERANCE
        assert abs(float(parts[2]) - PERSON_YOLO[1]) < _COORD_TOLERANCE
        assert abs(float(parts[3]) - PERSON_YOLO[2]) < _COORD_TOLERANCE
        assert abs(float(parts[4]) - PERSON_YOLO[3]) < _COORD_TOLERANCE

    def test_write_classes_txt(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """classes.txt가 올바르게 생성되는지 확인."""
        output_dir = tmp_path / "output"
        write_yolo_dir(sample_dataset_meta_coco, output_dir)

        classes_path = output_dir / "classes.txt"
        assert classes_path.exists()
        class_names = classes_path.read_text().strip().split("\n")
        assert class_names == ["person", "car"]

    def test_write_no_classes_txt(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """write_classes_txt=False면 classes.txt가 생성되지 않는지 확인."""
        output_dir = tmp_path / "output"
        write_yolo_dir(sample_dataset_meta_coco, output_dir, write_classes_txt=False)

        assert not (output_dir / "classes.txt").exists()

    def test_write_five_fields_per_line(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """각 행이 정확히 5개 필드(class_id cx cy w h)인지 확인."""
        output_dir = tmp_path / "output"
        write_yolo_dir(sample_dataset_meta_coco, output_dir)

        for txt_file in output_dir.glob("*.txt"):
            if txt_file.name == "classes.txt":
                continue
            for line in txt_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                assert len(parts) == 5, f"{txt_file.name}: {line}"

    def test_write_coords_in_unit_range(
        self, tmp_path: Path, sample_dataset_meta_coco: DatasetMeta
    ):
        """출력된 좌표가 모두 [0, 1] 범위인지 확인."""
        output_dir = tmp_path / "output"
        write_yolo_dir(sample_dataset_meta_coco, output_dir)

        for txt_file in output_dir.glob("*.txt"):
            if txt_file.name == "classes.txt":
                continue
            for line in txt_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                for coord in parts[1:]:
                    value = float(coord)
                    assert 0.0 <= value <= 1.0, f"좌표 범위 초과: {value} in {txt_file.name}"

    def test_write_missing_dimensions_raises(self, tmp_path: Path):
        """width/height가 없으면 ValueError를 발생시키는지 확인."""
        meta = DatasetMeta(
            dataset_id="test",
            storage_uri="",
            annotation_format="COCO",
            image_records=[
                # width/height 없는 ImageRecord
                type("ImageRecord", (), {
                    "image_id": 1, "file_name": "no_size.jpg",
                    "width": None, "height": None,
                    "annotations": [], "extra": {},
                })(),
            ],
        )
        # DatasetMeta의 image_records는 list이므로 실제 ImageRecord 사용
        from app.pipeline.models import Annotation, ImageRecord
        meta_proper = DatasetMeta(
            dataset_id="test",
            storage_uri="",
            annotation_format="COCO",
            image_records=[
                ImageRecord(
                    image_id=1,
                    file_name="no_size.jpg",
                    width=None,
                    height=None,
                    annotations=[
                        Annotation(annotation_type="BBOX", category_id=0, bbox=[10, 20, 30, 40]),
                    ],
                ),
            ],
        )

        output_dir = tmp_path / "output"
        with pytest.raises(ValueError, match="이미지 크기가 필요"):
            write_yolo_dir(meta_proper, output_dir)


# =============================================================================
# round-trip 테스트
# =============================================================================


class TestYoloRoundTrip:
    """YOLO parse → write → re-parse round-trip 검증."""

    def test_roundtrip_preserves_coords(self, sample_yolo_dir: tuple[Path, list[str]], tmp_path: Path):
        """parse → write → re-parse 후 좌표가 오차 범위 내에서 동일한지 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }

        # 1단계: 원본 파싱 (YOLO normalized → absolute)
        original_meta = parse_yolo_dir(
            label_dir, image_sizes=image_sizes, class_names=class_names,
        )

        # 2단계: 쓰기 (absolute → YOLO normalized)
        output_dir = tmp_path / "roundtrip_output"
        write_yolo_dir(original_meta, output_dir)

        # 3단계: 재파싱 (YOLO normalized → absolute)
        reparsed_meta = parse_yolo_dir(
            output_dir, image_sizes=image_sizes, class_names=class_names,
        )

        # 검증: 이미지 수
        assert reparsed_meta.image_count == original_meta.image_count

        # 검증: bbox 좌표 오차 이내
        for img_idx in range(original_meta.image_count):
            original_annotations = original_meta.image_records[img_idx].annotations
            reparsed_annotations = reparsed_meta.image_records[img_idx].annotations
            assert len(reparsed_annotations) == len(original_annotations)

            for ann_idx in range(len(original_annotations)):
                _assert_bbox_close(
                    reparsed_annotations[ann_idx].bbox,
                    original_annotations[ann_idx].bbox,
                )

    def test_roundtrip_preserves_categories(
        self, sample_yolo_dir: tuple[Path, list[str]], tmp_path: Path,
    ):
        """round-trip 후 category names가 동일한지 확인."""
        label_dir, class_names = sample_yolo_dir
        image_sizes = {
            "image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "image_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }

        original_meta = parse_yolo_dir(label_dir, image_sizes=image_sizes, class_names=class_names)

        output_dir = tmp_path / "roundtrip_output"
        write_yolo_dir(original_meta, output_dir)

        # classes.txt에서 자동 로드
        reparsed_meta = parse_yolo_dir(output_dir, image_sizes=image_sizes)
        assert reparsed_meta.category_names == original_meta.category_names
