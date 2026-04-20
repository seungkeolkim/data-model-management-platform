/**
 * 노드 SDK 스타일 상수.
 *
 * 기존 components/pipeline/nodeStyles.ts에서 이관. 팔레트·NodeShell이 공유.
 * 새 manipulator 이모지/색상 추가는 이 파일에서 일원화한다.
 */

/**
 * 카테고리별 색상/이모지/라벨. operator 노드의 헤더와 팔레트 섹션 헤더가 공유.
 *
 * 키 선언 순서 = 팔레트 내 카테고리 노출 순서 (NodePalette 가 이 객체의
 * key order 를 그대로 사용한다). 위쪽이 위에 표시된다.
 *
 * CLS_HEAD_CTRL / CLS_CLASS_CTRL 은 classification 전용 분화 카테고리.
 * 기존 SCHEMA 카테고리는 아무도 쓰지 않게 되어 제거했다.
 */
export const CATEGORY_STYLE: Record<string, { color: string; emoji: string; label: string }> = {
  CLS_HEAD_CTRL:     { color: '#52c41a', emoji: '🗂️', label: '분류 항목 제어' },
  CLS_CLASS_CTRL:    { color: '#faad14', emoji: '🎯', label: '분류 Class 상세 제어' },
  ANNOTATION_FILTER: { color: '#eb2f96', emoji: '🏷️', label: 'Annotation 필터' },
  IMAGE_FILTER:      { color: '#cf1322', emoji: '🖼️', label: 'Image 필터' },
  FORMAT_CONVERT:    { color: '#1677ff', emoji: '🔄', label: '포맷 변환' },
  SAMPLE:            { color: '#722ed1', emoji: '🎲', label: '샘플링' },
  REMAP:             { color: '#fa8c16', emoji: '🔀', label: '리매핑' },
  AUGMENT:           { color: '#13c2c2', emoji: '✨', label: 'Image 변형' },
  MERGE:             { color: '#9254de', emoji: '🔗', label: '병합' },
}

/**
 * 카테고리 내부의 팔레트 항목 정렬 순서(manipulator name 기준).
 * 여기에 나열된 이름은 배열 순서대로, 나머지는 뒤에 알파벳 순으로 붙는다.
 * API 응답의 기본 정렬(name asc) 을 덮어써야 할 때만 항목을 추가한다.
 */
export const CATEGORY_ITEM_ORDER: Record<string, readonly string[]> = {
  CLS_HEAD_CTRL: [
    'cls_add_head',
    'cls_select_heads',
    'cls_rename_head',
    'cls_reorder_heads',
    'cls_demote_head_to_single_label',
    'cls_set_head_labels_for_all_images',
  ],
  CLS_CLASS_CTRL: ['cls_rename_class', 'cls_reorder_classes', 'cls_merge_classes'],
  AUGMENT: ['cls_crop_image', 'cls_rotate_image'],
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
  cls_merge_datasets: '🔗',
  cls_demote_head_to_single_label: '⬇️',
  cls_crop_image: '✂️',
  cls_rotate_image: '↩️',
  cls_add_head: '➕',
  cls_set_head_labels_for_all_images: '📝',
}

export function getCategoryStyle(category: string) {
  return CATEGORY_STYLE[category] ?? DEFAULT_CATEGORY_STYLE
}

export function getManipulatorEmoji(operatorName: string, category: string): string {
  return MANIPULATOR_EMOJI[operatorName] ?? getCategoryStyle(category).emoji
}
