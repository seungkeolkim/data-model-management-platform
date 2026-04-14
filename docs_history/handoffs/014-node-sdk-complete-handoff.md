# 통합 핸드오프 014 — 파이프라인 노드 SDK 완성 후

> 최종 갱신: 2026-04-13
> 이전 핸드오프: `docs_history/handoffs/013-consolidated-handoff.md` (013까지 아카이브)
> 설계 현행: `objective_n_plan_7th.md`
> 신규 가이드: `docs/pipeline-node-sdk-guide.md` (사람용 — manipulator/NodeKind 추가 규약)

이 문서는 013 시점 이후 적용된 변경을 baseline에 반영하고, 아직 남은 작업만 추린 현행 핸드오프다. 구현 완료 항목(노드 SDK, 자동 발견, placeholder, schema_version)은 baseline으로 편입되어 TODO에서 빠졌다.

---

## 1. 013 → 014 사이 적용된 변경

| 영역 | 변경 | 위치 |
|------|------|------|
| 프론트 SDK | `frontend/src/pipeline-sdk/` 신설 — NodeDefinition 1개 = 팔레트/NodeComponent/PropertiesComponent/validate/toConfigContribution/matchFromConfig/matchIssueField 일체 | `pipeline-sdk/{types,registry,bootstrap,engine,definitions,components,hooks,styles}` |
| 프론트 SDK | 5종 NodeKind(`dataLoad`, `operator`, `merge`, `save`, `placeholder`) 각 definition으로 이관 | `pipeline-sdk/definitions/*.tsx` |
| 프론트 SDK | `configToGraph` / `graphToConfig` / `clientValidation` / `distributeIssuesToNodes` 엔진화 | `pipeline-sdk/engine/*.ts` |
| 프론트 SDK | `placeholder` 노드 — 미등록 operator도 유실 없이 복원, 실행 시 validate 차단 | `placeholderDefinition.tsx` |
| 프론트 SDK | `PipelineConfig.schema_version = 1` 기입 (버전 상승 시 migrator 자리) | `engine/graphToConfig.ts` |
| 프론트 SDK | registry 완전성 런타임 assert — 새 NodeKind 추가 시 3군데 갱신 강제 | `registry.ts` `assertRegistryCompleteness` |
| 프론트 통합 | `PipelineEditorPage` / `PropertiesPanel` / `NodePalette` / store SDK 경로 전환, 구 `nodes/*.tsx` · `pipelineConverter.ts` · `nodeStyles.ts` 제거 | |
| 백엔드 | `MANIPULATOR_REGISTRY` 자동 발견 — `lib/manipulators/` 하위 모듈만 추가하면 수동 등록 불요. 중복 name 즉시 RuntimeError | `backend/lib/manipulators/__init__.py` |
| 백엔드 | `PipelineConfig.schema_version: int \| None` 필드 추가 (YAGNI — migrator 없음, 완충 필드만) | `backend/lib/pipeline/config.py` |
| 문서 | 사람용 "새 노드 만드는 법" 가이드 작성 + CLAUDE.md에서 필독 명시 | `docs/pipeline-node-sdk-guide.md` |

**검증 완료**: JSON 복원 → Phase A(9초, 8 tasks) → Phase B(이미지 실체화 4738장 rotate+mask) 성공. 재직렬화 왕복 시 `source:<id>` 및 operator task 정확 복원 확인.

---

## 2. 현재 baseline 스냅샷 (013의 §1에 위 변경 반영)

- **백엔드**: FastAPI + async SQLAlchemy. Celery(sync 세션) 파이프라인/RAW 등록. Broker/Backend = PostgreSQL. `MANIPULATOR_REGISTRY`는 `pkgutil.iter_modules` 자동 발견.
- **파이프라인 모델**: DAG 기반 `PipelineConfig` + `schema_version:int|None`. 통일포맷(`category_name:str`). IO 경계에서만 포맷별 ID 처리.
- **MANIPULATOR (12종)**: format_convert 4 (no-op) / merge_datasets / filter_keep·remove_images_containing_class_name / filter_remain_selected_class_names_only_in_annotation / remap_class_name / rotate_image / mask_region_by_class / sample_n_images.
- **GUI 에디터**: React Flow + Zustand `nodeDataMap` 단일 소스. **5종 NodeKind** (dataLoad / operator / merge / save / placeholder). Merge 외 입력 엣지 1개 강제. 노드 스펙 추가는 `pipeline-sdk/definitions/` 한 파일.
- **버전 정책**: `{major}.{minor}`. major=수동, minor=automation 예약(미구현).
- **검증 체계**: 정적(`lib/pipeline/pipeline_validator.py`) + DB(`app/services/pipeline_service.py`) + 클라이언트(`pipeline-sdk/engine/clientValidation.ts`).
- **실행 제출/상세**: 202 응답 + `ExecutionSubmittedModal`, 이력 행 클릭 → `ExecutionDetailDrawer`. Config JSON 확인/복사 + JSON→DAG 복원 지원. 미등록 operator는 `placeholder` 노드로 복원되고 실행 단계에서 차단.

