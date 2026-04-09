"""
Manipulator 레지스트리.

name → UnitManipulator 클래스 매핑.
PipelineDagExecutor가 config의 operator로 클래스를 조회할 때 사용한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lib.manipulators.filter_keep_images_containing_class_name import FilterKeepImagesContainingClassName
from lib.manipulators.filter_remain_selected_class_names_only_in_annotation import FilterRemainSelectedClassNamesOnlyInAnnotation
from lib.manipulators.filter_remove_images_containing_class_name import FilterRemoveImagesContainingClassName
from lib.manipulators.format_convert import (
    FormatConvertToCoco,
    FormatConvertToYolo,
    FormatConvertVisDroneToCoco,
    FormatConvertVisDroneToYolo,
)
from lib.manipulators.mask_region_by_class import MaskRegionByClass
from lib.manipulators.merge_datasets import MergeDatasets
from lib.manipulators.remap_class_name import RemapClassName
from lib.manipulators.rotate_image import RotateImage
from lib.manipulators.sample_n_images import SampleNImages

if TYPE_CHECKING:
    from lib.pipeline.manipulator_base import UnitManipulator

MANIPULATOR_REGISTRY: dict[str, type[UnitManipulator]] = {
    "format_convert_to_coco": FormatConvertToCoco,
    "format_convert_to_yolo": FormatConvertToYolo,
    "format_convert_visdrone_to_coco": FormatConvertVisDroneToCoco,
    "format_convert_visdrone_to_yolo": FormatConvertVisDroneToYolo,
    "merge_datasets": MergeDatasets,
    "filter_remain_selected_class_names_only_in_annotation": FilterRemainSelectedClassNamesOnlyInAnnotation,
    "filter_keep_images_containing_class_name": FilterKeepImagesContainingClassName,
    "filter_remove_images_containing_class_name": FilterRemoveImagesContainingClassName,
    "mask_region_by_class": MaskRegionByClass,
    "remap_class_name": RemapClassName,
    "rotate_image": RotateImage,
    "sample_n_images": SampleNImages,
}
