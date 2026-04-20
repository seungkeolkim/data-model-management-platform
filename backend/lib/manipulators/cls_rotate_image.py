"""
cls_rotate_image — Classification 이미지 회전 manipulator (AUGMENT).

역할:
    이미지를 지정 각도(90°/180°/270°) 만큼 시계 방향으로 회전한다. Classification 은 bbox 가
    없으므로 annotation 좌표 변환은 수행하지 않고, 이미지 바이너리만 변형한다.
    head_schema / labels 는 회전과 무관하게 보존된다.

params:
    degrees: int — 회전 각도. 90 | 180 | 270 (필수, 기본값 180).

처리 흐름 (det_rotate_image 와 유사한 2단계):
    1. transform_annotation:
       - 90°/270° 회전 시 record.width ↔ record.height 교환
       - record.file_name 에 "_rotated_{degrees}" postfix 를 붙여 rename.
         v7.5 filename-identity (§2-13) 에서 "같은 파일명 = 같은 내용" 불변식을 지키려면,
         이미지 변형으로 내용이 바뀔 때는 새 파일명을 부여해야 한다.
       - 최초 변형 시에만 record.extra 에 source_storage_uri / original_file_name 을 기록하여
         Phase B 가 원본 src 를 복원할 수 있도록 한다 (merge 에서 이미 채워져 있다면 그대로 둠).
       - record.extra["image_manipulation_specs"] 에 rotate spec 누적.

    2. build_image_manipulation:
       - ImageManipulationSpec(operation="rotate_image", params={"degrees": N}) 반환.
       - 실제 픽셀 회전은 ImageMaterializer._apply_rotate 가 Phase B 에서 수행.

Phase B 경로 요약:
    src  = record.extra.source_storage_uri / record.extra.original_file_name
    dst  = output_storage_uri / record.file_name  (postfix 가 붙은 새 이름)
    ImageMaterializer 가 specs 순서대로 적용 후 dst 에 저장.
"""
from __future__ import annotations

import copy
import logging
import os.path
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import (
    DatasetMeta,
    ImageManipulationSpec,
    ImageRecord,
)

logger = logging.getLogger(__name__)

VALID_DEGREES: set[int] = {90, 180, 270}


class RotateImageClassification(UnitManipulator):
    """DB seed name: "cls_rotate_image"."""

    REQUIRED_PARAMS = ["degrees"]

    @property
    def name(self) -> str:
        return "cls_rotate_image"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        각 image_record 의 width/height 를 회전에 맞게 갱신하고, file_name 에 postfix 를
        붙여 rename 한다. 실제 이미지 바이너리 회전은 Phase B 가 수행한다.

        Args:
            input_meta: 단건 DatasetMeta (list 는 허용하지 않음).
            params:
                - degrees: int — 90 | 180 | 270 (기본 180).
            context: 실행 컨텍스트 (현재 사용 안 함).

        Returns:
            file_name / width / height / extra 가 갱신된 DatasetMeta (deep copy).

        Raises:
            TypeError: input_meta 가 list 인 경우.
            ValueError: degrees 가 VALID_DEGREES 에 속하지 않는 경우.
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_rotate_image 는 단건 DatasetMeta 만 입력 가능합니다."
            )

        degrees = int(params.get("degrees", 180))
        if degrees not in VALID_DEGREES:
            raise ValueError(
                f"degrees 는 {sorted(VALID_DEGREES)} 중 하나여야 합니다. 입력값: {degrees}"
            )

        rotated_meta = copy.deepcopy(input_meta)
        postfix = f"_rotated_{degrees}"

        for record in rotated_meta.image_records:
            # 90°/270° 에서만 가로·세로 교환. 180° 는 dimension 불변.
            if degrees in (90, 270) and record.width is not None and record.height is not None:
                record.width, record.height = record.height, record.width

            # src 복원용 메타데이터: 최초 변형 시에만 기록. merge 경로 등에서 이미
            # 채워져 있으면 그대로 둔다 (원본 추적 체인을 끊지 않기 위함).
            if "source_storage_uri" not in record.extra:
                record.extra["source_storage_uri"] = rotated_meta.storage_uri
            if "original_file_name" not in record.extra:
                record.extra["original_file_name"] = record.file_name

            record.file_name = _append_postfix_to_filename(record.file_name, postfix)

            existing_specs = record.extra.get("image_manipulation_specs", [])
            existing_specs.append({
                "operation": "rotate_image",
                "params": {"degrees": degrees},
            })
            record.extra["image_manipulation_specs"] = existing_specs

        logger.info(
            "cls_rotate_image 완료: %d장 이미지 × %d° 회전",
            len(rotated_meta.image_records), degrees,
        )

        return rotated_meta

    def build_image_manipulation(
        self,
        image_record: ImageRecord,
        params: dict[str, Any],
    ) -> list[ImageManipulationSpec]:
        """이미지 회전 변환 명세를 반환한다."""
        degrees = int(params.get("degrees", 180))
        return [ImageManipulationSpec(
            operation="rotate_image",
            params={"degrees": degrees},
        )]


def _append_postfix_to_filename(file_name: str, postfix: str) -> str:
    """
    확장자 앞에 postfix 를 삽입한다. 경로 prefix 는 유지.

    예:
        "images/truck_001.jpg" + "_rotated_180" → "images/truck_001_rotated_180.jpg"
        "truck_001.jpg"        + "_rotated_90"  → "truck_001_rotated_90.jpg"
        "noext"                + "_rotated_180" → "noext_rotated_180"
    """
    base_path, extension = os.path.splitext(file_name)
    return f"{base_path}{postfix}{extension}"
