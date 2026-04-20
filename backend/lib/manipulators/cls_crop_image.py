"""
cls_crop_image — Classification 이미지 Crop manipulator (AUGMENT).

역할:
    이미지의 상단(=위쪽) 또는 하단(=아래쪽) 영역을 전체 height 의 지정 비율(%)만큼
    잘라낸다. width 는 변하지 않고, 결과 height 는 원본 height 의 (100 - crop_pct)% 가
    된다. Classification 은 bbox 가 없으므로 annotation 좌표 변환은 없으며,
    head_schema / labels 는 crop 과 무관하게 보존된다.

params:
    direction: select("상단"|"하단") — Crop 영역 선택. 필수, 기본 "상단".
    crop_pct:  number(1~99)          — 잘라낼 비율. 필수, 기본 30.

처리 흐름 (cls_rotate_image 와 동일한 2단계 패턴):
    1. transform_annotation:
       - record.height 를 (100 - crop_pct)% 로 축소 (정수 내림). width 는 유지.
       - record.file_name 에 "_crop_up_{crop_pct:03d}" / "_crop_down_{crop_pct:03d}"
         postfix 를 붙여 rename. v7.5 filename-identity (§2-13) 에서 "같은 파일명 =
         같은 내용" 을 지키기 위함.
       - 최초 변형 시에만 record.extra 에 source_storage_uri / original_file_name 을
         기록 (이미 채워져 있으면 그대로 둠 — merge 경로 추적 체인 유지).
       - record.extra["image_manipulation_specs"] 에 crop spec 을 누적.

    2. build_image_manipulation:
       - ImageManipulationSpec(operation="crop_image_vertical",
                               params={"direction": "up"|"down", "crop_pct": N}) 반환.
       - 실제 픽셀 crop 은 ImageMaterializer._apply_crop_vertical 이 Phase B 에서 수행.

설계 결정:
    - direction 은 Korean("상단"/"하단") 으로 입력받지만, 내부 spec 및 파일명 postfix 는
      English("up"/"down") 로 정규화한다. UI 다국어화 시에도 spec 이 안정적이고,
      파일명 규약이 ASCII 로 유지된다.
    - crop_pct 범위는 [1, 99]. 0 또는 100 은 의미가 없고(전체 또는 소멸), 중간 정수만 허용.
    - 이미지 변형이므로 lazy copy 대상이 아님 — Phase B 에서 실체화된다.
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

# direction(Korean) → 내부 표기(English). 파일명 postfix 와 spec params 에서 사용.
_DIRECTION_TO_CODE: dict[str, str] = {
    "상단": "up",
    "하단": "down",
}


class CropImageClassification(UnitManipulator):
    """DB seed name: "cls_crop_image"."""

    REQUIRED_PARAMS = ["direction", "crop_pct"]

    @property
    def name(self) -> str:
        return "cls_crop_image"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        각 image_record 의 height 를 crop 후 값으로 갱신하고, file_name 에 postfix 를 붙여
        rename 한다. 실제 이미지 바이너리 crop 은 Phase B 가 수행한다.

        Args:
            input_meta: 단건 DatasetMeta (list 는 허용하지 않음).
            params:
                - direction: "상단" | "하단" (기본 "상단").
                - crop_pct:  int, 1 ≤ crop_pct ≤ 99 (기본 30).
            context: 실행 컨텍스트 (현재 사용 안 함).

        Returns:
            file_name / height / extra 가 갱신된 DatasetMeta (deep copy).

        Raises:
            TypeError: input_meta 가 list 인 경우.
            ValueError: direction 이 _DIRECTION_TO_CODE 밖, 또는 crop_pct 가 정수
                        [1, 99] 범위를 벗어나는 경우.
        """
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_crop_image 는 단건 DatasetMeta 만 입력 가능합니다."
            )

        direction_code = _parse_direction(params.get("direction", "상단"))
        crop_pct = _parse_crop_pct(params.get("crop_pct", 30))

        cropped_meta = copy.deepcopy(input_meta)
        postfix = f"_crop_{direction_code}_{crop_pct:03d}"
        remain_ratio = (100 - crop_pct) / 100.0

        for record in cropped_meta.image_records:
            # height 가 알려져 있을 때만 축소 계산. 정수 내림 — Phase B 픽셀 crop 과 일치.
            if record.height is not None:
                new_height = max(1, int(record.height * remain_ratio))
                record.height = new_height

            # src 복원용 메타데이터: 최초 변형 시에만 기록. merge 등으로 이미 채워져
            # 있으면 그대로 둔다 (원본 추적 체인 보존).
            if "source_storage_uri" not in record.extra:
                record.extra["source_storage_uri"] = cropped_meta.storage_uri
            if "original_file_name" not in record.extra:
                record.extra["original_file_name"] = record.file_name

            record.file_name = _append_postfix_to_filename(record.file_name, postfix)

            existing_specs = record.extra.get("image_manipulation_specs", [])
            existing_specs.append({
                "operation": "crop_image_vertical",
                "params": {"direction": direction_code, "crop_pct": crop_pct},
            })
            record.extra["image_manipulation_specs"] = existing_specs

        logger.info(
            "cls_crop_image 완료: %d장 이미지 × direction=%s crop_pct=%d%%",
            len(cropped_meta.image_records), direction_code, crop_pct,
        )

        return cropped_meta

    def build_image_manipulation(
        self,
        image_record: ImageRecord,
        params: dict[str, Any],
    ) -> list[ImageManipulationSpec]:
        """이미지 vertical crop 변환 명세를 반환한다."""
        direction_code = _parse_direction(params.get("direction", "상단"))
        crop_pct = _parse_crop_pct(params.get("crop_pct", 30))
        return [ImageManipulationSpec(
            operation="crop_image_vertical",
            params={"direction": direction_code, "crop_pct": crop_pct},
        )]


