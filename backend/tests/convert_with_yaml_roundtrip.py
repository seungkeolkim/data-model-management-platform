"""
YOLO → COCO 1회 변환 및 YOLO → COCO → YOLO → COCO roundtrip 변환 스크립트.

매 변환 단계마다 yaml/json을 생성하고, 다음 단계에서 해당 파일을 활용한다.

출력 구조 (user_test 하위):
  tococo/           — YOLO → COCO 1회 변환 결과
    coco8/train/instances.json
    coco8/val/instances.json
    coco128/train2017/instances.json

  tococo_roundtrip/  — YOLO → COCO → YOLO → COCO roundtrip 결과
    coco8/train/
      step1_coco/instances.json        (YOLO → COCO)
      step2_yolo/                      (COCO → YOLO, data.yaml 포함)
      step3_coco/instances.json        (YOLO → COCO, step2 yaml 활용)
    ...
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.io.coco_io import parse_coco_json, write_coco_json
from app.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from app.manipulators.format_convert import FormatConvertToCoco, FormatConvertToYolo


def get_image_sizes(image_dir: Path) -> dict[str, tuple[int, int]]:
    """이미지 디렉토리에서 각 이미지의 (width, height)를 읽어 반환한다."""
    from PIL import Image

    sizes: dict[str, tuple[int, int]] = {}
    for img_path in sorted(image_dir.iterdir()):
        if img_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"):
            with Image.open(img_path) as img:
                sizes[img_path.stem] = (img.width, img.height)
    return sizes


def convert_single_split(
    dataset_name: str,
    split_name: str,
    label_dir: Path,
    image_dir: Path,
    yaml_path: Path,
    tococo_out: Path,
    roundtrip_out: Path,
) -> None:
    """단일 split에 대해 1회 변환 및 roundtrip 변환을 수행한다."""
    print(f"\n{'='*60}")
    print(f"[{dataset_name}/{split_name}]")
    print(f"  labels: {label_dir}")
    print(f"  images: {image_dir}")
    print(f"  yaml:   {yaml_path}")
    print(f"{'='*60}")

    # 이미지 크기 읽기 (YOLO normalized ↔ absolute 변환에 필요)
    image_sizes = get_image_sizes(image_dir)
    print(f"  이미지 수: {len(image_sizes)}")

    converter_to_coco = FormatConvertToCoco()
    converter_to_yolo = FormatConvertToYolo()

    # ── Step A: YOLO → COCO (1회 변환) ──
    print(f"\n  [1회 변환] YOLO → COCO")
    yolo_meta = parse_yolo_dir(
        label_dir=label_dir,
        image_dir=image_dir,
        image_sizes=image_sizes,
        yaml_path=yaml_path,
    )
    # 이미지 크기가 없는 레코드 제거 (이미지 없이 라벨만 있는 경우)
    orphan_count = sum(1 for r in yolo_meta.image_records if r.width is None)
    if orphan_count > 0:
        yolo_meta.image_records = [r for r in yolo_meta.image_records if r.width is not None]
        print(f"    ⚠ 이미지 없는 라벨 {orphan_count}개 제외")
    print(f"    파싱 완료: {len(yolo_meta.image_records)}장, {len(yolo_meta.categories)} categories")

    coco_meta = converter_to_coco.transform_annotation(yolo_meta, {})

    tococo_split_dir = tococo_out / dataset_name / split_name
    tococo_split_dir.mkdir(parents=True, exist_ok=True)
    coco_json_path = tococo_split_dir / "instances.json"
    write_coco_json(coco_meta, coco_json_path)
    print(f"    출력: {coco_json_path}")

    # ── Step B: Roundtrip (YOLO → COCO → YOLO → COCO) ──
    roundtrip_split_dir = roundtrip_out / dataset_name / split_name

    # Step 1: YOLO → COCO
    print(f"\n  [Roundtrip Step 1] YOLO → COCO")
    step1_dir = roundtrip_split_dir / "step1_coco"
    step1_dir.mkdir(parents=True, exist_ok=True)
    step1_json = step1_dir / "instances.json"
    write_coco_json(coco_meta, step1_json)
    print(f"    출력: {step1_json}")
    print(f"    categories: {len(coco_meta.categories)}")

    # Step 2: COCO → YOLO (data.yaml 생성)
    print(f"\n  [Roundtrip Step 2] COCO → YOLO")
    step1_coco_meta = parse_coco_json(step1_json)
    step2_yolo_meta = converter_to_yolo.transform_annotation(step1_coco_meta, {})
    step2_dir = roundtrip_split_dir / "step2_yolo"
    write_yolo_dir(step2_yolo_meta, step2_dir)
    step2_yaml = step2_dir / "data.yaml"
    print(f"    출력: {step2_dir}")
    print(f"    data.yaml 생성: {step2_yaml.exists()}")
    print(f"    categories: {len(step2_yolo_meta.categories)}")
    label_count = len(list(step2_dir.glob("*.txt")))
    print(f"    label 파일 수: {label_count}")

    # Step 3: YOLO → COCO (step2에서 생성된 data.yaml 활용)
    print(f"\n  [Roundtrip Step 3] YOLO → COCO (step2 yaml 활용)")
    step2_yolo_meta_reparsed = parse_yolo_dir(
        label_dir=step2_dir,
        image_dir=image_dir,
        image_sizes=image_sizes,
        yaml_path=step2_yaml,
    )
    step3_coco_meta = converter_to_coco.transform_annotation(step2_yolo_meta_reparsed, {})
    step3_dir = roundtrip_split_dir / "step3_coco"
    step3_dir.mkdir(parents=True, exist_ok=True)
    step3_json = step3_dir / "instances.json"
    write_coco_json(step3_coco_meta, step3_json)
    print(f"    출력: {step3_json}")
    print(f"    categories: {len(step3_coco_meta.categories)}")

    # ── 비교 요약 ──
    print(f"\n  [비교 요약]")
    # 원본 annotation 개수
    original_ann_count = sum(len(r.annotations) for r in yolo_meta.image_records)
    step3_ann_count = sum(len(r.annotations) for r in step3_coco_meta.image_records)
    print(f"    원본 annotation 수: {original_ann_count}")
    print(f"    Step3 annotation 수: {step3_ann_count}")
    print(f"    일치: {original_ann_count == step3_ann_count}")

    # category name 비교 (원본 yaml vs step3)
    original_names = {c["name"] for c in yolo_meta.categories}
    step3_names = {c["name"] for c in step3_coco_meta.categories}
    name_match = original_names == step3_names
    print(f"    category name 전체 일치: {name_match}")
    if not name_match:
        print(f"      원본에만 있는: {original_names - step3_names}")
        print(f"      step3에만 있는: {step3_names - original_names}")


def main() -> None:
    user_test = Path(__file__).resolve().parent.parent.parent / "user_test"
    tococo_out = user_test / "tococo"
    roundtrip_out = user_test / "tococo_roundtrip"

    # 기존 출력 디렉토리 정리
    import shutil
    for out_dir in (tococo_out, roundtrip_out):
        if out_dir.exists():
            shutil.rmtree(out_dir)

    # 변환 대상 정의: (dataset_name, split_name, label_dir, image_dir, yaml_path)
    datasets = []

    # coco8: train, val
    coco8_base = user_test / "coco8"
    coco8_yaml = coco8_base / "coco8.yaml"
    for split in ("train", "val"):
        datasets.append((
            "coco8", split,
            coco8_base / "labels" / split,
            coco8_base / "images" / split,
            coco8_yaml,
        ))

    # coco128: train2017
    coco128_base = user_test / "coco128"
    coco128_yaml = coco128_base / "coco128.yaml"
    for split in ("train2017",):
        datasets.append((
            "coco128", split,
            coco128_base / "labels" / split,
            coco128_base / "images" / split,
            coco128_yaml,
        ))

    for dataset_name, split_name, label_dir, image_dir, yaml_path in datasets:
        if not label_dir.exists():
            print(f"\n[SKIP] {dataset_name}/{split_name} — label_dir 없음: {label_dir}")
            continue
        convert_single_split(
            dataset_name, split_name,
            label_dir, image_dir, yaml_path,
            tococo_out, roundtrip_out,
        )

    print(f"\n{'='*60}")
    print(f"완료!")
    print(f"  1회 변환 결과: {tococo_out}")
    print(f"  Roundtrip 결과: {roundtrip_out}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
