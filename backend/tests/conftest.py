"""
테스트 공통 fixture.

장난감 데이터: 2장 이미지, 3개 annotation, 2개 category (person, car).
COCO와 YOLO 양쪽으로 동일한 데이터를 표현한다.

통일포맷: 내부 모델은 category_name(문자열)으로 클래스를 식별.
annotation_format, category_id 필드 없음.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.pipeline_data_models import Annotation, DatasetMeta, ImageRecord


# =============================================================================
# 장난감 데이터 상수
# =============================================================================

# 이미지 크기
IMAGE_1_WIDTH = 640
IMAGE_1_HEIGHT = 480
IMAGE_2_WIDTH = 800
IMAGE_2_HEIGHT = 600

# COCO absolute bbox [x, y, w, h]
# 이미지 1: person bbox, car bbox
PERSON_BBOX = [100.0, 50.0, 200.0, 300.0]   # x=100, y=50, w=200, h=300
CAR_BBOX = [300.0, 200.0, 150.0, 100.0]     # x=300, y=200, w=150, h=100
# 이미지 2: person bbox
PERSON_BBOX_2 = [50.0, 30.0, 100.0, 250.0]  # x=50, y=30, w=100, h=250

# YOLO normalized center 좌표 (위 COCO bbox에 대응)
# person on image1: cx=(100+100)/640, cy=(50+150)/480, w=200/640, h=300/480
PERSON_YOLO = (
    (100.0 + 200.0 / 2) / IMAGE_1_WIDTH,    # cx = 200/640 = 0.3125
    (50.0 + 300.0 / 2) / IMAGE_1_HEIGHT,     # cy = 200/480 ≈ 0.416667
    200.0 / IMAGE_1_WIDTH,                    # w  = 200/640 = 0.3125
    300.0 / IMAGE_1_HEIGHT,                   # h  = 300/480 = 0.625
)
CAR_YOLO = (
    (300.0 + 150.0 / 2) / IMAGE_1_WIDTH,    # cx = 375/640 ≈ 0.585938
    (200.0 + 100.0 / 2) / IMAGE_1_HEIGHT,   # cy = 250/480 ≈ 0.520833
    150.0 / IMAGE_1_WIDTH,                    # w  = 150/640 ≈ 0.234375
    100.0 / IMAGE_1_HEIGHT,                   # h  = 100/480 ≈ 0.208333
)
PERSON_2_YOLO = (
    (50.0 + 100.0 / 2) / IMAGE_2_WIDTH,     # cx = 100/800 = 0.125
    (30.0 + 250.0 / 2) / IMAGE_2_HEIGHT,    # cy = 155/600 ≈ 0.258333
    100.0 / IMAGE_2_WIDTH,                    # w  = 100/800 = 0.125
    250.0 / IMAGE_2_HEIGHT,                   # h  = 250/600 ≈ 0.416667
)


# =============================================================================
# COCO fixtures
# =============================================================================

@pytest.fixture
def sample_coco_dict() -> dict:
    """
    2장 이미지, 3개 annotation, 2개 category를 가진 최소 COCO JSON dict.
    COCO 표준 비순차 ID 사용: person=1, car=3.
    """
    return {
        "images": [
            {"id": 1, "file_name": "image_001.jpg", "width": IMAGE_1_WIDTH, "height": IMAGE_1_HEIGHT},
            {"id": 2, "file_name": "image_002.jpg", "width": IMAGE_2_WIDTH, "height": IMAGE_2_HEIGHT},
        ],
        "annotations": [
            {
                "id": 1, "image_id": 1, "category_id": 1,
                "bbox": PERSON_BBOX, "area": PERSON_BBOX[2] * PERSON_BBOX[3], "iscrowd": 0,
            },
            {
                "id": 2, "image_id": 1, "category_id": 3,
                "bbox": CAR_BBOX, "area": CAR_BBOX[2] * CAR_BBOX[3], "iscrowd": 0,
            },
            {
                "id": 3, "image_id": 2, "category_id": 1,
                "bbox": PERSON_BBOX_2, "area": PERSON_BBOX_2[2] * PERSON_BBOX_2[3], "iscrowd": 0,
            },
        ],
        "categories": [
            {"id": 1, "name": "person", "supercategory": "human"},
            {"id": 3, "name": "car", "supercategory": "vehicle"},
        ],
    }


@pytest.fixture
def sample_coco_file(tmp_path: Path, sample_coco_dict: dict) -> Path:
    """tmp_path에 COCO JSON 파일을 생성하고 경로를 반환한다."""
    json_path = tmp_path / "annotations.json"
    with open(json_path, "w", encoding="utf-8") as file_handle:
        json.dump(sample_coco_dict, file_handle)
    return json_path


# =============================================================================
# YOLO fixtures
# =============================================================================

@pytest.fixture
def sample_yolo_dir(tmp_path: Path) -> tuple[Path, list[str]]:
    """
    tmp_path에 YOLO .txt 라벨 파일들과 classes.txt를 생성한다.

    Returns:
        (label_dir, class_names) 튜플
    """
    label_dir = tmp_path / "labels"
    label_dir.mkdir()

    class_names = ["person", "car"]

    # image_001.txt: person + car
    label_1 = label_dir / "image_001.txt"
    label_1.write_text(
        f"0 {PERSON_YOLO[0]:.6f} {PERSON_YOLO[1]:.6f} {PERSON_YOLO[2]:.6f} {PERSON_YOLO[3]:.6f}\n"
        f"1 {CAR_YOLO[0]:.6f} {CAR_YOLO[1]:.6f} {CAR_YOLO[2]:.6f} {CAR_YOLO[3]:.6f}\n"
    )

    # image_002.txt: person
    label_2 = label_dir / "image_002.txt"
    label_2.write_text(
        f"0 {PERSON_2_YOLO[0]:.6f} {PERSON_2_YOLO[1]:.6f} {PERSON_2_YOLO[2]:.6f} {PERSON_2_YOLO[3]:.6f}\n"
    )

    # classes.txt
    classes_txt = label_dir / "classes.txt"
    classes_txt.write_text("person\ncar\n")

    return label_dir, class_names


@pytest.fixture
def sample_yolo_dir_with_yaml(tmp_path: Path) -> tuple[Path, list[str]]:
    """
    tmp_path에 YOLO .txt 라벨 파일들과 data.yaml을 생성한다.
    classes.txt는 생성하지 않음 (yaml 우선순위 테스트용).

    Returns:
        (label_dir, class_names) 튜플
    """
    label_dir = tmp_path / "labels"
    label_dir.mkdir()

    class_names = ["person", "car"]

    # image_001.txt: person + car
    label_1 = label_dir / "image_001.txt"
    label_1.write_text(
        f"0 {PERSON_YOLO[0]:.6f} {PERSON_YOLO[1]:.6f} {PERSON_YOLO[2]:.6f} {PERSON_YOLO[3]:.6f}\n"
        f"1 {CAR_YOLO[0]:.6f} {CAR_YOLO[1]:.6f} {CAR_YOLO[2]:.6f} {CAR_YOLO[3]:.6f}\n"
    )

    # data.yaml (ultralytics 스타일)
    yaml_content = (
        "path: /datasets/coco\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 2\n"
        "names: ['person', 'car']\n"
    )
    (label_dir / "data.yaml").write_text(yaml_content)

    return label_dir, class_names


# =============================================================================
# COCO 표준 비순차 ID fixture (실제 COCO 데이터 시뮬레이션)
# =============================================================================

@pytest.fixture
def sample_coco_dict_standard_ids() -> dict:
    """
    실제 COCO 2017과 동일한 비순차 category_id를 사용하는 데이터.
    person(id=1), car(id=3), bus(id=6) — YOLO에서는 0, 2, 5.
    """
    return {
        "images": [
            {"id": 1, "file_name": "img_001.jpg", "width": IMAGE_1_WIDTH, "height": IMAGE_1_HEIGHT},
            {"id": 2, "file_name": "img_002.jpg", "width": IMAGE_2_WIDTH, "height": IMAGE_2_HEIGHT},
        ],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": PERSON_BBOX, "area": 60000.0, "iscrowd": 0},
            {"id": 2, "image_id": 1, "category_id": 3, "bbox": CAR_BBOX, "area": 15000.0, "iscrowd": 0},
            {"id": 3, "image_id": 2, "category_id": 6, "bbox": PERSON_BBOX_2, "area": 25000.0, "iscrowd": 0},
        ],
        "categories": [
            {"id": 1, "name": "person", "supercategory": "human"},
            {"id": 3, "name": "car", "supercategory": "vehicle"},
            {"id": 6, "name": "bus", "supercategory": "vehicle"},
        ],
    }


@pytest.fixture
def sample_coco_file_standard_ids(tmp_path: Path, sample_coco_dict_standard_ids: dict) -> Path:
    """표준 비순차 COCO ID를 사용하는 JSON 파일."""
    json_path = tmp_path / "coco_standard.json"
    with open(json_path, "w", encoding="utf-8") as file_handle:
        json.dump(sample_coco_dict_standard_ids, file_handle)
    return json_path


@pytest.fixture
def sample_dataset_meta_coco_standard_ids() -> DatasetMeta:
    """COCO 표준 비순차 ID로 파싱된 통일포맷 DatasetMeta (person, car, bus)."""
    return DatasetMeta(
        dataset_id="test-coco-std",
        storage_uri="raw/test/train/v1.0.0",
        categories=["person", "car", "bus"],
        image_records=[
            ImageRecord(
                image_id=1,
                file_name="img_001.jpg",
                width=IMAGE_1_WIDTH,
                height=IMAGE_1_HEIGHT,
                annotations=[
                    Annotation(annotation_type="BBOX", category_name="person", bbox=PERSON_BBOX.copy()),
                    Annotation(annotation_type="BBOX", category_name="car", bbox=CAR_BBOX.copy()),
                ],
            ),
            ImageRecord(
                image_id=2,
                file_name="img_002.jpg",
                width=IMAGE_2_WIDTH,
                height=IMAGE_2_HEIGHT,
                annotations=[
                    Annotation(annotation_type="BBOX", category_name="bus", bbox=PERSON_BBOX_2.copy()),
                ],
            ),
        ],
    )


# =============================================================================
# DatasetMeta fixtures (통일포맷)
# =============================================================================

@pytest.fixture
def sample_dataset_meta_coco() -> DatasetMeta:
    """COCO에서 파싱된 통일포맷 DatasetMeta 인스턴스. person, car."""
    return DatasetMeta(
        dataset_id="test-coco-001",
        storage_uri="raw/test/train/v1.0.0",
        categories=["person", "car"],
        image_records=[
            ImageRecord(
                image_id=1,
                file_name="image_001.jpg",
                width=IMAGE_1_WIDTH,
                height=IMAGE_1_HEIGHT,
                annotations=[
                    Annotation(annotation_type="BBOX", category_name="person", bbox=PERSON_BBOX.copy()),
                    Annotation(annotation_type="BBOX", category_name="car", bbox=CAR_BBOX.copy()),
                ],
            ),
            ImageRecord(
                image_id=2,
                file_name="image_002.jpg",
                width=IMAGE_2_WIDTH,
                height=IMAGE_2_HEIGHT,
                annotations=[
                    Annotation(annotation_type="BBOX", category_name="person", bbox=PERSON_BBOX_2.copy()),
                ],
            ),
        ],
    )


@pytest.fixture
def sample_dataset_meta_yolo() -> DatasetMeta:
    """YOLO에서 파싱된 통일포맷 DatasetMeta 인스턴스 (동일 데이터)."""
    return DatasetMeta(
        dataset_id="test-yolo-001",
        storage_uri="raw/test/train/v1.0.0",
        categories=["person", "car"],
        image_records=[
            ImageRecord(
                image_id=1,
                file_name="image_001.jpg",
                width=IMAGE_1_WIDTH,
                height=IMAGE_1_HEIGHT,
                annotations=[
                    Annotation(annotation_type="BBOX", category_name="person", bbox=PERSON_BBOX.copy()),
                    Annotation(annotation_type="BBOX", category_name="car", bbox=CAR_BBOX.copy()),
                ],
            ),
            ImageRecord(
                image_id=2,
                file_name="image_002.jpg",
                width=IMAGE_2_WIDTH,
                height=IMAGE_2_HEIGHT,
                annotations=[
                    Annotation(annotation_type="BBOX", category_name="person", bbox=PERSON_BBOX_2.copy()),
                ],
            ),
        ],
    )