# =============================================================================
# 내부 파싱 헬퍼
# =============================================================================


def _parse_direction(raw_value: Any) -> str:
    """
    direction 파라미터를 내부 표기("up"|"down") 로 정규화.

    허용 입력:
        - "상단" / "하단" — Korean (seed default 및 DynamicParamForm 전달값).
        - "up"   / "down" — 이미 정규화된 English 표기도 관용적으로 허용.

    그 외에는 ValueError.
    """
    if raw_value is None:
        raise ValueError("direction 은 필수 입력입니다 ('상단' 또는 '하단').")
    if not isinstance(raw_value, str):
        raise ValueError(
            f"direction 은 문자열이어야 합니다: {type(raw_value).__name__}"
        )

    stripped = raw_value.strip()
    if stripped in _DIRECTION_TO_CODE:
        return _DIRECTION_TO_CODE[stripped]
    if stripped in ("up", "down"):
        return stripped

    raise ValueError(
        f"direction 은 '상단' 또는 '하단' 이어야 합니다. 입력값: {raw_value!r}"
    )


def _parse_crop_pct(raw_value: Any) -> int:
    """
    crop_pct 파라미터를 정수로 정규화. 허용 범위 [1, 99].

    허용 입력: int / float(정수값) / 숫자 문자열. bool 은 거부.
    """
    if isinstance(raw_value, bool):
        raise ValueError(
            f"crop_pct 는 정수여야 합니다: {type(raw_value).__name__}"
        )
    if raw_value is None:
        raise ValueError("crop_pct 는 필수 입력입니다 (1~99 사이 정수).")

    try:
        crop_pct = int(raw_value)
    except (TypeError, ValueError) as parse_error:
        raise ValueError(
            f"crop_pct 를 정수로 해석할 수 없습니다: {raw_value!r}"
        ) from parse_error

    # float 였던 경우 소수부가 있으면 거부 (예: 30.5 입력은 명시적으로 차단).
    if isinstance(raw_value, float) and not raw_value.is_integer():
        raise ValueError(
            f"crop_pct 는 정수여야 합니다 (소수 입력 불가): {raw_value}"
        )

    if crop_pct < 1 or crop_pct > 99:
        raise ValueError(
            f"crop_pct 는 1 이상 99 이하 정수여야 합니다. 입력값: {crop_pct}"
        )

    return crop_pct


def _append_postfix_to_filename(file_name: str, postfix: str) -> str:
    """
    확장자 앞에 postfix 를 삽입한다. 경로 prefix 는 유지.

    예:
        "images/truck_001.jpg" + "_crop_up_030"   → "images/truck_001_crop_up_030.jpg"
        "truck_001.jpg"        + "_crop_down_050" → "truck_001_crop_down_050.jpg"
        "noext"                + "_crop_up_010"   → "noext_crop_up_010"
    """
    base_path, extension = os.path.splitext(file_name)
    return f"{base_path}{postfix}{extension}"
