/**
 * 노드 카테고리별 색상 및 이모지 — 팔레트와 캔버스 노드가 공유한다.
 *
 * 같은 유형(필터 등)은 동일 색상을 사용하고, manipulator별 고유 이모지로 구분한다.
 */

/** 카테고리별 스타일 — 색상과 기본 이모지(카테고리 헤더용) */
export const CATEGORY_STYLE: Record<string, { color: string; emoji: string; label: string }> = {
  // 필터 계열 — 동일 색상(#eb2f96)
  ANNOTATION_FILTER: { color: '#eb2f96', emoji: '🏷️', label: 'Annotation 필터' },
  IMAGE_FILTER:      { color: '#cf1322', emoji: '🖼️', label: 'Image 필터' },
  // 변환
  FORMAT_CONVERT:    { color: '#1677ff', emoji: '🔄', label: '포맷 변환' },
  // 기타 조작
  SAMPLE:            { color: '#722ed1', emoji: '🎲', label: '샘플링' },
  REMAP:             { color: '#fa8c16', emoji: '🔀', label: '리매핑' },
  AUGMENT:           { color: '#13c2c2', emoji: '✨', label: 'Image 변형' },
  MERGE:             { color: '#9254de', emoji: '🔗', label: '병합' },
}

export const DEFAULT_CATEGORY_STYLE = { color: '#8c8c8c', emoji: '⚙️', label: '기타' }

/**
 * manipulator name별 고유 이모지.
 * 같은 카테고리 내에서도 노드를 한눈에 구분할 수 있도록 각각 다른 이모지를 사용한다.
 */
const MANIPULATOR_EMOJI: Record<string, string> = {
  // ANNOTATION_FILTER
  filter_remain_selected_class_names_only_in_annotation: '🏷️',
  // IMAGE_FILTER
  filter_keep_images_containing_class_name:   '✅',
  filter_remove_images_containing_class_name: '🚫',
  // FORMAT_CONVERT
  format_convert_to_coco:          '🅾️',
  format_convert_to_yolo:          '🅨',
  format_convert_visdrone_to_coco: '🛩️',
  format_convert_visdrone_to_yolo: '✈️',
  // SAMPLE
  sample_n_images:    '🎯',
  shuffle_image_ids:  '🔀',
  // REMAP
  remap_class_name:   '🏷️',
  // AUGMENT
  rotate_image:          '↩️',
  change_compression:    '📐',
  mask_region_by_class:  '🎭',
  // MERGE
  merge_datasets: '🔗',
}

/** 기본 노드(특수 노드) 스타일 */
export const SPECIAL_NODE_STYLE = {
  DATA_LOAD: { color: '#52c41a', emoji: '📂' },
  MERGE:     { color: '#9254de', emoji: '🔗' },
  SAVE:      { color: '#fa541c', emoji: '💾' },
} as const

/** 카테고리에 해당하는 스타일을 반환 */
export function getCategoryStyle(category: string) {
  return CATEGORY_STYLE[category] ?? DEFAULT_CATEGORY_STYLE
}

/** manipulator name에 해당하는 고유 이모지를 반환. 없으면 카테고리 기본 이모지. */
export function getManipulatorEmoji(operatorName: string, category: string): string {
  return MANIPULATOR_EMOJI[operatorName] ?? getCategoryStyle(category).emoji
}
