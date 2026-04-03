"""
실제 YOLO 데이터(coco8, coco128)를 이용한 YOLO → COCO → YOLO → COCO 왕복 변환 테스트.

각 데이터셋의 모든 split에 대해:
  1단계: YOLO 파싱 → COCO 변환 → COCO JSON 쓰기
  2단계: COCO JSON 파싱 → YOLO 변환 → YOLO 파일 쓰기
  3단계: YOLO 파싱 → COCO 변환 → COCO JSON 쓰기

결과물은 /tmp/roundtrip_output/ 에 저장한 뒤 zip으로 압축.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from PIL import Image

# backend 패키지 import를 위해 경로 추가
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.manipulators.format_convert import FormatConvertToCoco, FormatConvertToYolo
from app.pipeline.io.coco_io import parse_coco_json, write_coco_json
from app.pipeline.io.yolo_io import parse_yolo_dir, write_yolo_dir
from app.pipeline.io.class_mapping import YOLO_ID_TO_NAME

# =============================================================================
# 유틸리티
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # data-model-management-platform/
USER_TEST_DIR = PROJECT_ROOT / "user_test"
OUTPUT_BASE = Path("/tmp/roundtrip_output")

# COCO 80 클래스 이름 목록 (YOLO 순서 0~79)
STANDARD_CLASS_NAMES = [YOLO_ID_TO_NAME[yolo_id] for yolo_id in range(80)]


def collect_image_sizes(image_dir: Path) -> dict[str, tuple[int, int]]:
    """이미지 디렉토리를 읽어 {stem: (width, height)} 사전을 반환한다."""
    image_sizes: dict[str, tuple[int, int]] = {}
    for image_path in sorted(image_dir.iterdir()):
        if image_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}:
            with Image.open(image_path) as img:
                image_sizes[image_path.stem] = img.size  # (width, height)
    return image_sizes


def validate_coco_json(coco_path: Path, step_label: str) -> dict:
    """COCO JSON 파일의 기본 구조를 검증하고 요약 통계를 반환한다."""
    with open(coco_path, "r", encoding="utf-8") as file_handle:
        coco_data = json.load(file_handle)

    assert "images" in coco_data, f"[{step_label}] 'images' 키 누락"
    assert "annotations" in coco_data, f"[{step_label}] 'annotations' 키 누락"
    assert "categories" in coco_data, f"[{step_label}] 'categories' 키 누락"

    # bbox가 absolute 좌표인지 확인 (bbox 없는 annotation은 건너뜀)
    bbox_count = 0
    for annotation in coco_data["annotations"]:
        if "bbox" not in annotation:
            continue
        bbox = annotation["bbox"]
        assert len(bbox) == 4, f"[{step_label}] bbox 길이 오류: {bbox}"
        assert any(coord > 1.0 for coord in bbox), (
            f"[{step_label}] normalized 좌표 의심: {bbox}"
        )
        assert annotation.get("area", 0) > 0, f"[{step_label}] area 누락/0"
        bbox_count += 1

    return {
        "images": len(coco_data["images"]),
        "annotations": len(coco_data["annotations"]),
        "categories": len(coco_data["categories"]),
    }


def validate_yolo_dir(yolo_dir: Path, step_label: str) -> dict:
    """YOLO 출력 디렉토리의 기본 구조를 검증하고 요약 통계를 반환한다."""
    txt_files = [
        file_path for file_path in yolo_dir.glob("*.txt")
        if file_path.name != "classes.txt"
    ]
    assert len(txt_files) > 0, f"[{step_label}] YOLO label 파일 없음"

    classes_txt = yolo_dir / "classes.txt"
    assert classes_txt.exists(), f"[{step_label}] classes.txt 없음"

    total_annotations = 0
    for txt_file in txt_files:
        content = txt_file.read_text().strip()
        if not content:
            continue
        for line in content.split("\n"):
            parts = line.split()
            assert len(parts) == 5, f"[{step_label}] 필드 수 오류: {line} in {txt_file.name}"
            int(parts[0])  # class_id는 정수
            for coord_str in parts[1:]:
                coord_value = float(coord_str)
                assert 0.0 <= coord_value <= 1.0, (
                    f"[{step_label}] 좌표 범위 초과: {coord_value} in {txt_file.name}"
                )
            total_annotations += 1

    class_names = classes_txt.read_text().strip().split("\n")
    return {
        "label_files": len(txt_files),
        "annotations": total_annotations,
        "classes": len(class_names),
    }


# =============================================================================
# 메인 변환 로직
# =============================================================================

def run_roundtrip_for_split(
    dataset_name: str,
    split_name: str,
    label_dir: Path,
    image_dir: Path,
    output_dir: Path,
) -> None:
    """단일 split에 대해 YOLO → COCO → YOLO → COCO 3단계 왕복 변환을 수행한다."""
    print(f"\n{'='*60}")
    print(f"  {dataset_name} / {split_name}")
    print(f"{'='*60}")

    # 이미지 크기 수집
    image_sizes = collect_image_sizes(image_dir)

    # 라벨 파일 중 이미지가 없는 것 확인
    label_stems = {
        file_path.stem
        for file_path in label_dir.glob("*.txt")
        if file_path.name != "classes.txt"
    }
    unmatched_labels = label_stems - set(image_sizes.keys())
    if unmatched_labels:
        print(f"  ⚠ 이미지 없는 라벨 {len(unmatched_labels)}개 (bbox=None 예상): "
              f"{sorted(unmatched_labels)[:5]}{'...' if len(unmatched_labels) > 5 else ''}")
    print(f"  이미지 수: {len(image_sizes)}, 라벨 수: {len(label_stems)}")

    # ── 1단계: YOLO → COCO ──
    print("\n  [1단계] YOLO 원본 파싱 → COCO 변환")
    yolo_meta_original = parse_yolo_dir(
        label_dir,
        image_sizes=image_sizes,
        class_names=STANDARD_CLASS_NAMES,
        dataset_id=f"{dataset_name}-{split_name}-original",
    )
    # 이미지 크기 없는 레코드 제거 (라벨만 있고 이미지가 없는 경우)
    valid_records = [
        rec for rec in yolo_meta_original.image_records
        if rec.width is not None and rec.height is not None
    ]
    skipped_count = yolo_meta_original.image_count - len(valid_records)
    if skipped_count > 0:
        yolo_meta_original.image_records = valid_records
        print(f"    ⚠ 이미지 크기 없는 레코드 {skipped_count}개 제외")

    print(f"    파싱 완료: {yolo_meta_original.image_count}장, "
          f"annotation {sum(len(rec.annotations) for rec in yolo_meta_original.image_records)}개")

    to_coco = FormatConvertToCoco()
    coco_meta_step1 = to_coco.transform_annotation(yolo_meta_original, params={})

    step1_coco_path = output_dir / "step1_yolo_to_coco" / "annotations.json"
    write_coco_json(coco_meta_step1, step1_coco_path)
    step1_stats = validate_coco_json(step1_coco_path, "1단계 COCO")
    print(f"    COCO 출력: {step1_stats}")

    # ── 2단계: COCO → YOLO ──
    print("\n  [2단계] COCO 파싱 → YOLO 변환")
    coco_meta_reparsed = parse_coco_json(step1_coco_path)

    to_yolo = FormatConvertToYolo()
    yolo_meta_step2 = to_yolo.transform_annotation(coco_meta_reparsed, params={})

    step2_yolo_dir = output_dir / "step2_coco_to_yolo"
    write_yolo_dir(yolo_meta_step2, step2_yolo_dir)
    step2_stats = validate_yolo_dir(step2_yolo_dir, "2단계 YOLO")
    print(f"    YOLO 출력: {step2_stats}")

    # ── 3단계: YOLO → COCO ──
    print("\n  [3단계] YOLO 재파싱 → COCO 최종 변환")
    yolo_meta_reparsed = parse_yolo_dir(
        step2_yolo_dir,
        image_sizes=image_sizes,
        dataset_id=f"{dataset_name}-{split_name}-final",
    )

    coco_meta_step3 = to_coco.transform_annotation(yolo_meta_reparsed, params={})

    step3_coco_path = output_dir / "step3_yolo_to_coco" / "annotations.json"
    write_coco_json(coco_meta_step3, step3_coco_path)
    step3_stats = validate_coco_json(step3_coco_path, "3단계 COCO")
    print(f"    COCO 출력: {step3_stats}")

    # ── 정합성 비교 ──
    print("\n  [검증] 1단계 vs 3단계 비교")
    assert step1_stats["images"] == step3_stats["images"], "이미지 수 불일치"
    assert step1_stats["annotations"] == step3_stats["annotations"], "annotation 수 불일치"
    assert step1_stats["categories"] == step3_stats["categories"], "category 수 불일치"

    # 1단계와 3단계의 category_id 집합 비교
    with open(step1_coco_path) as fh:
        step1_data = json.load(fh)
    with open(step3_coco_path) as fh:
        step3_data = json.load(fh)

    step1_cat_ids = sorted({ann["category_id"] for ann in step1_data["annotations"]})
    step3_cat_ids = sorted({ann["category_id"] for ann in step3_data["annotations"]})
    assert step1_cat_ids == step3_cat_ids, (
        f"category_id 불일치: 1단계={step1_cat_ids}, 3단계={step3_cat_ids}"
    )

    # bbox 좌표 비교 (파일명 기반 매칭, float 오차 허용)
    coord_tolerance = 1.0  # 1 pixel 이내 오차 허용

    # image_id → file_name 매핑
    def build_filename_ann_map(coco_data):
        """파일명별 annotation을 (category_id, bbox) 리스트로 정리한다."""
        id_to_fname = {img["id"]: img["file_name"] for img in coco_data["images"]}
        fname_to_anns = {}
        for ann in coco_data["annotations"]:
            if "bbox" not in ann:
                continue
            fname = id_to_fname[ann["image_id"]]
            fname_to_anns.setdefault(fname, []).append(
                (ann["category_id"], tuple(ann["bbox"]))
            )
        # 각 이미지 내 annotation을 정렬
        # 정렬 키를 정수 pixel로 반올림하여 미세한 float 차이로 인한 순서 뒤바뀜 방지
        for fname in fname_to_anns:
            fname_to_anns[fname].sort(
                key=lambda item: (item[0], tuple(round(coord) for coord in item[1]))
            )
        return fname_to_anns

    step1_map = build_filename_ann_map(step1_data)
    step3_map = build_filename_ann_map(step3_data)

    max_coord_diff = 0.0
    for fname in sorted(step1_map.keys()):
        anns1 = step1_map[fname]
        anns3 = step3_map.get(fname, [])
        assert len(anns1) == len(anns3), (
            f"{fname}: annotation 수 불일치 ({len(anns1)} vs {len(anns3)})"
        )
        for (cat1, bbox1), (cat3, bbox3) in zip(anns1, anns3):
            assert cat1 == cat3, f"{fname}: category_id 불일치 {cat1} vs {cat3}"
            for coord_idx in range(4):
                diff = abs(bbox1[coord_idx] - bbox3[coord_idx])
                max_coord_diff = max(max_coord_diff, diff)
                assert diff < coord_tolerance, (
                    f"{fname}: bbox 오차 초과: {diff:.6f} (허용: {coord_tolerance})"
                )

    print(f"    ✓ 이미지 수 일치: {step1_stats['images']}")
    print(f"    ✓ annotation 수 일치: {step1_stats['annotations']}")
    print(f"    ✓ category_id 집합 일치: {step1_cat_ids}")
    print(f"    ✓ bbox 최대 오차: {max_coord_diff:.6f} pixel")
    print(f"    ✓ 왕복 변환 정합성 통과!")

    # 이미지 심볼릭 링크 생성 (viewer에서 확인할 수 있도록)
    for step_dir_name in ["step1_yolo_to_coco", "step3_yolo_to_coco"]:
        images_link = output_dir / step_dir_name / "images"
        if not images_link.exists():
            images_link.symlink_to(image_dir.resolve())

    # step2 (YOLO) 에도 이미지 링크
    step2_images_link = step2_yolo_dir / "images"
    if not step2_images_link.exists():
        step2_images_link.symlink_to(image_dir.resolve())


def main():
    """모든 데이터셋, 모든 split에 대해 왕복 변환을 실행한다."""
    # 출력 디렉토리 초기화
    if OUTPUT_BASE.exists():
        shutil.rmtree(OUTPUT_BASE)
    OUTPUT_BASE.mkdir(parents=True)

    # 데이터셋 탐색
    datasets = {
        "coco8": {
            "splits": {
                "train": {
                    "labels": USER_TEST_DIR / "coco8" / "labels" / "train",
                    "images": USER_TEST_DIR / "coco8" / "images" / "train",
                },
                "val": {
                    "labels": USER_TEST_DIR / "coco8" / "labels" / "val",
                    "images": USER_TEST_DIR / "coco8" / "images" / "val",
                },
            },
        },
        "coco128": {
            "splits": {
                "train2017": {
                    "labels": USER_TEST_DIR / "coco128" / "labels" / "train2017",
                    "images": USER_TEST_DIR / "coco128" / "images" / "train2017",
                },
            },
        },
    }

    total_splits = 0
    for dataset_name, dataset_config in datasets.items():
        for split_name, split_paths in dataset_config["splits"].items():
            output_dir = OUTPUT_BASE / dataset_name / split_name
            output_dir.mkdir(parents=True, exist_ok=True)

            run_roundtrip_for_split(
                dataset_name=dataset_name,
                split_name=split_name,
                label_dir=split_paths["labels"],
                image_dir=split_paths["images"],
                output_dir=output_dir,
            )
            total_splits += 1

    # 결과 압축 (심볼릭 링크는 따라가지 않고 원본 이미지 복사)
    print(f"\n{'='*60}")
    print(f"  전체 {total_splits}개 split 변환 완료")
    print(f"{'='*60}")

    # 이미지를 실제 파일로 복사 (심볼릭 링크 대신)
    print("\n  이미지 파일 복사 중...")
    for symlink_path in OUTPUT_BASE.rglob("images"):
        if symlink_path.is_symlink():
            real_target = symlink_path.resolve()
            symlink_path.unlink()
            shutil.copytree(real_target, symlink_path)

    zip_path = Path("/tmp/roundtrip_output.zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(
        str(zip_path).replace(".zip", ""),
        "zip",
        root_dir=OUTPUT_BASE.parent,
        base_dir=OUTPUT_BASE.name,
    )
    print(f"\n  압축 완료: {zip_path}")
    print(f"  압축 크기: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
