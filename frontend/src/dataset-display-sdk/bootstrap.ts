/**
 * Dataset Display SDK 부팅.
 *
 * 앱 진입점(main.tsx)에서 import side-effect로 1회 실행된다.
 * - classification을 먼저 등록해 resolveDatasetKind에서 우선 매칭되도록 한다.
 *   (detection definition이 fallback 성격을 띠므로 순서 중요)
 * - 마지막으로 registry 키 집합과 DatasetKind 전역 집합이 일치하는지 검증.
 */
import { assertDatasetKindRegistryCompleteness, registerDatasetKindDefinition } from './registry'
import { classificationDefinition } from './definitions/classificationDefinition'
import { detectionDefinition } from './definitions/detectionDefinition'

registerDatasetKindDefinition(classificationDefinition)
registerDatasetKindDefinition(detectionDefinition)

assertDatasetKindRegistryCompleteness()
