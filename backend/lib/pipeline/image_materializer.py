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
            # 이미지 변환 — 현재는 미구현, 복사 후 변환 적용 예정
            shutil.copy2(src_path, dst_path)
            for spec in image_plan.specs:
                self._apply_image_operation(dst_path, spec)

        return False

    def _apply_image_operation(self, image_path: Path, spec: 'ImageManipulationSpec') -> None:
        """
        단일 이미지에 변환 operation을 적용한다.
        현재는 stub — 이미지 변환 manipulator 구현 시 함께 작업 예정.
        """
        logger.warning(
            "이미지 변환 operation은 아직 미구현: %s (파일: %s)",
            spec.operation, image_path.name,
        )
