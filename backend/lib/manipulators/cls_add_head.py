"""
cls_add_head — Classification 데이터셋에 신규 Head 를 추가하는 manipulator.

역할:
    기존 classification DatasetMeta 에 새로운 head 를 하나 추가한다. head_schema 말단에
    추가되며(순서 규약: 맨 뒤), 모든 기존 이미지의 신규 head labels 는 `null` (unknown)
    으로 초기화된다. §2-12 의 null=unknown 규약을 그대로 따른다.

params:
    head_name:        text      — 신규 head 이름 (필수, 비어있지 않은 문자열, 기존 head 와 중복 금지).
    multi_label:      checkbox  — 체크 시 multi-label head (기본 False = single-label).
    class_candidates: textarea  — class 이름 목록. 줄바꿈 구분. list[str] 도 허용.
                                   trim 후 비어있는 줄은 제외, 중복 class 이름은 ValueError.
                                   class 는 2개 이상이어야 함.

설계 결정:
    - 신규 head 는 head_schema 배열의 **맨 뒤**에 추가한다 (순서 재배치가 필요하면
      cls_reorder_heads 를 이어서 쓴다).
    - 기존 이미지의 신규 head labels 는 **전부 null**. `[]` (explicit empty) 이 아니라 `null`
      인 이유: 해당 이미지에 대해 신규 head 의 라벨을 "아직 모른다" 가 맞는 의미 — §2-12.
    - class 이름 순서는 사용자가 textarea 에 입력한 순서 그대로 = 학습 output index 의 SSOT
      (§2-4 head_schema 계약).

이미지 바이너리 불변 → file_name 유지 → Phase B 는 lazy copy.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import DatasetMeta, HeadSchema, ImageRecord

logger = logging.getLogger(__name__)


class AddHeadClassification(UnitManipulator):
    """DB seed name: "cls_add_head"."""

    REQUIRED_PARAMS = ["head_name", "class_candidates"]

    @property
    def name(self) -> str:
        return "cls_add_head"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        if isinstance(input_meta, list):
            raise TypeError(
                "cls_add_head 는 단건 DatasetMeta 만 입력 가능합니다 (list 입력 불가)."
            )
        if input_meta.head_schema is None:
            raise ValueError(
                "cls_add_head 는 classification DatasetMeta 에만 사용합니다 "
                "(head_schema 가 None 입니다)."
            )

        new_head_name = self._parse_head_name(params.get("head_name"))
        multi_label = self._parse_multi_label(params.get("multi_label", False))
        class_candidates = self._parse_class_candidates(params.get("class_candidates"))

        # ── 기존 head 와 이름 충돌 검사 ──
        existing_head_names = [head.name for head in input_meta.head_schema]
        if new_head_name in existing_head_names:
            raise ValueError(
                f"cls_add_head: head_name='{new_head_name}' 은 이미 존재합니다. "
                f"기존 head: {existing_head_names}"
            )

        # ── head_schema 재구성: 기존 유지 + 맨 뒤에 신규 head 추가 ──
        new_head_schema = [
            HeadSchema(
                name=head.name,
                multi_label=head.multi_label,
                classes=list(head.classes),
            )
            for head in input_meta.head_schema
        ]
        new_head_schema.append(
            HeadSchema(
                name=new_head_name,
                multi_label=multi_label,
                classes=list(class_candidates),
            )
        )

        # ── 모든 이미지에 신규 head 를 null(unknown) 으로 추가 ──
        new_records: list[ImageRecord] = []
        for record in input_meta.image_records:
            source_labels = record.labels or {}
            new_labels: dict[str, list[str] | None] = {
                head_name: (list(class_names) if class_names is not None else None)
                for head_name, class_names in source_labels.items()
            }
            new_labels[new_head_name] = None
            new_records.append(
                replace(
                    record,
                    labels=new_labels,
                    extra=dict(record.extra) if record.extra else {},
                )
            )

        logger.info(
            "cls_add_head 완료: head='%s' (multi_label=%s, classes=%d개) 추가, "
            "총 %d장 이미지에 null 라벨 초기화",
            new_head_name,
            multi_label,
            len(class_candidates),
            len(new_records),
        )

        return DatasetMeta(
            dataset_id=input_meta.dataset_id,
            storage_uri=input_meta.storage_uri,
            categories=[],
            image_records=new_records,
            head_schema=new_head_schema,
            extra=dict(input_meta.extra) if input_meta.extra else {},
        )

    # ─────────────────────────────────────────────────────────────
    # params 파싱 헬퍼
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_head_name(raw_value: Any) -> str:
        """head_name 을 str 로 정규화. 비어있으면 ValueError."""
        if raw_value is None:
            raise ValueError("head_name 은 필수 입력입니다.")
        if not isinstance(raw_value, str):
            raise ValueError(
                f"head_name 은 문자열이어야 합니다: {type(raw_value).__name__}"
            )
        stripped = raw_value.strip()
        if not stripped:
            raise ValueError("head_name 이 공백입니다. 신규 Head 이름을 지정하세요.")
        return stripped

    @staticmethod
    def _parse_multi_label(raw_value: Any) -> bool:
        """multi_label checkbox 값을 bool 로 정규화. 기본 False."""
        # Python bool / None / 문자열 "true"/"false" 모두 수용.
        if isinstance(raw_value, bool):
            return raw_value
        if raw_value is None:
            return False
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in ("true", "1", "yes", "on"):
                return True
            if normalized in ("false", "0", "no", "off", ""):
                return False
            raise ValueError(
                f"multi_label 문자열 값은 true/false 계열이어야 합니다: {raw_value!r}"
            )
        raise ValueError(
            f"multi_label 은 bool 이어야 합니다: {type(raw_value).__name__}"
        )

    @staticmethod
    def _parse_class_candidates(raw_value: Any) -> list[str]:
        """
        class_candidates 를 list[str] 로 정규화.

        허용 입력:
            - str (textarea): 줄바꿈 구분, trim 후 빈 줄 제외.
            - list[str] / tuple[str]: 각 원소 trim 후 빈 값 제외.

        검증:
            - 2개 이상 필수 (1개면 class 선택 여지가 없어 무의미).
            - 중복 class 이름 금지.
        """
        if raw_value is None:
            raise ValueError("class_candidates 는 필수 입력입니다.")

        if isinstance(raw_value, str):
            candidates = [line.strip() for line in raw_value.splitlines() if line.strip()]
        elif isinstance(raw_value, (list, tuple)):
            candidates = [str(item).strip() for item in raw_value if str(item).strip()]
        else:
            raise ValueError(
                f"class_candidates 는 str 또는 list 이어야 합니다: "
                f"{type(raw_value).__name__}"
            )

        if len(candidates) < 2:
            raise ValueError(
                f"class_candidates 는 2개 이상이어야 합니다. 입력값: {candidates}"
            )

        # 중복 검사 (순서를 유지한 채 ValueError 를 던지기 위해 수동 체크).
        seen: set[str] = set()
        duplicates: list[str] = []
        for name in candidates:
            if name in seen:
                duplicates.append(name)
            seen.add(name)
        if duplicates:
            raise ValueError(
                f"class_candidates 에 중복된 class 이름이 있습니다: {duplicates}"
            )

        return candidates
