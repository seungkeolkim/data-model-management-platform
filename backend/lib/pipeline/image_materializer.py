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

from lib.pipeline.pipeline_data_models import DatasetPlan, ImagePlan
from lib.pipeline.storage_protocol import StorageProtocol

logger = logging.getLogger(__name__)


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

    def materialize(self, dataset_plan: DatasetPlan) -> int:
        """
        DatasetPlan의 모든 ImagePlan을 실체화한다.

        Returns:
            처리된 이미지 수
        """
        total = dataset_plan.total_images
        if total == 0:
            logger.info("실체화할 이미지가 없습니다.")
            return 0

        logger.info(
            "이미지 실체화 시작: total=%d, copy_only=%d, transform=%d",
            total, dataset_plan.copy_only_count, dataset_plan.transform_count,
        )

        processed_count = 0
        for image_plan in dataset_plan.image_plans:
            self._materialize_single_image(image_plan)
            processed_count += 1

            if self.progress_callback and processed_count % 100 == 0:
                self.progress_callback(processed_count, total)

        if self.progress_callback:
            self.progress_callback(processed_count, total)

        logger.info("이미지 실체화 완료: processed=%d", processed_count)
        return processed_count

    def _materialize_single_image(self, image_plan: ImagePlan) -> None:
        """
        단일 ImagePlan을 실체화 (복사 또는 변환).

        등록된 데이터셋의 이미지는 존재한다고 가정하며,
        존재하지 않으면 복사 시점에 FileNotFoundError를 발생시킨다.
        """
        src_path = self.storage.resolve_path(image_plan.src_uri)
        dst_path = self.storage.resolve_path(image_plan.dst_uri)

        # 출력 디렉토리 생성
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if image_plan.is_copy_only:
                shutil.copy2(src_path, dst_path)
            else:
                # 이미지 변환 — 현재는 미구현, 복사 후 변환 적용 예정
                shutil.copy2(src_path, dst_path)
                for spec in image_plan.specs:
                    self._apply_image_operation(dst_path, spec)
        except FileNotFoundError:
            logger.error(
                "소스 이미지를 찾을 수 없음: src=%s, dst=%s",
                src_path, dst_path,
            )
            raise

    def _apply_image_operation(self, image_path: Path, spec: 'ImageManipulationSpec') -> None:
        """
        단일 이미지에 변환 operation을 적용한다.
        현재는 stub — 이미지 변환 manipulator 구현 시 함께 작업 예정.
        """
        logger.warning(
            "이미지 변환 operation은 아직 미구현: %s (파일: %s)",
            spec.operation, image_path.name,
        )
