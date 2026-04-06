"""
클래스 매핑 테이블 및 리매핑 로직 테스트.

COCO 80 클래스 표준 매핑 테이블의 정확성과,
build_coco_to_yolo_remap / build_yolo_to_coco_remap 함수의 동작을 검증한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.manipulators.format_convert import FormatConvertToCoco, FormatConvertToYolo
from app.pipeline.io.coco_yolo_class_mapping import (
    COCO_80_CLASSES,
    COCO_ID_TO_NAME,
    COCO_ID_TO_YOLO_ID,
    YOLO_ID_TO_COCO_ID,
    YOLO_ID_TO_NAME,
    build_coco_to_yolo_remap,
    build_yolo_to_coco_remap,
)
from app.pipeline.io.coco_io import parse_coco_json, write_coco_json
from app.pipeline.io.yolo_io import write_yolo_dir
from app.pipeline.pipeline_data_models import DatasetMeta
from tests.conftest import (
    IMAGE_1_HEIGHT,
    IMAGE_1_WIDTH,
    IMAGE_2_HEIGHT,
    IMAGE_2_WIDTH,
)

_COORD_TOLERANCE = 1e-3


# =============================================================================
# 표준 매핑 테이블 검증
# =============================================================================


class TestCoco80ClassesTable:
    """COCO 80 클래스 표준 매핑 테이블 검증."""

    def test_exactly_80_classes(self):
        """COCO 2017 공식 80개 클래스가 정의되어 있는지 확인.
        (id 1~90 중 12,26,29,30,45,66,68,69,71,83 제외 = 80개)"""
        assert len(COCO_80_CLASSES) == 80

    def test_yolo_ids_are_sequential(self):
        """YOLO ID가 0부터 순차적인지 확인."""
        yolo_ids = [entry["yolo_id"] for entry in COCO_80_CLASSES]
        expected = list(range(len(COCO_80_CLASSES)))
        assert yolo_ids == expected

    def test_coco_ids_non_sequential(self):
        """COCO ID에 빈 번호가 있는지 확인 (비순차성)."""
        coco_ids = [entry["coco_id"] for entry in COCO_80_CLASSES]
        # 12번(예: 없음)이 빠져 있으므로 연속이 아님
        assert coco_ids != list(range(1, len(coco_ids) + 1))

    def test_known_mappings(self):
        """잘 알려진 COCO↔YOLO 매핑이 정확한지 확인."""
        # person: coco_id=1 → yolo_id=0
        assert COCO_ID_TO_YOLO_ID[1] == 0
        assert YOLO_ID_TO_COCO_ID[0] == 1
        assert COCO_ID_TO_NAME[1] == "person"

        # car: coco_id=3 → yolo_id=2
        assert COCO_ID_TO_YOLO_ID[3] == 2
        assert YOLO_ID_TO_COCO_ID[2] == 3

        # stop sign: coco_id=13 → yolo_id=11 (12번이 빠짐)
        assert COCO_ID_TO_YOLO_ID[13] == 11
        assert COCO_ID_TO_NAME[13] == "stop sign"

        # bus: coco_id=6 → yolo_id=5
        assert COCO_ID_TO_YOLO_ID[6] == 5
        assert YOLO_ID_TO_NAME[5] == "bus"

    def test_bidirectional_consistency(self):
        """COCO→YOLO와 YOLO→COCO 매핑이 양방향 일관성을 가지는지 확인."""
        for entry in COCO_80_CLASSES:
            coco_id = entry["coco_id"]
            yolo_id = entry["yolo_id"]
            assert COCO_ID_TO_YOLO_ID[coco_id] == yolo_id
            assert YOLO_ID_TO_COCO_ID[yolo_id] == coco_id


# =============================================================================
# build_coco_to_yolo_remap 테스트
# =============================================================================


class TestBuildCocoToYoloRemap:
    """COCO → YOLO 리매핑 테이블 구성 테스트."""

    def test_standard_classes_remap(self):
        """표준 COCO 클래스가 0-based sequential로 리매핑되는지 확인.
        표준 순서(person→bicycle→car→...→bus) 기준으로 정렬 후 0,1,2 할당."""
        categories = [
            {"id": 1, "name": "person"},
            {"id": 3, "name": "car"},
            {"id": 6, "name": "bus"},
        ]
        remap, new_cats = build_coco_to_yolo_remap(categories)

        # person(표준순서0) → 0, car(표준순서2) → 1, bus(표준순서5) → 2
        assert remap[1] == 0   # person
        assert remap[3] == 1   # car
        assert remap[6] == 2   # bus

    def test_unknown_class_appended_after_standard(self):
        """표준에 없는 클래스가 표준 클래스 뒤에 순차 할당되는지 확인."""
        categories = [
            {"id": 1, "name": "person"},
            {"id": 999, "name": "custom_object"},
        ]
        remap, new_cats = build_coco_to_yolo_remap(categories)

        assert remap[1] == 0     # 표준 (person)
        assert remap[999] == 1   # 미지 → 표준 1개 다음

    def test_multiple_unknown_classes(self):
        """여러 미지의 클래스가 순차적으로 할당되는지 확인."""
        categories = [
            {"id": 1, "name": "person"},
            {"id": 500, "name": "custom_a"},
            {"id": 600, "name": "custom_b"},
        ]
        remap, new_cats = build_coco_to_yolo_remap(categories)

        assert remap[1] == 0     # 표준 (person)
        assert remap[500] == 1   # 첫 번째 미지
        assert remap[600] == 2   # 두 번째 미지

    def test_custom_mapping_overrides_default(self):
        """custom_mapping이 표준 매핑을 override하는지 확인."""
        categories = [
            {"id": 1, "name": "person"},
            {"id": 3, "name": "car"},
        ]
        # person을 강제로 yolo_id=10으로 매핑
        custom = {1: 10, 3: 20}
        remap, new_cats = build_coco_to_yolo_remap(categories, custom_mapping=custom)

        assert remap[1] == 10
        assert remap[3] == 20

    def test_new_categories_sorted_by_yolo_id(self):
        """반환된 categories가 yolo_id 순으로 정렬되는지 확인."""
        categories = [
            {"id": 6, "name": "bus"},    # yolo 5
            {"id": 1, "name": "person"}, # yolo 0
            {"id": 3, "name": "car"},    # yolo 2
        ]
        _, new_cats = build_coco_to_yolo_remap(categories)

        ids = [cat["id"] for cat in new_cats]
        assert ids == sorted(ids)

    def test_category_names_preserved(self):
        """리매핑 후 클래스 이름이 보존되는지 확인."""
        categories = [
            {"id": 1, "name": "person"},
            {"id": 999, "name": "my_custom_class"},
        ]
        _, new_cats = build_coco_to_yolo_remap(categories)

        name_by_id = {cat["id"]: cat["name"] for cat in new_cats}
        assert name_by_id[0] == "person"
        assert name_by_id[1] == "my_custom_class"  # 표준 1개 다음


# =============================================================================
# build_yolo_to_coco_remap 테스트
# =============================================================================


class TestBuildYoloToCocoRemap:
    """YOLO → COCO 리매핑 테이블 구성 테스트."""

    def test_standard_classes_remap(self):
        """표준 YOLO 클래스가 올바르게 COCO ID로 리매핑되는지 확인."""
        categories = [
            {"id": 0, "name": "person"},
            {"id": 2, "name": "car"},
            {"id": 5, "name": "bus"},
        ]
        remap, new_cats = build_yolo_to_coco_remap(categories)

        assert remap[0] == 1   # person: yolo 0 → coco 1
        assert remap[2] == 3   # car: yolo 2 → coco 3
        assert remap[5] == 6   # bus: yolo 5 → coco 6

    def test_unknown_class_starts_at_91(self):
        """표준에 없는 클래스가 91번부터 할당되는지 확인."""
        categories = [
            {"id": 0, "name": "person"},
            {"id": 80, "name": "custom_object"},
        ]
        remap, new_cats = build_yolo_to_coco_remap(categories)

        assert remap[0] == 1     # 표준 매핑
        assert remap[80] == 91   # 미지 → 91번

    def test_custom_mapping_overrides(self):
        """custom_mapping이 표준 매핑을 override하는지 확인."""
        categories = [
            {"id": 0, "name": "person"},
        ]
        custom = {0: 100}
        remap, _ = build_yolo_to_coco_remap(categories, custom_mapping=custom)

        assert remap[0] == 100

    def test_roundtrip_standard_ids(self):
        """표준 클래스의 coco→yolo→coco 왕복이 원래 ID로 돌아오는지 확인."""
        # coco categories (비순차)
        coco_cats = [
            {"id": 1, "name": "person"},
            {"id": 13, "name": "stop sign"},
            {"id": 67, "name": "dining table"},
        ]
        # coco → yolo
        remap_to_yolo, yolo_cats = build_coco_to_yolo_remap(coco_cats)
        # yolo → coco
        remap_to_coco, final_cats = build_yolo_to_coco_remap(yolo_cats)

        # 왕복 확인: 원래 coco_id로 복원되는지
        for original_cat in coco_cats:
            coco_id = original_cat["id"]
            yolo_id = remap_to_yolo[coco_id]
            restored_coco_id = remap_to_coco[yolo_id]
            assert restored_coco_id == coco_id, (
                f"왕복 실패: coco_id={coco_id} → yolo_id={yolo_id} → "
                f"restored={restored_coco_id}"
            )


# =============================================================================
# Manipulator + class mapping 통합 테스트
# =============================================================================


class TestFormatConvertWithClassMapping:
    """포맷 변환 Manipulator의 class ID 리매핑 동작 검증."""

    def test_coco_to_yolo_remaps_standard_ids(
        self, sample_dataset_meta_coco_standard_ids: DatasetMeta,
    ):
        """COCO 표준 비순차 ID가 YOLO 순차 ID로 리매핑되는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(
            sample_dataset_meta_coco_standard_ids, params={},
        )

        # person: coco 1 → yolo 0 (순차 0번째)
        assert result.image_records[0].annotations[0].category_id == 0
        # car: coco 3 → yolo 1 (순차 1번째)
        assert result.image_records[0].annotations[1].category_id == 1
        # bus: coco 6 → yolo 2 (순차 2번째)
        assert result.image_records[1].annotations[0].category_id == 2

    def test_coco_to_yolo_categories_updated(
        self, sample_dataset_meta_coco_standard_ids: DatasetMeta,
    ):
        """변환 후 categories의 ID가 YOLO 순차 ID로 변경되는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(
            sample_dataset_meta_coco_standard_ids, params={},
        )

        cat_ids = [cat["id"] for cat in result.categories]
        assert 0 in cat_ids   # person
        assert 1 in cat_ids   # car
        assert 2 in cat_ids   # bus

    def test_coco_to_yolo_preserves_names(
        self, sample_dataset_meta_coco_standard_ids: DatasetMeta,
    ):
        """리매핑 후 클래스 이름이 보존되는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(
            sample_dataset_meta_coco_standard_ids, params={},
        )

        name_by_id = {cat["id"]: cat["name"] for cat in result.categories}
        assert name_by_id[0] == "person"
        assert name_by_id[1] == "car"
        assert name_by_id[2] == "bus"

    def test_coco_to_yolo_custom_mapping(
        self, sample_dataset_meta_coco_standard_ids: DatasetMeta,
    ):
        """custom class_id_mapping이 표준 매핑을 override하는지 확인."""
        converter = FormatConvertToYolo()
        result = converter.transform_annotation(
            sample_dataset_meta_coco_standard_ids,
            params={"class_id_mapping": {1: 10, 3: 20, 6: 30}},
        )

        assert result.image_records[0].annotations[0].category_id == 10  # person
        assert result.image_records[0].annotations[1].category_id == 20  # car
        assert result.image_records[1].annotations[0].category_id == 30  # bus

    def test_yolo_to_coco_remaps_standard_ids(
        self, sample_dataset_meta_coco_standard_ids: DatasetMeta,
    ):
        """YOLO→COCO 변환이 표준 COCO ID로 복원되는지 확인."""
        # 먼저 COCO→YOLO 변환
        to_yolo = FormatConvertToYolo()
        yolo_meta = to_yolo.transform_annotation(
            sample_dataset_meta_coco_standard_ids, params={},
        )

        # YOLO→COCO 역변환
        to_coco = FormatConvertToCoco()
        coco_meta = to_coco.transform_annotation(yolo_meta, params={})

        # 원래 COCO ID로 복원 확인
        assert coco_meta.image_records[0].annotations[0].category_id == 1  # person
        assert coco_meta.image_records[0].annotations[1].category_id == 3  # car
        assert coco_meta.image_records[1].annotations[0].category_id == 6  # bus

    def test_does_not_mutate_input(
        self, sample_dataset_meta_coco_standard_ids: DatasetMeta,
    ):
        """변환 후 원본 DatasetMeta의 category_id가 변경되지 않는지 확인."""
        original_ids = [
            ann.category_id
            for rec in sample_dataset_meta_coco_standard_ids.image_records
            for ann in rec.annotations
        ]

        converter = FormatConvertToYolo()
        converter.transform_annotation(sample_dataset_meta_coco_standard_ids, params={})

        after_ids = [
            ann.category_id
            for rec in sample_dataset_meta_coco_standard_ids.image_records
            for ann in rec.annotations
        ]
        assert after_ids == original_ids

    def test_full_roundtrip_with_standard_ids(
        self, sample_coco_file_standard_ids: Path, tmp_path: Path,
    ):
        """
        COCO(비순차 ID) → parse → YOLO 변환 → write files → re-parse → COCO 변환
        전체 왕복 후 category_id가 원래 COCO ID로 복원되는지 확인.
        """
        # 1. COCO 파싱
        original_coco = parse_coco_json(sample_coco_file_standard_ids)

        # 2. COCO → YOLO 변환 (ID 리매핑)
        to_yolo = FormatConvertToYolo()
        yolo_meta = to_yolo.transform_annotation(original_coco, params={})

        # 3. YOLO 파일 쓰기
        yolo_dir = tmp_path / "yolo_output"
        write_yolo_dir(yolo_meta, yolo_dir)

        # YOLO 파일 검증: class_id가 0-based sequential인지 확인
        for txt_file in yolo_dir.glob("*.txt"):
            for line in txt_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                class_id = int(line.split()[0])
                assert class_id in {0, 1, 2}, f"비표준 YOLO class_id 발견: {class_id}"

        # 4. YOLO 재파싱 (data.yaml을 상위 디렉토리에 생성하여 클래스명 유지)
        from lib.pipeline.io.yolo_io import _write_yolo_data_yaml
        sorted_cats = sorted(yolo_meta.categories, key=lambda c: c["id"])
        _write_yolo_data_yaml(sorted_cats, yolo_dir.parent)

        from app.pipeline.io.yolo_io import parse_yolo_dir
        image_sizes = {
            "img_001": (IMAGE_1_WIDTH, IMAGE_1_HEIGHT),
            "img_002": (IMAGE_2_WIDTH, IMAGE_2_HEIGHT),
        }
        reparsed_yolo = parse_yolo_dir(yolo_dir, image_sizes=image_sizes)

        # 5. YOLO → COCO 변환 (ID 복원)
        to_coco = FormatConvertToCoco()
        final_coco = to_coco.transform_annotation(reparsed_yolo, params={})

        # 6. COCO JSON 쓰기 → 재파싱
        coco_output = tmp_path / "coco_roundtrip.json"
        write_coco_json(final_coco, coco_output)
        final_meta = parse_coco_json(coco_output)

        # 검증: category_id가 원래 COCO 비순차 ID로 복원되었는지
        final_cat_ids = sorted(
            {ann.category_id for rec in final_meta.image_records for ann in rec.annotations}
        )
        assert final_cat_ids == [1, 3, 6], f"복원된 COCO ID: {final_cat_ids}"
