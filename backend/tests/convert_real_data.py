"""
실제 YOLO 데이터(coco8, coco128)를 COCO로 변환하여 저장.

출력 1: tococo/           — YOLO → COCO (1회 변환)
출력 2: tococo_toyolo_tococo/ — YOLO → COCO → YOLO → COCO (왕복 변환)

각 데이터셋/split 구조를 유지하며, annotations.json + images/ 를 함께 저장한다.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.manipulators.format_convert import FormatConvertToCoco, FormatConvertToYolo
from app.pipeline.io.coco_io import parse_coco_json, write_coco_json
from app.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from app.pipeline.io.class_mapping import YOLO_ID_TO_NAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USER_TEST_DIR = PROJECT_ROOT / "user_test"
TOCOCO_DIR = USER_TEST_DIR / "tococo"
ROUNDTRIP_DIR = USER_TEST_DIR / "tococo_toyolo_tococo"

STANDARD_CLASS_NAMES = [YOLO_ID_TO_NAME[yolo_id] for yolo_id in range(80)]


def collect_image_sizes(image_dir: Path) -> dict[str, tuple[int, int]]:
    """이미지 디렉토리에서 {stem: (width, height)} 사전을 반환한다."""
    image_sizes: dict[str, tuple[int, int]] = {}
    for image_path in sorted(image_dir.iterdir()):
        if image_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}:
            with Image.open(image_path) as img:
                image_sizes[image_path.stem] = img.size
    return image_sizes


def copy_images(src_image_dir: Path, dst_dir: Path) -> None:
    """이미지 디렉토리를 dst_dir/images/ 로 복사한다."""
    dst_images = dst_dir / "images"
    if dst_images.exists():
        shutil.rmtree(dst_images)
    shutil.copytree(src_image_dir, dst_images)


def convert_split(
    dataset_name: str,
    split_name: str,
    label_dir: Path,
    image_dir: Path,
) -> None:
    """단일 split에 대해 두 종류의 COCO 변환을 수행한다."""
    print(f"\n  {dataset_name}/{split_name}")

    image_sizes = collect_image_sizes(image_dir)

    # YOLO 파싱
    yolo_meta = parse_yolo_dir(
        label_dir,
        image_sizes=image_sizes,
        class_names=STANDARD_CLASS_NAMES,
        dataset_id=f"{dataset_name}-{split_name}",
    )

    # 이미지 크기 없는 레코드 제거
    valid_records = [
        rec for rec in yolo_meta.image_records
        if rec.width is not None and rec.height is not None
    ]
    skipped = len(yolo_meta.image_records) - len(valid_records)
    if skipped > 0:
        yolo_meta.image_records = valid_records
        print(f"    이미지 없는 라벨 {skipped}개 제외")

    to_coco = FormatConvertToCoco()
    to_yolo = FormatConvertToYolo()

    # ── 출력 1: YOLO → COCO ──
    coco_meta_1 = to_coco.transform_annotation(yolo_meta, params={})
    out1 = TOCOCO_DIR / dataset_name / split_name
    out1.mkdir(parents=True, exist_ok=True)
    write_coco_json(coco_meta_1, out1 / "annotations.json")
    copy_images(image_dir, out1)
    ann_count_1 = sum(len(rec.annotations) for rec in coco_meta_1.image_records)
    print(f"    tococo: {coco_meta_1.image_count}장, {ann_count_1}개 annotation")

    # ── 출력 2: YOLO → COCO → YOLO → COCO ──
    yolo_meta_2 = to_yolo.transform_annotation(coco_meta_1, params={})

    # 중간 YOLO 파일을 임시 디렉토리에 쓰고 재파싱
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_yolo_dir:
        tmp_yolo_path = Path(tmp_yolo_dir)
        write_yolo_dir(yolo_meta_2, tmp_yolo_path)
        yolo_meta_reparsed = parse_yolo_dir(
            tmp_yolo_path, image_sizes=image_sizes,
            dataset_id=f"{dataset_name}-{split_name}-roundtrip",
        )

    coco_meta_3 = to_coco.transform_annotation(yolo_meta_reparsed, params={})
    out3 = ROUNDTRIP_DIR / dataset_name / split_name
    out3.mkdir(parents=True, exist_ok=True)
    write_coco_json(coco_meta_3, out3 / "annotations.json")
    copy_images(image_dir, out3)
    ann_count_3 = sum(len(rec.annotations) for rec in coco_meta_3.image_records)
    print(f"    tococo_toyolo_tococo: {coco_meta_3.image_count}장, {ann_count_3}개 annotation")


def main():
    datasets = {
        "coco8": {
            "train": {
                "labels": USER_TEST_DIR / "coco8" / "labels" / "train",
                "images": USER_TEST_DIR / "coco8" / "images" / "train",
            },
            "val": {
                "labels": USER_TEST_DIR / "coco8" / "labels" / "val",
                "images": USER_TEST_DIR / "coco8" / "images" / "val",
            },
        },
        "coco128": {
            "train2017": {
                "labels": USER_TEST_DIR / "coco128" / "labels" / "train2017",
                "images": USER_TEST_DIR / "coco128" / "images" / "train2017",
            },
        },
    }

    print("=== YOLO → COCO 변환 시작 ===")
    for dataset_name, splits in datasets.items():
        for split_name, paths in splits.items():
            convert_split(dataset_name, split_name, paths["labels"], paths["images"])

    print(f"\n=== 완료 ===")
    print(f"  1회 변환: {TOCOCO_DIR}")
    print(f"  왕복 변환: {ROUNDTRIP_DIR}")


if __name__ == "__main__":
    main()