---

## 3. 남은 작업 (우선순위 순)

### 3-1. Classification 데이터 입력 [1순위]

현재 Detection 전용. Classification 전용 흐름 설계·구현 필요.

- RAW 등록 UI: 이미지 디렉토리 구조(폴더=class) / manifest CSV 선택
- 파서/라이터: Classification label 포맷(단일 라벨 / 멀티 라벨)
- DatasetGroup.task_types 분기: `CLASSIFICATION`
- Manipulator 재분류: detection 전용(bbox 의존) / 공통(filter / sample / remap) 구분
- 뷰어: class distribution 뷰 추가

**관련 메모리**: `project_detection_only_scope.md` (현재 범위 명시).

### 3-2. Automation 실구현 [2순위]

6차 설계서 §6 시나리오. 원천 데이터 버전업 → downstream 파이프라인 연쇄 실행.

- `PipelineTemplate` — DB에 템플릿 저장(최초 실행 config snapshot)
- `find_downstream_templates(source_dataset_id)` — lineage 역추적
- `dispatch_automation_run(template, is_automation=True)` — Celery dispatch, minor 증가
- 실패/중복 방지: 동일 `(template_id, source_version)` 재실행 스킵
- UI: 자동 실행 이력 구분 표시

### 3-3. 미구현 Manipulator 2종 [3순위]

- `change_compression` — JPEG 품질·PNG 압축 수준 변경 (이미지 파일 재인코딩)
- `shuffle_image_ids` — COCO의 image_id 셔플 (학습 재현성 테스트용)

팔레트에는 `disabled=true`로 이미 노출 중. `lib/manipulators/`에 구현 파일 + seed만 추가하면 바로 활성화.

### 3-4. 버전 정책 운영 검증

수동 실행과 automation 동시 발생 시 minor 번호 충돌 가능성. 현재 미구현이므로 3-2와 묶어서 테스트.

### 3-5. 잔여 백로그 (p3 이하)

| 영역 | 항목 |
|------|------|
| Manipulator | IoU 기반 annotation 제거 / IoU 기반 masking (신규 후보) |
| Manipulator UX | `sample_n_images` DAG 위치 안내 (필터 전/후 차이) |
| GUI | MergeNode params_schema 폼 (확장 대비, 보류 가능) |
| 품질 | `_write_data_yaml` 등 general 함수명 리네이밍 |
| 품질 | 뷰어 / EDA 전수 검증 (`schema_version=2` 캐시 재생성) |
| 품질 | Integration / Regression / E2E 테스트 (Celery 안정화 후) |
| 품질 | DB seed ↔ 자동 발견 레지스트리 대조 정기 점검 |
| Step 2 연계 | YOLO `data.yaml` 학습용 `path/train/val` 키 주입 |

### 3-6. Phase 3 — 2차 수용 준비 & UX 정리 (예정)

Step 2 진입 전 필수.

- `TrainingExecutor` 추상 인터페이스 (submit_job / get_job_status / cancel_job)
- `GPUResourceManager` 추상 인터페이스 (get_available_gpus / reserve / release)
- 알림 Celery signal 골격 + SMTP env 구조
- GNB 확정(모델 학습 메뉴 "준비 중"), Manipulator 관리 페이지, 시스템 상태 페이지
- 전체 UX 정리 (빈 상태 안내 / 에러 토스트 / 로딩 일관성)

---

## 4. 유의사항 / 규약

- **새 manipulator·NodeKind 추가는 반드시 `docs/pipeline-node-sdk-guide.md` 를 먼저 읽을 것.** `assertRegistryCompleteness`로 부팅 차단됨.
- `schema_version` — 지금은 v1. 구조 변경 시 v2로 올리고 `matchFromConfig`에서 분기. 하위 호환 migrator는 도입 보류(YAGNI).
- `placeholder` 노드는 유실 방지 목적. 실행 시 validate가 차단 — 이걸 "복원되면 실행 가능"으로 착각하지 말 것.
- Celery worker concurrency=4지만 파이프라인 1건 = worker 1슬롯. Phase B(이미지 실체화)가 대개 병목 — 대용량 실행 시 다른 Celery 작업(RAW 등록 등)과 슬롯 경합 가능.
- `lib/` → `app/` import 금지 원칙 유지. SDK는 프론트 전담이므로 백엔드에 영향 없음.
