/**
 * 노드 SDK 스타일 상수.
 *
 * 기존 components/pipeline/nodeStyles.ts에서 이관. 팔레트·NodeShell이 공유.
 * 새 manipulator 이모지/색상 추가는 이 파일에서 일원화한다.
 */

/** 카테고리별 색상/이모지/라벨. operator 노드의 헤더와 팔레트 섹션 헤더가 공유. */
export const CATEGORY_STYLE: Record<string, { color: string; emoji: string; label: string }> = {
  ANNOTATION_FILTER: { color: '#eb2f96', emoji: '🏷️', label: 'Annotation 필터' },
  IMAGE_FILTER:      { color: '#cf1322', emoji: '🖼️', label: 'Image 필터' },
  FORMAT_CONVERT:    { color: '#1677ff', emoji: '🔄', label: '포맷 변환' },
  SAMPLE:            { color: '#722ed1', emoji: '🎲', label: '샘플링' },
  REMAP:             { color: '#fa8c16', emoji: '🔀', label: '리매핑' },
  AUGMENT:           { color: '#13c2c2', emoji: '✨', label: 'Image 변형' },
  MERGE:             { color: '#9254de', emoji: '🔗', label: '병합' },
}

export const DEFAULT_CATEGORY_STYLE = { color: '#8c8c8c', emoji: '⚙️', label: '기타' }

/** manipulator name 당 고유 이모지. 카테고리 이모지와 구분하여 한눈에 노드를 식별한다. */
export const MANIPULATOR_EMOJI: Record<string, string> = {
  det_filter_remain_selected_class_names_only_in_annotation: '🏷️',
  det_filter_keep_images_containing_class_name:   '✅',
  det_filter_remove_images_containing_class_name: '🚫',
  det_format_convert_to_coco:          '🅾️',
  det_format_convert_to_yolo:          '🅨',
  det_format_convert_visdrone_to_coco: '🛩️',
  det_format_convert_visdrone_to_yolo: '✈️',
  det_sample_n_images:    '🎯',
  det_shuffle_image_ids:  '🔀',
  det_remap_class_name:   '🏷️',
  det_rotate_image:          '↩️',
  det_change_compression:    '📐',
  det_mask_region_by_class:  '🎭',
  det_merge_datasets: '🔗',
}

export function getCategoryStyle(category: string) {
  return CATEGORY_STYLE[category] ?? DEFAULT_CATEGORY_STYLE
}

export function getManipulatorEmoji(operatorName: string, category: string): string {
  return MANIPULATOR_EMOJI[operatorName] ?? getCategoryStyle(category).emoji
}
