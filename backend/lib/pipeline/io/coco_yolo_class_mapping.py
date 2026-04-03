"""
COCO ↔ YOLO 표준 클래스 매핑 테이블.

COCO 2017 공식 80 클래스의 category_id는 비순차(1~90, 10개 빠짐)이고,
YOLO는 동일 80 클래스를 0~79 순차 ID로 사용한다.
이 모듈은 두 ID 체계 간 변환 테이블과 유틸리티 함수를 제공한다.

사용 예시:
  - COCO→YOLO 변환 시: coco_id=13(stop sign) → yolo_id=11
  - YOLO→COCO 변환 시: yolo_id=11 → coco_id=13(stop sign)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================================
# COCO 2017 공식 80 클래스 (coco_id 순서)
# YOLO class_id는 이 리스트의 인덱스(0-based, 0~79)
# =============================================================================

COCO_80_CLASSES: list[dict[str, Any]] = [
    {"coco_id": 1,  "yolo_id": 0,  "name": "person"},
    {"coco_id": 2,  "yolo_id": 1,  "name": "bicycle"},
    {"coco_id": 3,  "yolo_id": 2,  "name": "car"},
    {"coco_id": 4,  "yolo_id": 3,  "name": "motorcycle"},
    {"coco_id": 5,  "yolo_id": 4,  "name": "airplane"},
    {"coco_id": 6,  "yolo_id": 5,  "name": "bus"},
    {"coco_id": 7,  "yolo_id": 6,  "name": "train"},
    {"coco_id": 8,  "yolo_id": 7,  "name": "truck"},
    {"coco_id": 9,  "yolo_id": 8,  "name": "boat"},
    {"coco_id": 10, "yolo_id": 9,  "name": "traffic light"},
    {"coco_id": 11, "yolo_id": 10, "name": "fire hydrant"},
    {"coco_id": 13, "yolo_id": 11, "name": "stop sign"},
    {"coco_id": 14, "yolo_id": 12, "name": "parking meter"},
    {"coco_id": 15, "yolo_id": 13, "name": "bench"},
    {"coco_id": 16, "yolo_id": 14, "name": "bird"},
    {"coco_id": 17, "yolo_id": 15, "name": "cat"},
    {"coco_id": 18, "yolo_id": 16, "name": "dog"},
    {"coco_id": 19, "yolo_id": 17, "name": "horse"},
    {"coco_id": 20, "yolo_id": 18, "name": "sheep"},
    {"coco_id": 21, "yolo_id": 19, "name": "cow"},
    {"coco_id": 22, "yolo_id": 20, "name": "elephant"},
    {"coco_id": 23, "yolo_id": 21, "name": "bear"},
    {"coco_id": 24, "yolo_id": 22, "name": "zebra"},
    {"coco_id": 25, "yolo_id": 23, "name": "giraffe"},
    {"coco_id": 27, "yolo_id": 24, "name": "backpack"},
    {"coco_id": 28, "yolo_id": 25, "name": "umbrella"},
    {"coco_id": 31, "yolo_id": 26, "name": "handbag"},
    {"coco_id": 32, "yolo_id": 27, "name": "tie"},
    {"coco_id": 33, "yolo_id": 28, "name": "suitcase"},
    {"coco_id": 34, "yolo_id": 29, "name": "frisbee"},
    {"coco_id": 35, "yolo_id": 30, "name": "skis"},
    {"coco_id": 36, "yolo_id": 31, "name": "snowboard"},
    {"coco_id": 37, "yolo_id": 32, "name": "sports ball"},
    {"coco_id": 38, "yolo_id": 33, "name": "kite"},
    {"coco_id": 39, "yolo_id": 34, "name": "baseball bat"},
    {"coco_id": 40, "yolo_id": 35, "name": "baseball glove"},
    {"coco_id": 41, "yolo_id": 36, "name": "skateboard"},
    {"coco_id": 42, "yolo_id": 37, "name": "surfboard"},
    {"coco_id": 43, "yolo_id": 38, "name": "tennis racket"},
    {"coco_id": 44, "yolo_id": 39, "name": "bottle"},
    {"coco_id": 46, "yolo_id": 40, "name": "wine glass"},
    {"coco_id": 47, "yolo_id": 41, "name": "cup"},
    {"coco_id": 48, "yolo_id": 42, "name": "fork"},
    {"coco_id": 49, "yolo_id": 43, "name": "knife"},
    {"coco_id": 50, "yolo_id": 44, "name": "spoon"},
    {"coco_id": 51, "yolo_id": 45, "name": "bowl"},
    {"coco_id": 52, "yolo_id": 46, "name": "banana"},
    {"coco_id": 53, "yolo_id": 47, "name": "apple"},
    {"coco_id": 54, "yolo_id": 48, "name": "sandwich"},
    {"coco_id": 55, "yolo_id": 49, "name": "orange"},
    {"coco_id": 56, "yolo_id": 50, "name": "broccoli"},
    {"coco_id": 57, "yolo_id": 51, "name": "carrot"},
    {"coco_id": 58, "yolo_id": 52, "name": "hot dog"},
    {"coco_id": 59, "yolo_id": 53, "name": "pizza"},
    {"coco_id": 60, "yolo_id": 54, "name": "donut"},
    {"coco_id": 61, "yolo_id": 55, "name": "cake"},
    {"coco_id": 62, "yolo_id": 56, "name": "chair"},
    {"coco_id": 63, "yolo_id": 57, "name": "couch"},
    {"coco_id": 64, "yolo_id": 58, "name": "potted plant"},
    {"coco_id": 65, "yolo_id": 59, "name": "bed"},
    {"coco_id": 67, "yolo_id": 60, "name": "dining table"},
    {"coco_id": 70, "yolo_id": 61, "name": "toilet"},
    {"coco_id": 72, "yolo_id": 62, "name": "tv"},
    {"coco_id": 73, "yolo_id": 63, "name": "laptop"},
    {"coco_id": 74, "yolo_id": 64, "name": "mouse"},
    {"coco_id": 75, "yolo_id": 65, "name": "remote"},
    {"coco_id": 76, "yolo_id": 66, "name": "keyboard"},
    {"coco_id": 77, "yolo_id": 67, "name": "cell phone"},
    {"coco_id": 78, "yolo_id": 68, "name": "microwave"},
    {"coco_id": 79, "yolo_id": 69, "name": "oven"},
    {"coco_id": 80, "yolo_id": 70, "name": "toaster"},
    {"coco_id": 81, "yolo_id": 71, "name": "sink"},
    {"coco_id": 82, "yolo_id": 72, "name": "refrigerator"},
    {"coco_id": 84, "yolo_id": 73, "name": "book"},
    {"coco_id": 85, "yolo_id": 74, "name": "clock"},
    {"coco_id": 86, "yolo_id": 75, "name": "vase"},
    {"coco_id": 87, "yolo_id": 76, "name": "scissors"},
    {"coco_id": 88, "yolo_id": 77, "name": "teddy bear"},
    {"coco_id": 89, "yolo_id": 78, "name": "hair drier"},
    {"coco_id": 90, "yolo_id": 79, "name": "toothbrush"},
]

# 빠른 조회용 사전: coco_id → yolo_id
COCO_ID_TO_YOLO_ID: dict[int, int] = {
    entry["coco_id"]: entry["yolo_id"] for entry in COCO_80_CLASSES
}

# 빠른 조회용 사전: yolo_id → coco_id
YOLO_ID_TO_COCO_ID: dict[int, int] = {
    entry["yolo_id"]: entry["coco_id"] for entry in COCO_80_CLASSES
}

# 빠른 조회용 사전: coco_id → class name
COCO_ID_TO_NAME: dict[int, str] = {
    entry["coco_id"]: entry["name"] for entry in COCO_80_CLASSES
}

# 빠른 조회용 사전: yolo_id → class name
YOLO_ID_TO_NAME: dict[int, str] = {
    entry["yolo_id"]: entry["name"] for entry in COCO_80_CLASSES
}

# 빠른 조회용 사전: class name → coco_id
NAME_TO_COCO_ID: dict[str, int] = {
    entry["name"]: entry["coco_id"] for entry in COCO_80_CLASSES
}

# 빠른 조회용 사전: class name → yolo_id
NAME_TO_YOLO_ID: dict[str, int] = {
    entry["name"]: entry["yolo_id"] for entry in COCO_80_CLASSES
}


def build_coco_to_yolo_remap(
    coco_categories: list[dict[str, Any]],
    custom_mapping: dict[int, int] | None = None,
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    """
    COCO category_id → YOLO class_id 매핑 테이블을 구성한다.

    YOLO format 제약: class_id는 반드시 0-based sequential이어야 한다.
    따라서 입력 categories를 **표준 COCO 순서(yolo_id 기준)**로 정렬한 뒤
    0, 1, 2, ... 순차 할당한다. 미지의 클래스는 표준 클래스 뒤에 배치.

    custom_mapping이 있으면 최우선으로 적용한다.

    Args:
        coco_categories: 입력 DatasetMeta의 categories 리스트 [{id, name, ...}]
        custom_mapping: 사용자 지정 {coco_id: yolo_id} 매핑 (선택)

    Returns:
        (remap_table, new_categories) 튜플
        - remap_table: {원본_coco_id: 변환될_yolo_id}
        - new_categories: YOLO용 categories 리스트 [{id: 0-based, name: ...}]
    """
    if custom_mapping:
        # custom_mapping이 있으면 그대로 사용
        remap_table: dict[int, int] = {}
        new_categories: list[dict[str, Any]] = []
        for category in coco_categories:
            coco_id = category["id"]
            category_name = category.get("name", str(coco_id))
            if coco_id in custom_mapping:
                yolo_id = custom_mapping[coco_id]
            elif coco_id in COCO_ID_TO_YOLO_ID:
                yolo_id = COCO_ID_TO_YOLO_ID[coco_id]
            else:
                yolo_id = coco_id
            remap_table[coco_id] = yolo_id
            new_categories.append({"id": yolo_id, "name": category_name})
        new_categories.sort(key=lambda cat: cat["id"])
        return remap_table, new_categories

    # 표준 COCO 순서로 정렬하여 0-based sequential 할당
    # 표준 클래스: COCO_ID_TO_YOLO_ID[coco_id] 값(표준 yolo 순서)으로 정렬
    # 미지의 클래스: 표준 클래스 뒤에 coco_id 순서로 배치
    standard_entries: list[tuple[int, str, int]] = []  # (sort_key, name, coco_id)
    unknown_entries: list[tuple[int, str]] = []  # (coco_id, name)

    for category in coco_categories:
        coco_id = category["id"]
        category_name = category.get("name", str(coco_id))
        if coco_id in COCO_ID_TO_YOLO_ID:
            standard_yolo_order = COCO_ID_TO_YOLO_ID[coco_id]
            standard_entries.append((standard_yolo_order, category_name, coco_id))
        else:
            unknown_entries.append((coco_id, category_name))
            logger.info(
                "표준 매핑에 없는 클래스 발견: coco_id=%d, name='%s'",
                coco_id, category_name,
            )

    # 표준 COCO 순서대로 정렬 (person 먼저, bicycle, car, ...)
    standard_entries.sort(key=lambda entry: entry[0])
    # 미지의 클래스는 coco_id 순서대로 뒤에 붙임
    unknown_entries.sort(key=lambda entry: entry[0])

    # 0-based sequential 할당
    remap_table = {}
    new_categories = []
    sequential_id = 0

    for _, category_name, coco_id in standard_entries:
        remap_table[coco_id] = sequential_id
        new_categories.append({"id": sequential_id, "name": category_name})
        sequential_id += 1

    for coco_id, category_name in unknown_entries:
        remap_table[coco_id] = sequential_id
        new_categories.append({"id": sequential_id, "name": category_name})
        sequential_id += 1

    return remap_table, new_categories


def build_yolo_to_coco_remap(
    yolo_categories: list[dict[str, Any]],
    custom_mapping: dict[int, int] | None = None,
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    """
    YOLO class_id → COCO category_id 매핑 테이블을 구성한다.

    **클래스 이름 기반 매핑**: YOLO categories의 name을 표준 COCO 80 클래스 테이블에서
    조회하여 대응하는 COCO category_id를 찾는다. YOLO→COCO 변환 시 YOLO class_id
    자체는 데이터셋마다 다를 수 있으므로, 이름으로 매핑하는 것이 정확하다.

    매핑 우선순위:
      1. custom_mapping이 있으면 최우선 적용
      2. 클래스 이름으로 표준 COCO 테이블에서 매칭 (NAME_TO_COCO_ID)
      3. 이름으로 매칭 실패 시 → 91번부터 순차 할당

    Args:
        yolo_categories: 입력 DatasetMeta의 categories 리스트 [{id, name, ...}]
        custom_mapping: 사용자 지정 {yolo_id: coco_id} 매핑 (선택)

    Returns:
        (remap_table, new_categories) 튜플
        - remap_table: {원본_yolo_id: 변환될_coco_id}
        - new_categories: COCO용 categories 리스트 [{id: coco_id, name: ...}]
    """
    remap_table: dict[int, int] = {}
    new_categories: list[dict[str, Any]] = []
    next_custom_coco_id = 91  # COCO 공식 max는 89

    used_coco_ids: set[int] = set()
    if custom_mapping:
        used_coco_ids.update(custom_mapping.values())

    for category in yolo_categories:
        yolo_id = category["id"]
        category_name = category.get("name", str(yolo_id))

        # 1순위: custom_mapping
        if custom_mapping and yolo_id in custom_mapping:
            coco_id = custom_mapping[yolo_id]
            remap_table[yolo_id] = coco_id
            new_categories.append({"id": coco_id, "name": category_name})
            used_coco_ids.add(coco_id)
            continue

        # 2순위: 클래스 이름으로 표준 COCO 테이블 조회
        if category_name in NAME_TO_COCO_ID:
            coco_id = NAME_TO_COCO_ID[category_name]
            remap_table[yolo_id] = coco_id
            new_categories.append({"id": coco_id, "name": category_name})
            used_coco_ids.add(coco_id)
            continue

        # 3순위: 미지의 클래스 → 91번부터 순차 할당
        while next_custom_coco_id in used_coco_ids:
            next_custom_coco_id += 1
        coco_id = next_custom_coco_id
        next_custom_coco_id += 1
        used_coco_ids.add(coco_id)

        remap_table[yolo_id] = coco_id
        new_categories.append({"id": coco_id, "name": category_name})
        logger.info(
            "표준 매핑에 없는 클래스 발견: yolo_id=%d, name='%s' → coco_id=%d 할당",
            yolo_id, category_name, coco_id,
        )

    new_categories.sort(key=lambda cat: cat["id"])
    return remap_table, new_categories
