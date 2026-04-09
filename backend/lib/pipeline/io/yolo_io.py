"""
YOLO txt 포맷 파서 및 라이터.

YOLO label 디렉토리 ↔ DatasetMeta 변환을 담당하는 순수 함수 모듈.
파일 I/O만 수행하며, DB나 서비스 레이어에 의존하지 않는다.

YOLO 포맷 규격:
  - 이미지 1장당 .txt 파일 1개 (이미지와 동일 basename)
  - 각 행: class_id center_x center_y width height (공백 구분)
  - 좌표는 이미지 크기 대비 normalized [0, 1]

통일포맷:
  - 파싱 시: class_id(정수) → class_name(문자열)로 변환
  - bbox는 COCO absolute [x, y, w, h]로 변환 (이미지 크기 있을 때)
  - 저장 시: category_name → 0-based 순차 index로 변환

클래스 이름 소스 우선순위:
  1. class_names 파라미터 (직접 전달)
  2. .yaml 파일의 names: 필드 (data.yaml 등)
  3. classes.txt 파일
  4. COCO 표준 80클래스 매핑 (yolo_id → name) + 경고
  5. 관측된 class_id로 숫자 이름 생성 + 경고
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lib.pipeline.io.coco_yolo_class_mapping import YOLO_ID_TO_NAME
from lib.pipeline.pipeline_data_models import Annotation, DatasetMeta, ImageRecord

logger = logging.getLogger(__name__)

# 지원하는 이미지 확장자 (YOLO label → 이미지 파일 매칭용)
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")

# YOLO .yaml 파일에서 탐색할 일반적인 파일명
_YAML_CANDIDATES = ("data.yaml", "dataset.yaml", "data.yml", "dataset.yml")


def parse_yolo_yaml(yaml_path: Path) -> list[str] | None:
    """
    YOLO data.yaml 파일에서 클래스 이름 목록을 추출한다.

    지원하는 yaml 구조:
      names: ['person', 'car', ...]        — 리스트 형태
      names: {0: 'person', 1: 'car', ...}  — dict 형태 (ultralytics 스타일)

    yaml 모듈 없이 간단한 파싱을 수행한다.
    복잡한 yaml 구조는 지원하지 않으며, names: 키만 추출한다.

    Args:
        yaml_path: .yaml 파일 경로

    Returns:
        클래스 이름 리스트 (id 순서대로). 파싱 실패 시 None.
    """
    try:
        # PyYAML이 있으면 사용, 없으면 간이 파서로 대체
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as file_handle:
                data = yaml.safe_load(file_handle)

            if not isinstance(data, dict) or "names" not in data:
                return None

            names_value = data["names"]

            # dict 형태: {0: 'person', 1: 'car', ...}
            if isinstance(names_value, dict):
                sorted_items = sorted(names_value.items(), key=lambda item: int(item[0]))
                return [str(name) for _, name in sorted_items]

            # list 형태: ['person', 'car', ...]
            if isinstance(names_value, list):
                return [str(name) for name in names_value]

            return None

        except ImportError:
            # PyYAML이 없으면 간이 파서로 names: 라인 추출
            return _parse_yaml_names_fallback(yaml_path)

    except Exception as parse_error:
        logger.warning("YOLO yaml 파싱 실패 (%s): %s", yaml_path, parse_error)
        return None


def _parse_yaml_names_fallback(yaml_path: Path) -> list[str] | None:
    """
    PyYAML 없이 YOLO data.yaml에서 names: 필드를 간이 파싱한다.

    지원 형태:
      names: ['person', 'car', 'bus']           — 한 줄 리스트
      names:                                     — 여러 줄 리스트
        - person
        - car

    Args:
        yaml_path: .yaml 파일 경로

    Returns:
        클래스 이름 리스트 또는 None
    """
    with open(yaml_path, "r", encoding="utf-8") as file_handle:
        lines = file_handle.readlines()

    names_line_index = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("names:"):
            names_line_index = idx
            break

    if names_line_index is None:
        return None

    names_line = lines[names_line_index].strip()
    after_colon = names_line[len("names:"):].strip()

    # 한 줄 리스트: names: ['person', 'car']
    if after_colon.startswith("["):
        content = after_colon.strip("[] ")
        if not content:
            return None
        return [
            name.strip().strip("'\"")
            for name in content.split(",")
            if name.strip()
        ]

    # 여러 줄 리스트: names:\n  - person\n  - car
    class_names: list[str] = []
    for line in lines[names_line_index + 1:]:
        stripped = line.strip()
        if stripped.startswith("- "):
            name = stripped[2:].strip().strip("'\"")
            class_names.append(name)
        elif stripped and not stripped.startswith("#"):
            # 다른 키를 만나면 종료
            break
    return class_names if class_names else None


def _find_yolo_yaml_in_directory(search_dir: Path) -> Path | None:
    """
    디렉토리에서 YOLO data.yaml 파일을 탐색한다.
    일반적인 파일명 후보를 우선 확인하고, 없으면 *.yaml/*.yml 전체 탐색.

    Args:
        search_dir: 탐색할 디렉토리

    Returns:
        발견된 yaml 파일 경로 또는 None
    """
    # 1순위: 일반적인 이름
    for candidate_name in _YAML_CANDIDATES:
        candidate_path = search_dir / candidate_name
        if candidate_path.exists():
            return candidate_path

    # 2순위: 아무 .yaml/.yml 파일
    yaml_files = list(search_dir.glob("*.yaml")) + list(search_dir.glob("*.yml"))
    if yaml_files:
        return yaml_files[0]

    return None


def _find_image_filename_for_label(
    label_basename: str,
    image_dir: Path,
) -> str | None:
    """
    라벨 파일 basename에 대응하는 이미지 파일명을 image_dir에서 탐색한다.
    여러 확장자를 순회하며 첫 번째 매칭을 반환, 없으면 None.
    """
    for extension in _IMAGE_EXTENSIONS:
        candidate_path = image_dir / f"{label_basename}{extension}"
        if candidate_path.exists():
            return candidate_path.name
    return None


def _convert_yolo_to_absolute_bbox(
    center_x_norm: float,
    center_y_norm: float,
    width_norm: float,
    height_norm: float,
    image_width: int,
    image_height: int,
) -> list[float]:
    """
    YOLO normalized center 좌표를 COCO absolute [x, y, w, h]로 변환한다.

    YOLO: (cx, cy, w, h) — 모두 이미지 크기 대비 [0, 1] 범위
    COCO: (x, y, w, h) — 좌상단 좌표 + 절대 크기 (pixel 단위)
    """
    absolute_width = width_norm * image_width
    absolute_height = height_norm * image_height
    absolute_x = (center_x_norm - width_norm / 2) * image_width
    absolute_y = (center_y_norm - height_norm / 2) * image_height
    return [absolute_x, absolute_y, absolute_width, absolute_height]


def _convert_absolute_bbox_to_yolo(
    absolute_x: float,
    absolute_y: float,
    absolute_width: float,
    absolute_height: float,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """
    COCO absolute [x, y, w, h]를 YOLO normalized center 좌표로 변환한다.

    Returns:
        (center_x, center_y, width, height) — 모두 normalized [0, 1]
    """
    center_x_norm = (absolute_x + absolute_width / 2) / image_width
    center_y_norm = (absolute_y + absolute_height / 2) / image_height
    width_norm = absolute_width / image_width
    height_norm = absolute_height / image_height
    return (center_x_norm, center_y_norm, width_norm, height_norm)


def _resolve_class_name(
    class_id: int,
    class_names: list[str] | None,
    used_fallback: set[int],
) -> str:
    """
    YOLO class_id를 클래스 이름으로 변환한다.

    우선순위:
      1. class_names 리스트에서 인덱스로 조회
      2. COCO 표준 80클래스 매핑 (YOLO_ID_TO_NAME)
      3. 숫자 문자열 폴백

    폴백 사용 시 used_fallback에 class_id를 추가하여 경고 로그용으로 추적한다.
    """
    if class_names is not None and 0 <= class_id < len(class_names):
        return class_names[class_id]

    # 표준 80클래스 매핑 시도
    if class_id in YOLO_ID_TO_NAME:
        used_fallback.add(class_id)
        return YOLO_ID_TO_NAME[class_id]

    # 최종 폴백: 숫자 이름
    used_fallback.add(class_id)
    return str(class_id)


def parse_yolo_dir(
    label_dir: Path,
    image_dir: Path | None = None,
    image_sizes: dict[str, tuple[int, int]] | None = None,
    class_names: list[str] | None = None,
    yaml_path: Path | None = None,
    dataset_id: str = "",
    storage_uri: str = "",
) -> DatasetMeta:
    """
    YOLO 라벨 디렉토리를 읽어 통일포맷 DatasetMeta로 변환한다.

    좌표 변환: YOLO normalized center → COCO absolute [x, y, w, h].
    이미지 크기 정보가 없으면 normalized [x,y,w,h] (top-left 변환)로 저장.

    Args:
        label_dir: YOLO .txt 라벨 파일이 있는 디렉토리
        image_dir: 이미지 파일 디렉토리 (파일명 매칭용, 선택)
        image_sizes: {basename_without_ext: (width, height)} 딕셔너리 (선택)
        class_names: 클래스 이름 목록 (id 순서대로). None이면 자동 탐지.
        yaml_path: YOLO data.yaml 파일 경로 (명시적 지정).
        dataset_id: DatasetMeta.dataset_id
        storage_uri: DatasetMeta.storage_uri

    Returns:
        파싱된 DatasetMeta (통일포맷, annotation_format 없음)
    """
    label_files = sorted(label_dir.glob("*.txt"))
    # classes.txt는 라벨 파일이 아니므로 제외
    label_files = [
        file_path for file_path in label_files
        if file_path.name != "classes.txt"
    ]

    # 클래스 이름 자동 탐지 (class_names 파라미터가 없을 때)
    if class_names is None:
        # 1순위: 명시적으로 지정된 yaml_path 사용
        resolved_yaml_path = yaml_path
        # 2순위: label_dir 및 상위 디렉토리에서 자동 탐색
        if resolved_yaml_path is None:
            resolved_yaml_path = _find_yolo_yaml_in_directory(label_dir)
        if resolved_yaml_path is None:
            resolved_yaml_path = _find_yolo_yaml_in_directory(label_dir.parent)
        if resolved_yaml_path is not None:
            parsed_names = parse_yolo_yaml(resolved_yaml_path)
            if parsed_names:
                class_names = parsed_names
                logger.info(
                    "YOLO yaml에서 %d개 클래스 로드: %s", len(class_names), resolved_yaml_path.name,
                )

    if class_names is None:
        # 2순위: classes.txt
        classes_txt_path = label_dir / "classes.txt"
        if classes_txt_path.exists():
            with open(classes_txt_path, "r", encoding="utf-8") as file_handle:
                class_names = [
                    line.strip() for line in file_handle if line.strip()
                ]

    # 폴백 매핑 사용 추적 (경고 로그용)
    fallback_used_class_ids: set[int] = set()

    # 관측된 category_name 수집 (categories 구성용)
    observed_category_names: list[str] = []
    observed_name_set: set[str] = set()
    image_records: list[ImageRecord] = []

    for image_index, label_path in enumerate(label_files):
        label_basename = label_path.stem  # 확장자 제외한 이름

        # 이미지 파일명 결정
        if image_dir is not None:
            matched_filename = _find_image_filename_for_label(label_basename, image_dir)
            image_filename = matched_filename or f"{label_basename}.jpg"
        else:
            image_filename = f"{label_basename}.jpg"

        # 이미지 크기 결정
        image_width: int | None = None
        image_height: int | None = None
        if image_sizes and label_basename in image_sizes:
            image_width, image_height = image_sizes[label_basename]

        # 라벨 파일 파싱
        annotations: list[Annotation] = []
        with open(label_path, "r", encoding="utf-8") as file_handle:
            for line in file_handle:
                stripped_line = line.strip()
                if not stripped_line:
                    continue

                parts = stripped_line.split()
                if len(parts) < 5:
                    logger.warning(
                        "YOLO 라벨 행 형식 오류 (5개 미만): %s in %s",
                        stripped_line, label_path.name,
                    )
                    continue

                class_id = int(parts[0])

                # class_id → category_name 변환
                category_name = _resolve_class_name(
                    class_id, class_names, fallback_used_class_ids,
                )

                # 관측된 name 수집 (등장 순서 보존)
                if category_name not in observed_name_set:
                    observed_category_names.append(category_name)
                    observed_name_set.add(category_name)

                # 좌표 변환: 이미지 크기가 있으면 absolute, 없으면 normalized [x,y,w,h] 그대로 저장
                center_x = float(parts[1])
                center_y = float(parts[2])
                box_width = float(parts[3])
                box_height = float(parts[4])

                bbox: list[float] | None = None
                if image_width is not None and image_height is not None:
                    bbox = _convert_yolo_to_absolute_bbox(
                        center_x, center_y, box_width, box_height,
                        image_width, image_height,
                    )
                else:
                    # 이미지 크기 없음 — YOLO center→COCO top-left 변환만 수행 (정규화 유지)
                    bbox = [
                        center_x - box_width / 2,
                        center_y - box_height / 2,
                        box_width,
                        box_height,
                    ]

                annotations.append(Annotation(
                    annotation_type="BBOX",
                    category_name=category_name,
                    bbox=bbox,
                ))

        image_record = ImageRecord(
            image_id=image_index + 1,
            file_name=image_filename,
            width=image_width,
            height=image_height,
            annotations=annotations,
        )
        image_records.append(image_record)

    # 폴백 매핑 사용 시 경고 로그 (data.yaml/classes.txt 없이 로드됨)
    if fallback_used_class_ids:
        logger.warning(
            "YOLO 클래스 매핑 파일 없이 로드됨: class_id %s에 대해 "
            "COCO 표준 80클래스 매핑 또는 숫자 이름을 사용했습니다. "
            "정확한 이름이 필요하면 data.yaml 또는 classes.txt를 제공하세요.",
            sorted(fallback_used_class_ids),
        )

    # categories 구성: class_names가 있으면 사용, 없으면 관측 기반
    if class_names is not None:
        categories = list(class_names)
    else:
        categories = observed_category_names

    return DatasetMeta(
        dataset_id=dataset_id,
        storage_uri=storage_uri,
        categories=categories,
        image_records=image_records,
    )


def write_yolo_dir(
    meta: DatasetMeta,
    output_dir: Path,
) -> Path:
    """
    DatasetMeta(통일포맷)를 YOLO txt 라벨 파일들로 출력한다.

    저장 시 ID 부여:
      - categories(list[str])를 정렬하여 0-based 순차 index 매핑
      - annotation.category_name → index로 변환
    좌표 변환: COCO absolute [x, y, w, h] → YOLO normalized center.

    Args:
        meta: 출력할 DatasetMeta (통일포맷)
        output_dir: 출력 디렉토리 경로 (annotations/)

    Returns:
        output_dir (동일 경로 반환)

    Raises:
        ValueError: ImageRecord에 width/height가 없어 좌표 변환이 불가능할 때
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # category_name → 0-based sequential index 매핑
    sorted_category_names = sorted(meta.categories)
    name_to_yolo_index: dict[str, int] = {
        name: index for index, name in enumerate(sorted_category_names)
    }

    for image_record in meta.image_records:
        # width/height 검증 (normalized 좌표 계산에 필수)
        if image_record.width is None or image_record.height is None:
            raise ValueError(
                f"YOLO 좌표 변환에 이미지 크기가 필요합니다: "
                f"{image_record.file_name} (width={image_record.width}, "
                f"height={image_record.height})"
            )

        # 이미지 basename으로 .txt 파일명 결정
        image_stem = Path(image_record.file_name).stem
        label_file_path = output_dir / f"{image_stem}.txt"

        lines: list[str] = []
        for annotation in image_record.annotations:
            if annotation.bbox is None:
                continue

            # category_name → 0-based index
            yolo_class_id = name_to_yolo_index.get(
                annotation.category_name, 0,
            )

            center_x, center_y, width_norm, height_norm = _convert_absolute_bbox_to_yolo(
                annotation.bbox[0], annotation.bbox[1],
                annotation.bbox[2], annotation.bbox[3],
                image_record.width, image_record.height,
            )
            lines.append(
                f"{yolo_class_id} "
                f"{center_x:.6f} {center_y:.6f} "
                f"{width_norm:.6f} {height_norm:.6f}"
            )

        with open(label_file_path, "w", encoding="utf-8") as file_handle:
            file_handle.write("\n".join(lines))
            if lines:
                file_handle.write("\n")

    return output_dir


def _write_yolo_data_yaml(
    category_names: list[str],
    output_dir: Path,
) -> Path:
    """
    YOLO data.yaml 파일을 생성한다.

    Ultralytics 스타일의 names dict 형태로 출력:
      names:
        0: person
        1: car
        ...

    Args:
        category_names: 정렬된 클래스 이름 리스트
        output_dir: yaml 파일을 생성할 디렉토리

    Returns:
        생성된 data.yaml 파일 경로
    """
    yaml_path = output_dir / "data.yaml"
    lines = [
        f"# Auto-generated YOLO data.yaml",
        f"# {len(category_names)} classes",
        f"",
        f"nc: {len(category_names)}",
        f"",
        f"names:",
    ]
    for sequential_index, class_name in enumerate(category_names):
        lines.append(f"  {sequential_index}: {class_name}")

    with open(yaml_path, "w", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(lines))
        file_handle.write("\n")

    logger.info("data.yaml 생성 완료: %d개 클래스", len(category_names))
    return yaml_path
