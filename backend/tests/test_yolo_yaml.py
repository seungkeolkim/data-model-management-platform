"""
YOLO yaml 파싱 테스트.

data.yaml의 names: 필드에서 클래스 이름을 추출하는 기능을 검증한다.
리스트 형태, dict 형태, 여러 줄 형태 등 다양한 yaml 구조를 테스트한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.io.yolo_io import (
    _find_yaml_in_directory,
    parse_yolo_dir,
    parse_yolo_yaml,
)
from tests.conftest import (
    IMAGE_1_HEIGHT,
    IMAGE_1_WIDTH,
)


# =============================================================================
# parse_yolo_yaml 테스트
# =============================================================================


class TestParseYoloYaml:
    """YOLO data.yaml 파싱 테스트."""

    def test_parse_list_format(self, tmp_path: Path):
        """names: ['person', 'car'] 리스트 형태 파싱."""
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text(
            "nc: 2\n"
            "names: ['person', 'car']\n"
        )
        result = parse_yolo_yaml(yaml_path)
        assert result == ["person", "car"]

    def test_parse_multiline_list_format(self, tmp_path: Path):
        """names: 여러 줄 - 형태 파싱."""
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text(
            "nc: 3\n"
            "names:\n"
            "  - person\n"
            "  - car\n"
            "  - bus\n"
        )
        result = parse_yolo_yaml(yaml_path)
        assert result == ["person", "car", "bus"]

    def test_parse_dict_format(self, tmp_path: Path):
        """names: {0: 'person', 1: 'car'} dict 형태 파싱 (ultralytics 스타일)."""
        yaml_path = tmp_path / "data.yaml"
        # PyYAML이 있으면 dict로 파싱됨
        yaml_path.write_text(
            "nc: 2\n"
            "names:\n"
            "  0: person\n"
            "  1: car\n"
        )
        result = parse_yolo_yaml(yaml_path)
        assert result is not None
        assert "person" in result
        assert "car" in result

    def test_parse_with_extra_fields(self, tmp_path: Path):
        """path, train, val 등 다른 필드가 있어도 names만 추출."""
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text(
            "path: /datasets/coco\n"
            "train: images/train\n"
            "val: images/val\n"
            "nc: 2\n"
            "names: ['person', 'car']\n"
        )
        result = parse_yolo_yaml(yaml_path)
        assert result == ["person", "car"]

    def test_parse_no_names_key(self, tmp_path: Path):
        """names: 키가 없으면 None 반환."""
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text("nc: 2\ntrain: images/train\n")
        result = parse_yolo_yaml(yaml_path)
        assert result is None

    def test_parse_quoted_names(self, tmp_path: Path):
        """따옴표가 있는 이름도 정상 파싱."""
        yaml_path = tmp_path / "data.yaml"
        yaml_path.write_text(
            "names: [\"traffic light\", \"stop sign\", 'fire hydrant']\n"
        )
        result = parse_yolo_yaml(yaml_path)
        assert result == ["traffic light", "stop sign", "fire hydrant"]


# =============================================================================
# _find_yaml_in_directory 테스트
# =============================================================================


class TestFindYamlInDirectory:
    """디렉토리에서 YOLO yaml 파일 탐색 테스트."""

    def test_finds_data_yaml(self, tmp_path: Path):
        """data.yaml이 있으면 찾기."""
        (tmp_path / "data.yaml").write_text("names: ['a']\n")
        result = _find_yaml_in_directory(tmp_path)
        assert result is not None
        assert result.name == "data.yaml"

    def test_finds_dataset_yaml(self, tmp_path: Path):
        """dataset.yaml이 있으면 찾기."""
        (tmp_path / "dataset.yaml").write_text("names: ['a']\n")
        result = _find_yaml_in_directory(tmp_path)
        assert result is not None
        assert result.name == "dataset.yaml"

    def test_finds_any_yaml(self, tmp_path: Path):
        """일반적인 이름이 없으면 아무 .yaml 파일 찾기."""
        (tmp_path / "custom.yaml").write_text("names: ['a']\n")
        result = _find_yaml_in_directory(tmp_path)
        assert result is not None
        assert result.suffix == ".yaml"

    def test_returns_none_when_no_yaml(self, tmp_path: Path):
        """yaml 파일이 없으면 None."""
        (tmp_path / "readme.txt").write_text("hello")
        result = _find_yaml_in_directory(tmp_path)
        assert result is None

    def test_data_yaml_has_priority(self, tmp_path: Path):
        """data.yaml이 dataset.yaml보다 우선."""
        (tmp_path / "data.yaml").write_text("names: ['a']\n")
        (tmp_path / "dataset.yaml").write_text("names: ['b']\n")
        result = _find_yaml_in_directory(tmp_path)
        assert result.name == "data.yaml"


# =============================================================================
# parse_yolo_dir + yaml 통합 테스트
# =============================================================================


class TestParseYoloDirWithYaml:
    """yaml 파일에서 클래스 이름을 자동 로드하는 통합 테스트."""

    def test_yaml_provides_class_names(
        self, sample_yolo_dir_with_yaml: tuple[Path, list[str]],
    ):
        """data.yaml의 names:에서 클래스 이름을 로드하는지 확인."""
        label_dir, expected_names = sample_yolo_dir_with_yaml
        image_sizes = {"image_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT)}

        # class_names=None, classes.txt도 없음 → yaml에서 로드
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes)
        assert meta.category_names == expected_names

    def test_yaml_priority_over_classes_txt(self, tmp_path: Path):
        """yaml이 classes.txt보다 우선하는지 확인."""
        label_dir = tmp_path / "labels"
        label_dir.mkdir()
        (label_dir / "img.txt").write_text("0 0.5 0.5 0.2 0.3\n")

        # classes.txt: 다른 이름
        (label_dir / "classes.txt").write_text("wrong_name_a\nwrong_name_b\n")

        # data.yaml: 올바른 이름
        (label_dir / "data.yaml").write_text("names: ['correct_a', 'correct_b']\n")

        image_sizes = {"img": (640, 480)}
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes)
        assert meta.category_names == ["correct_a", "correct_b"]

    def test_explicit_class_names_override_yaml(self, tmp_path: Path):
        """class_names 파라미터가 yaml보다 우선하는지 확인."""
        label_dir = tmp_path / "labels"
        label_dir.mkdir()
        (label_dir / "img.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        (label_dir / "data.yaml").write_text("names: ['from_yaml']\n")

        image_sizes = {"img": (640, 480)}
        meta = parse_yolo_dir(
            label_dir, image_sizes=image_sizes,
            class_names=["from_param"],
        )
        assert meta.category_names == ["from_param"]

    def test_parent_dir_yaml_found(self, tmp_path: Path):
        """label_dir에 없으면 상위 디렉토리에서 yaml을 탐색하는지 확인."""
        # 상위에 data.yaml
        (tmp_path / "data.yaml").write_text("names: ['person', 'car']\n")

        # 하위 labels/
        label_dir = tmp_path / "labels"
        label_dir.mkdir()
        (label_dir / "img.txt").write_text("0 0.5 0.5 0.2 0.3\n")

        image_sizes = {"img": (640, 480)}
        meta = parse_yolo_dir(label_dir, image_sizes=image_sizes)
        assert meta.category_names == ["person", "car"]
