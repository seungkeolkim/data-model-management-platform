"""
COCO JSON 포맷 파서 및 라이터.

COCO JSON ↔ DatasetMeta 변환을 담당하는 순수 함수 모듈.
파일 I/O만 수행하며, DB나 서비스 레이어에 의존하지 않는다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from lib.pipeline.models import Annotation, DatasetMeta, ImageRecord


def parse_coco_json(
    json_path: Path,
    dataset_id: str = "",
    storage_uri: str = "",
) -> DatasetMeta:
    """
    COCO JSON 파일을 읽어 DatasetMeta로 변환한다.

    변환 규칙:
      - images 배열 → ImageRecord (image_id, file_name, width, height)
      - annotations 배열 → Annotation (BBOX 타입, category_id, bbox [x,y,w,h] absolute)
      - categories 배열 → DatasetMeta.categories
      - area, iscrowd 등 추가 필드는 Annotation.extra에 보존

    Args:
        json_path: COCO JSON 파일 경로
        dataset_id: DatasetMeta.dataset_id (빈 문자열 허용)
        storage_uri: DatasetMeta.storage_uri (빈 문자열 허용)

    Returns:
        파싱된 DatasetMeta (annotation_format="COCO")

    Raises:
        FileNotFoundError: json_path가 존재하지 않을 때
        ValueError: 필수 키(images, annotations, categories)가 없을 때
    """
    with open(json_path, "r", encoding="utf-8") as file_handle:
        coco_data: dict[str, Any] = json.load(file_handle)

    # 필수 키 검증
    required_keys = {"images", "annotations", "categories"}
    missing_keys = required_keys - set(coco_data.keys())
    if missing_keys:
        raise ValueError(
            f"COCO JSON에 필수 키가 없습니다: {sorted(missing_keys)}"
        )

    # categories 변환: [{id, name, supercategory?}]
    categories = []
    for category in coco_data["categories"]:
        category_entry: dict[str, Any] = {
            "id": category["id"],
            "name": category["name"],
        }
        if "supercategory" in category:
            category_entry["supercategory"] = category["supercategory"]
        categories.append(category_entry)

    # images → ImageRecord dict (image_id → ImageRecord)
    image_record_by_id: dict[int, ImageRecord] = {}
    for image_entry in coco_data["images"]:
        image_id = image_entry["id"]
        image_record_by_id[image_id] = ImageRecord(
            image_id=image_id,
            file_name=image_entry["file_name"],
            width=image_entry.get("width"),
            height=image_entry.get("height"),
        )

    # annotations → 각 ImageRecord에 Annotation 추가
    # COCO bbox 필드 외의 나머지는 extra에 보존
    _ANNOTATION_CORE_KEYS = {"id", "image_id", "category_id", "bbox", "segmentation"}

    for annotation_entry in coco_data["annotations"]:
        image_id = annotation_entry["image_id"]
        if image_id not in image_record_by_id:
            # image에 없는 annotation은 무시 (데이터 불일치 허용)
            continue

        # extra: 핵심 키 외의 모든 필드 보존 (area, iscrowd 등)
        extra_fields = {
            key: value
            for key, value in annotation_entry.items()
            if key not in _ANNOTATION_CORE_KEYS
        }

        # segmentation 처리
        raw_segmentation = annotation_entry.get("segmentation")
        segmentation = None
        if isinstance(raw_segmentation, list) and raw_segmentation:
            segmentation = raw_segmentation

        annotation = Annotation(
            annotation_type="BBOX",
            category_id=annotation_entry["category_id"],
            bbox=annotation_entry.get("bbox"),
            segmentation=segmentation,
            extra=extra_fields,
        )
        image_record_by_id[image_id].annotations.append(annotation)

    # image_id 순서 유지하여 리스트로 변환
    sorted_image_records = sorted(
        image_record_by_id.values(), key=lambda record: record.image_id
    )

    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=storage_uri,
        annotation_format="COCO",
        categories=categories,
        image_records=sorted_image_records,
    )


def write_coco_json(
    meta: DatasetMeta,
    output_path: Path,
) -> Path:
    """
    DatasetMeta를 COCO JSON 파일로 출력한다.

    변환 규칙:
      - ImageRecord → images 배열
      - Annotation → annotations 배열 (annotation id 자동 순차 생성)
      - categories → categories 배열
      - area: Annotation.extra에 있으면 사용, 없으면 bbox w*h로 계산
      - iscrowd: Annotation.extra에 있으면 사용, 없으면 0

    Args:
        meta: 출력할 DatasetMeta
        output_path: 출력 JSON 파일 경로

    Returns:
        output_path (동일 경로 반환)
    """
    # images 배열 구성
    coco_images = []
    for image_record in meta.image_records:
        image_entry: dict[str, Any] = {
            "id": image_record.image_id,
            "file_name": image_record.file_name,
        }
        if image_record.width is not None:
            image_entry["width"] = image_record.width
        if image_record.height is not None:
            image_entry["height"] = image_record.height
        coco_images.append(image_entry)

    # annotations 배열 구성 (id 자동 순차 생성)
    coco_annotations = []
    annotation_id_counter = 1

    for image_record in meta.image_records:
        for annotation in image_record.annotations:
            annotation_entry: dict[str, Any] = {
                "id": annotation_id_counter,
                "image_id": image_record.image_id,
                "category_id": annotation.category_id,
            }

            if annotation.bbox is not None:
                annotation_entry["bbox"] = annotation.bbox
                # area 계산: extra에 있으면 사용, 없으면 w*h
                if "area" in annotation.extra:
                    annotation_entry["area"] = annotation.extra["area"]
                else:
                    annotation_entry["area"] = annotation.bbox[2] * annotation.bbox[3]
            else:
                annotation_entry["area"] = annotation.extra.get("area", 0)

            # segmentation 복원
            if annotation.segmentation is not None:
                annotation_entry["segmentation"] = annotation.segmentation

            # iscrowd 복원
            annotation_entry["iscrowd"] = annotation.extra.get("iscrowd", 0)

            # extra의 나머지 필드도 복원 (area, iscrowd 제외 — 이미 처리됨)
            for key, value in annotation.extra.items():
                if key not in ("area", "iscrowd") and key not in annotation_entry:
                    annotation_entry[key] = value

            coco_annotations.append(annotation_entry)
            annotation_id_counter += 1

    # categories 배열 구성
    coco_categories = []
    for category in meta.categories:
        category_entry: dict[str, Any] = {
            "id": category["id"],
            "name": category["name"],
        }
        if "supercategory" in category:
            category_entry["supercategory"] = category["supercategory"]
        coco_categories.append(category_entry)

    coco_output = {
        "images": coco_images,
        "annotations": coco_annotations,
        "categories": coco_categories,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file_handle:
        json.dump(coco_output, file_handle, ensure_ascii=False, indent=2)

    return output_path
