"""
이미지 파일 실체화기 (Image Materializer).

ImagePlan 리스트를 받아서 실제 이미지 파일을 복사/변환하여 출력 디렉토리에 생성한다.
현재는 단순 복사만 지원하며, 향후 이미지 변환(rotate, compress 등)을 추가할 수 있다.

설계 원칙:
  - annotation 처리(Phase A) 완료 후에만 호출 (Phase B: 이미지 실체화)
  - ImagePlan.is_copy_only이면 shutil.copy2
  - ImageManipulationSpec이 있으면 해당 operation 실행
  - 진행률 콜백 지원 (Celery 등에서 활용)
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from dataclasses import dataclass, field

from lib.pipeline.pipeline_data_models import DatasetPlan, ImagePlan
from lib.pipeline.storage_protocol import StorageProtocol

logger = logging.getLogger(__name__)


@dataclass
class MaterializeResult:
    """
    이미지 실체화 결과.

    materialized_count: 성공적으로 복사/변환된 이미지 수
    skipped_files: 소스 파일이 존재하지 않아 건너뛴 파일명 리스트
    """
    materialized_count: int = 0
    skipped_files: list[str] = field(default_factory=list)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_files)


class ImageMaterializer:
    """
    ImagePlan 리스트를 실체화하여 이미지 파일을 출력 경로에 생성한다.

    Args:
        storage: StorageProtocol 구현체 (경로 해석용)
        progress_callback: 진행률 콜백 (processed_count, total_count) → None
    """

    def __init__(
        self,
        storage: StorageProtocol,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        self.storage = storage
        self.progress_callback = progress_callback

    def materialize(self, dataset_plan: DatasetPlan) -> MaterializeResult:
        """
        DatasetPlan의 모든 ImagePlan을 실체화한다.

        소스 파일이 존재하지 않는 이미지는 건너뛰고 skipped_files에 기록한다.
        (annotation에는 존재하지만 실제 이미지가 없는 경우 — 파이프라인 중단 대신 경고)

        Returns:
            MaterializeResult: 실체화 결과 (성공 수 + 스킵된 파일 목록)
        """
        total = dataset_plan.total_images
        if total == 0:
            logger.info("실체화할 이미지가 없습니다.")
            return MaterializeResult()

        logger.info(
            "이미지 실체화 시작: total=%d, copy_only=%d, transform=%d",
            total, dataset_plan.copy_only_count, dataset_plan.transform_count,
        )

        materialized_count = 0
        skipped_files: list[str] = []

        for image_plan in dataset_plan.image_plans:
            was_skipped = self._materialize_single_image(image_plan)
            if was_skipped:
                # dst_uri에서 파일명 추출 (이미 rename된 최종 파일명)
                skipped_file_name = image_plan.dst_uri.rsplit("/", 1)[-1]
                skipped_files.append(skipped_file_name)
            else:
                materialized_count += 1

            processed_so_far = materialized_count + len(skipped_files)
            if self.progress_callback and processed_so_far % 100 == 0:
                self.progress_callback(processed_so_far, total)

        if self.progress_callback:
            self.progress_callback(materialized_count + len(skipped_files), total)

        if skipped_files:
            logger.warning(
                "이미지 실체화 완료 (일부 스킵): materialized=%d, skipped=%d",
                materialized_count, len(skipped_files),
            )
            # 스킵된 파일 목록 상세 로깅 (최대 20개까지만 표시)
            display_files = skipped_files[:20]
            logger.warning(
                "스킵된 파일 목록%s: %s",
                f" (상위 20/{len(skipped_files)}개)" if len(skipped_files) > 20 else "",
                ", ".join(display_files),
            )
        else:
            logger.info("이미지 실체화 완료: materialized=%d", materialized_count)

        return MaterializeResult(
            materialized_count=materialized_count,
            skipped_files=skipped_files,
        )

    def _materialize_single_image(self, image_plan: ImagePlan) -> bool:
        """
        단일 ImagePlan을 실체화 (복사 또는 변환).

        소스 파일이 존재하지 않으면 건너뛰고 True를 반환한다.

        Returns:
            True이면 스킵됨 (소스 파일 없음), False이면 정상 처리됨
        """
        src_path = self.storage.resolve_path(image_plan.src_uri)
        dst_path = self.storage.resolve_path(image_plan.dst_uri)

        # 소스 파일 존재 여부 확인 — 없으면 스킵
        if not src_path.exists():
            logger.warning(
                "소스 이미지를 찾을 수 없어 건너뜀: src=%s", src_path,
            )
            return True

        # 출력 디렉토리 생성
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if image_plan.is_copy_only:
            shutil.copy2(src_path, dst_path)
        else:
            # 변환이 있는 이미지: 소스를 PIL로 열어 변환 체인을 적용한 뒤 한 번만 저장
            # 복사 + 재저장 대비 I/O 1회 절약
            self._transform_and_save(src_path, dst_path, image_plan.specs)

        return False

    def _transform_and_save(
        self,
        src_path: Path,
        dst_path: Path,
        specs: list,
    ) -> None:
        """
        소스 이미지를 열어 모든 변환 spec을 순차 적용한 뒤 한 번에 저장한다.

        복사 없이 바로 변환 → 저장하므로 I/O 비용을 절약한다.
        원본 포맷(JPEG/PNG 등)과 EXIF 메타데이터를 유지한다.
        """
        from PIL import Image

        with Image.open(src_path) as img:
            # EXIF 정보 보존 (있으면)
            exif_data = img.info.get("exif")

            for spec in specs:
                img = self._apply_image_operation(img, spec)

            # 원본 포맷으로 저장 — JPEG이면 quality 유지, PNG이면 그대로
            save_kwargs: dict = {}
            output_format = src_path.suffix.lower()
            if output_format in (".jpg", ".jpeg"):
                save_kwargs["quality"] = 95
                save_kwargs["subsampling"] = 0  # 4:4:4 — 색상 손실 최소화
            if exif_data:
                save_kwargs["exif"] = exif_data

            img.save(dst_path, **save_kwargs)

    def _apply_image_operation(self, img: 'Image.Image', spec: 'ImageManipulationSpec') -> 'Image.Image':
        """
        PIL Image에 단일 변환 operation을 적용하여 반환한다.

        지원 operation:
          - rotate_image: 이미지를 지정 각도(90/180/270)로 시계 방향 회전
          - crop_image_vertical: 상단 또는 하단에서 height 의 지정 비율(%)을 잘라냄
          - mask_region: 지정 bbox 영역을 단색으로 채우기
        """
        if spec.operation == "rotate_image":
            return self._apply_rotate(img, spec.params)
        if spec.operation == "crop_image_vertical":
            return self._apply_crop_vertical(img, spec.params)
        if spec.operation == "mask_region":
            return self._apply_mask_region(img, spec.params)

        logger.warning(
            "미지원 이미지 변환 operation: %s (건너뜀)", spec.operation,
        )
        return img

    def _apply_rotate(self, img: 'Image.Image', params: dict) -> 'Image.Image':
        """PIL Image를 회전하여 반환한다."""
        from PIL import Image

        degrees = int(params.get("degrees", 180))

        # PIL transpose는 무손실 픽셀 재배치 (보간 없음)
        if degrees == 90:
            return img.transpose(Image.Transpose.ROTATE_270)   # 시계 90° = PIL 반시계 270°
        elif degrees == 180:
            return img.transpose(Image.Transpose.ROTATE_180)
        elif degrees == 270:
            return img.transpose(Image.Transpose.ROTATE_90)    # 시계 270° = PIL 반시계 90°

        logger.warning("지원하지 않는 회전 각도: %d (건너뜀)", degrees)
        return img

    def _apply_crop_vertical(self, img: 'Image.Image', params: dict) -> 'Image.Image':
        """
        이미지 상단 또는 하단에서 height 의 지정 비율(%)을 잘라낸다.

        params:
            direction: "up" | "down" — "up" 이면 상단 영역, "down" 이면 하단 영역을 제거.
            crop_pct:  int (1~99)    — 전체 height 중 잘라낼 비율.
        """
        direction = str(params.get("direction", "up"))
        crop_pct = int(params.get("crop_pct", 30))

        if direction not in ("up", "down"):
            logger.warning(
                "미지원 crop direction: %s (건너뜀)", direction,
            )
            return img
        if crop_pct < 1 or crop_pct > 99:
            logger.warning(
                "crop_pct 범위 밖: %d (건너뜀)", crop_pct,
            )
            return img

        image_width, image_height = img.size
        cut_rows = int(image_height * crop_pct / 100)
        # 최소 1 픽셀은 남겨둔다 — crop_pct=99 + 작은 이미지에서도 0-height 방지.
        cut_rows = max(0, min(cut_rows, image_height - 1))

        if direction == "up":
            # 상단 영역을 제거 → upper 를 cut_rows 지점부터 시작.
            return img.crop((0, cut_rows, image_width, image_height))
        # direction == "down" — 하단 영역을 제거 → lower 를 height - cut_rows 로.
        return img.crop((0, 0, image_width, image_height - cut_rows))

    def _apply_mask_region(self, img: 'Image.Image', params: dict) -> 'Image.Image':
        """
        지정된 bbox 영역들을 단색으로 채워 마스킹한다.

        params:
            bboxes: list[list[float]] — COCO [x, y, w, h] 형식 bbox 목록
            fill_color: str — "black" | "white"
            bbox_normalized: bool — True이면 0~1 정규화 좌표 (이미지 크기로 변환)
        """
        from PIL import ImageDraw

        bboxes = params.get("bboxes", [])
        fill_color_name = params.get("fill_color", "black")
        bbox_normalized = params.get("bbox_normalized", False)

        # RGB 이미지로 변환 — 그레이스케일(L), 팔레트(P) 등에서 tuple fill이 동작하도록
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        fill_rgb = (0, 0, 0) if fill_color_name == "black" else (255, 255, 255)
        draw = ImageDraw.Draw(img)
        image_width, image_height = img.size

        for bbox in bboxes:
            bx, by, bw, bh = bbox
            if bbox_normalized:
                bx *= image_width
                by *= image_height
                bw *= image_width
                bh *= image_height

            # PIL rectangle은 (left, top, right, bottom)
            draw.rectangle(
                [int(bx), int(by), int(bx + bw), int(by + bh)],
                fill=fill_rgb,
            )

        return img
