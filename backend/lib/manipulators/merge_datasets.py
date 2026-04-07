"""
merge_datasets Manipulator.

복수의 DatasetMeta를 하나로 병합한다.
POST_MERGE scope 전용 — list[DatasetMeta]를 입력받아 단일 DatasetMeta를 반환.

핵심 처리:
  1. 파일명 충돌 감지 → 충돌 파일만 prefix 적용 ({dataset_name}_{4자리hash}_{원본파일명})
  2. 카테고리 통합 — 이름(name) 기준 union, category_id 재매핑
  3. 이미지 레코드 병합 — image_id 순차 재번호, 출처 정보(extra) 보존

파일명 prefix 규칙:
  - 서로 다른 소스에 동일 file_name이 존재하는 경우에만 적용
  - 충돌이 없는 파일은 원본 이름을 그대로 유지
  - prefix 형식: {dataset_name}_{md5(dataset_id)[:4]}_{원본파일명}

설계 원칙:
  - merge 이후 후속 DAG 노드가 결과를 이어받을 수 있도록 ImageRecord.extra에 출처 정보 보존
  - 매핑 테이블(file_name_mapping)은 rename된 파일만 기록 (불필요한 정보 최소화)
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from lib.pipeline.manipulator_base import UnitManipulator
from lib.pipeline.pipeline_data_models import Annotation, DatasetMeta, ImageRecord

logger = logging.getLogger(__name__)


class MergeDatasets(UnitManipulator):
    """
    복수 소스 데이터셋 병합 Manipulator.

    accepts_multi_input = True 로 표시하여 DAG executor가
    _merge_metas()를 건너뛰고 list[DatasetMeta]를 직접 전달하도록 한다.

    DB seed name: "merge_datasets"
    """

    accepts_multi_input: bool = True

    @property
    def name(self) -> str:
        return "merge_datasets"

    def transform_annotation(
        self,
        input_meta: DatasetMeta | list[DatasetMeta],
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> DatasetMeta:
        """
        복수 DatasetMeta를 하나로 병합한다.

        Args:
            input_meta: list[DatasetMeta] (2개 이상 필수)
            params: 현재 사용하지 않음 (향후 확장용)
            context: 실행 컨텍스트 (선택)

        Returns:
            병합된 DatasetMeta.
            extra에 file_name_mapping (rename된 파일만)과 source_dataset_ids를 포함.
            각 ImageRecord.extra에 source_dataset_id, source_storage_uri, original_file_name 포함.

        Raises:
            TypeError: input_meta가 list가 아닐 때
            ValueError: 소스가 2개 미만이거나 annotation_format이 불일치할 때
        """
        if not isinstance(input_meta, list):
            raise TypeError(
                "merge_datasets는 list[DatasetMeta]를 입력받아야 합니다. "
                f"받은 타입: {type(input_meta).__name__}"
            )
        if len(input_meta) < 2:
            raise ValueError(
                f"merge_datasets는 2개 이상의 소스가 필요합니다. "
                f"받은 소스 수: {len(input_meta)}"
            )

        # ── 포맷 일치 검증 ──
        _validate_annotation_formats(input_meta)

        # ── 소스별 hash 계산 (dataset_id 기반, 한 번만) ──
        dataset_hash_table = _build_dataset_hash_table(input_meta)

        # ── 파일명 충돌 감지 ──
        colliding_file_names = _detect_file_name_collisions(input_meta)

        if colliding_file_names:
            logger.info(
                "파일명 충돌 감지: %d개 파일명이 2개 이상의 소스에 존재",
                len(colliding_file_names),
            )

        # ── 카테고리 통합 (이름 기준) ──
        unified_categories, per_source_category_remap = _build_unified_categories(
            input_meta
        )

        # ── 이미지 레코드 병합 ──
        merged_records: list[ImageRecord] = []
        file_name_mapping: dict[str, dict[str, str]] = {}
        image_id_counter = 1

        for meta in input_meta:
            dataset_id = meta.dataset_id
            dataset_display_name, dataset_hash = dataset_hash_table[dataset_id]
            category_remap = per_source_category_remap[dataset_id]

            for record in meta.image_records:
                original_file_name = record.file_name

                # 충돌 파일만 prefix 적용
                if original_file_name in colliding_file_names:
                    new_file_name = (
                        f"{dataset_display_name}_{dataset_hash}_{original_file_name}"
                    )
                    # 매핑 테이블에 기록 (rename된 파일만)
                    file_name_mapping.setdefault(dataset_id, {})[
                        original_file_name
                    ] = new_file_name
                else:
                    new_file_name = original_file_name

                # annotation category_id 재매핑
                remapped_annotations = _remap_annotations(
                    record.annotations, category_remap
                )

                # 출처 정보를 extra에 저장 (모든 레코드, rename 여부 무관)
                merged_extra = {
                    **record.extra,
                    "source_dataset_id": dataset_id,
                    "source_storage_uri": meta.storage_uri,
                    "original_file_name": original_file_name,
                }

                merged_records.append(
                    ImageRecord(
                        image_id=image_id_counter,
                        file_name=new_file_name,
                        width=record.width,
                        height=record.height,
                        annotations=remapped_annotations,
                        extra=merged_extra,
                    )
                )
                image_id_counter += 1

        logger.info(
            "데이터셋 병합 완료: 소스 %d개, 총 이미지 %d장, 카테고리 %d개, rename %d건",
            len(input_meta),
            len(merged_records),
            len(unified_categories),
            sum(len(v) for v in file_name_mapping.values()),
        )

        return DatasetMeta(
            dataset_id="",
            storage_uri="",
            annotation_format=input_meta[0].annotation_format,
            categories=unified_categories,
            image_records=merged_records,
            extra={
                "file_name_mapping": file_name_mapping,
                "source_dataset_ids": [m.dataset_id for m in input_meta],
            },
        )


# ─────────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────────────────────────


def _validate_annotation_formats(metas: list[DatasetMeta]) -> None:
    """모든 소스의 annotation_format이 동일한지 검증한다."""
    formats = {meta.annotation_format.upper() for meta in metas}
    if len(formats) > 1:
        detail = [
            (meta.dataset_id, meta.annotation_format) for meta in metas
        ]
        raise ValueError(
            f"merge_datasets: 모든 소스의 annotation_format이 동일해야 합니다. "
            f"현재: {detail}"
        )


def _build_dataset_hash_table(
    metas: list[DatasetMeta],
) -> dict[str, tuple[str, str]]:
    """
    소스별 (표시용 이름, 4자리 hash) 테이블을 생성한다.

    hash는 dataset_id의 md5 앞 4자리. 소스당 한 번만 계산.

    Returns:
        {dataset_id: (display_name, hash_4char)}
    """
    table: dict[str, tuple[str, str]] = {}
    for meta in metas:
        display_name = meta.extra.get("dataset_name", meta.dataset_id[:8])
        hash_4char = hashlib.md5(meta.dataset_id.encode()).hexdigest()[:4]
        table[meta.dataset_id] = (display_name, hash_4char)
    return table


def _detect_file_name_collisions(
    metas: list[DatasetMeta],
) -> set[str]:
    """
    전체 소스에서 file_name을 수집하여 충돌(2개 이상의 소스에 존재)하는 파일명을 반환한다.

    Returns:
        충돌하는 file_name의 집합
    """
    # {file_name: 등장한 서로 다른 dataset_id 집합}
    file_name_sources: dict[str, set[str]] = {}
    for meta in metas:
        for record in meta.image_records:
            file_name_sources.setdefault(record.file_name, set()).add(
                meta.dataset_id
            )

    return {
        file_name
        for file_name, sources in file_name_sources.items()
        if len(sources) > 1
    }


def _build_unified_categories(
    metas: list[DatasetMeta],
) -> tuple[list[dict[str, Any]], dict[str, dict[int, int]]]:
    """
    카테고리를 이름(name) 기준으로 통합하고, 소스별 category_id 재매핑 테이블을 생성한다.

    annotation_format에 무관하게 동일한 전략을 적용한다:
      - 원본 category_id를 최대한 보존한다 (첫 등장 소스의 ID 유지).
      - 동일 이름의 카테고리가 여러 소스에 있으면 첫 등장한 소스의 ID를 사용.
      - 동일 이름인데 다른 ID인 경우 → 첫 등장 ID로 통일 (재매핑 로깅).
      - 동일 ID인데 다른 이름인 경우 → 충돌하는 쪽에 새 ID 할당 (91번부터).

    내부 표현에서 category_id는 포맷과 무관한 정수일 뿐이다.
    YOLO 저장 시 0-based 순차 재매핑은 write_yolo_dir()가 담당한다.

    Returns:
        (unified_categories, per_source_remap)
        per_source_remap: {dataset_id: {old_category_id: new_category_id}}
    """
    return _build_unified_categories_preserve_ids(metas)


def _build_unified_categories_preserve_ids(
    metas: list[DatasetMeta],
) -> tuple[list[dict[str, Any]], dict[str, dict[int, int]]]:
    """
    COCO 포맷용: 원본 category_id를 최대한 보존하여 통합한다.

    COCO 공식 80 클래스는 비순차 ID(1~90, 10개 빠짐)를 사용하므로
    merge 시에도 이 ID 체계를 유지해야 한다.

    처리 로직:
      1. 전체 소스에서 (이름 → 첫 등장 ID) 매핑을 수집
      2. 동일 이름이 서로 다른 ID로 등장하면 → 첫 등장 ID로 통일
      3. 서로 다른 이름이 같은 ID를 차지하면 → 나중 것에 새 ID 할당
      4. 새 ID 할당이 필요한 경우 기존 사용 ID와 충돌하지 않는 번호를 사용
    """
    # 이름 → 통합 ID (첫 등장한 소스의 ID를 사용)
    category_name_to_unified_id: dict[str, int] = {}
    # 사용 중인 ID 집합 (충돌 방지용)
    used_ids: set[int] = set()

    # 1단계: 모든 소스에서 카테고리 수집, 이름 기준 첫 등장 ID 확정
    for meta in metas:
        for category in meta.categories:
            category_name = category["name"]
            original_id = category["id"]

            if category_name not in category_name_to_unified_id:
                # 이 이름의 첫 등장
                if original_id not in used_ids:
                    # ID도 아직 사용되지 않음 → 그대로 사용
                    category_name_to_unified_id[category_name] = original_id
                    used_ids.add(original_id)
                else:
                    # ID가 이미 다른 이름에 의해 사용 중 → 새 ID 할당
                    new_id = _find_unused_id(used_ids)
                    category_name_to_unified_id[category_name] = new_id
                    used_ids.add(new_id)
                    logger.warning(
                        "카테고리 ID 충돌: '%s'의 원본 id=%d가 이미 사용 중 → id=%d 할당",
                        category_name, original_id, new_id,
                    )

    # 통합 categories 리스트 구성 (ID 오름차순 정렬)
    unified_categories: list[dict[str, Any]] = [
        {"id": unified_id, "name": name}
        for name, unified_id in sorted(
            category_name_to_unified_id.items(), key=lambda item: item[1]
        )
    ]

    # 2단계: 소스별 재매핑 테이블 생성
    per_source_remap: dict[str, dict[int, int]] = {}
    for meta in metas:
        remap: dict[int, int] = {}
        for category in meta.categories:
            old_id = category["id"]
            unified_id = category_name_to_unified_id[category["name"]]
            remap[old_id] = unified_id

            if old_id != unified_id:
                logger.info(
                    "카테고리 ID 재매핑: dataset=%s, '%s' id %d → %d",
                    meta.dataset_id, category["name"], old_id, unified_id,
                )

        per_source_remap[meta.dataset_id] = remap

    return unified_categories, per_source_remap


def _find_unused_id(used_ids: set[int], start: int = 91) -> int:
    """사용되지 않는 category_id를 찾아 반환한다. COCO 공식 max는 90이므로 91부터 탐색."""
    candidate = start
    while candidate in used_ids:
        candidate += 1
    return candidate


def _remap_annotations(
    annotations: list[Annotation],
    category_remap: dict[int, int],
) -> list[Annotation]:
    """
    annotation 리스트의 category_id를 재매핑 테이블에 따라 변환한다.
    원본을 수정하지 않고 새 Annotation 객체를 생성한다.

    Args:
        annotations: 원본 annotation 리스트
        category_remap: {old_category_id: new_category_id}

    Returns:
        재매핑된 새 Annotation 리스트
    """
    remapped: list[Annotation] = []
    for annotation in annotations:
        new_category_id = category_remap.get(
            annotation.category_id, annotation.category_id
        )
        remapped.append(
            Annotation(
                annotation_type=annotation.annotation_type,
                category_id=new_category_id,
                bbox=annotation.bbox,
                segmentation=annotation.segmentation,
                label=annotation.label,
                attributes=annotation.attributes,
                extra=annotation.extra,
            )
        )
    return remapped
