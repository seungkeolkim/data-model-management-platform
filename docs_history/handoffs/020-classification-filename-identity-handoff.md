# 통합 핸드오프 020 — Classification 이미지 identity: SHA → filename 전환

> 최종 갱신: 2026-04-20
> 이전 핸드오프: `docs_history/handoffs/019-null-unknown-convention-handoff.md`
> 설계 현행: `objective_n_plan_7th.md` (v7.5, §2-8 / §2-11 / §2-13 갱신)
> 이번 세션 브랜치: `feature/classification-image-transform-identity-01`
> 주요 커밋:
> - `b4de107` refactor(classification): 이미지 identity 를 SHA content → filename 기반으로 전환 (§2-8)
> - `f3631b2` docs: 설계서 v7.5 갱신 + handoff 020 — classification filename-identity 전환
> - `710fc88` feat(classification-viewer): 상세 뷰 파일명을 현재 파일명으로 노출 + 원본은 rename 시에만 병기

019 에서 classification 파이프라인 stub 제거와 `null` = unknown 규약 확정이 끝난 뒤,
실제 파이프라인 테스트를 돌리는 과정에서 Phase B 실체화 단계가 동일 SHA 체계 기반으로
계속 가정되고 있다는 점이 드러났다. 이를 기회로 classification 이미지 identity 를
**SHA-1 content hash → filename** 으로 전환하고, detection 과 규칙을 통일했다.

---

## 1. 이번 세션에서 확정한 변경

### 1-1. 설계 결정 — filename = identity (§2-13 신설)

- 이미지 identity 는 **filename (full relative path, `images/<basename>`)**. 같은 파일명이 여러 (head, class) 폴더에 등장하면 같은 이미지로 간주한다.
- **등록**: single-label head 내 파일명 충돌 = 사용자 라벨링 오류 → warning + skip, `metadata.class_info.skipped_collisions` 기록.
- **병합**: 두 입력에 같은 파일명이 있으면 detection 경로와 동일하게 `{display_name}_{md5_4}_{basename}` prefix rename 으로 공존. label 충돌 판정 단계가 사라진다.
- **Phase B 실체화**: rename 결과가 dst, 원본이 src. `ImageRecord.extra.{source_storage_uri, original_file_name, source_dataset_id}` 로 src 복원.
- **폐지 항목**: `ImageRecord.sha`, `manifest.jsonl` 의 `sha` 필드, `duplicate_image_policy` (FE Radio 포함), `DuplicateConflictError` / `DuplicateConflict` / `IntraClassDuplicate`, `metadata.class_info.skipped_conflicts` / `intra_class_duplicates`. v7.4 이전 데이터는 전량 삭제 후 재등록 기조 유지.

상세 근거와 미채택 옵션 기록은 설계서 §2-13 참조.

### 1-2. 코드 반영 (커밋 `b4de107`)

| 파일 | 변경 내용 |
|---|---|
| `lib/pipeline/pipeline_data_models.py` | `ImageRecord.sha` 필드 제거 + docstring 정리 |
| `lib/pipeline/io/manifest_io.py` | reader/writer 양쪽에서 `sha` 필드 제거, `filename` 이 유일 identity |
| `lib/classification/ingest.py` | SHA dedup 폐지 → filename 기반. `FilenameCollision` dataclass 신설, single-label 충돌 시 warning + skip + `skipped_collisions` 반환 |
| `lib/manipulators/cls_merge_datasets.py` | 전면 재작성: SHA dedup / drop 로직 제거, 파일명 충돌 시 detection 규칙(`{display_name}_{md5_4}_{basename}`)으로 rename 하여 공존. `ImageRecord.extra` 에 `source_storage_uri / original_file_name / source_dataset_id` 주입 |
| `lib/pipeline/cls_merge_compat.py` | 호환 검증에서 SHA 관련 체크 제거, on_label_conflict 파라미터 제거 |
| `lib/pipeline/dag_executor.py` | classification Phase B: `record.file_name` 은 dst 전용, src 는 `extra.source_storage_uri + extra.original_file_name` 우선 사용, 없으면 비-merge 경로로 `record.file_name` fallback. docstring 에 merge rename 처리 기술 |
| `lib/classification/__init__.py` | `FilenameCollision` export, 폐기된 타입/함수 제거 |
| `lib/manipulators/cls_*.py` (8종) | docstring 에서 `sha/file_name 유지` → `file_name 유지` 정리 |
| `app/schemas/dataset.py` | `DuplicateImagePolicy` 타입, `duplicate_image_policy` 필드 제거. 섹션 주석에 v7.5 전환 배경 기록 |
| `app/services/dataset_service.py`, `app/api/v1/dataset_groups/router.py` | `duplicate_policy` 로깅/Celery 파라미터 전달 제거 |
| `app/tasks/register_classification_tasks.py` | 전면 재작성: `FilenameCollision` 기반 메타데이터 (`skipped_collision_count / skipped_collisions`), `except DuplicateConflictError` 경로 제거, `_format_skipped_collision_lines` 신규 |
| `frontend/src/types/dataset.ts` | `DuplicateImagePolicy` 타입 제거, `ClassificationClassInfo` 에서 `skipped_conflicts* / intra_class_duplicate*` → `skipped_collision_count / skipped_collisions` |
| `frontend/src/components/dataset/DatasetRegisterModal.tsx` | 중복 정책 Radio.Group + `duplicatePolicy` state 완전 제거 |

DB 변경 없음. Alembic 마이그레이션 불필요.

### 1-3. 테스트

| 파일 | 변경 |
|---|---|
| `backend/tests/test_cls_merge_datasets.py` | 전면 재작성 — SHA dedup 테스트 4건 삭제, filename rename / extra 필드 / fill_empty=None / 충돌 없을 때 그대로 유지 케이스 재구성 |
| `backend/tests/test_cls_sample_n_images.py`, `test_cls_demote_head_to_single_label.py`, `test_cls_merge_classes.py` | `sha=` 인자 / `record.sha` 참조 전체 제거. 기존 테스트 의도는 유지 |
| `backend/tests/test_classification_ingest.py` (신규) | 5 케이스 — 행복경로 / multi-head 통합 / multi-label OR 병합 / single-label 충돌 skip / 한쪽 head 에만 등장 시 다른 head = null |

`uv run pytest tests/` → **242 / 242 통과**.

### 1-4. 실등록 / 파이프라인 검증

- `/hdd1/data-platform/uploads/hardhat_classification/val` (5613장 + 의도적 중복 1건) 을 `hardhat` 그룹 `VAL` split 으로 GUI 등록.
  - `image_count = 5612`
  - `metadata.class_info.skipped_collision_count = 1`
  - `skipped_collisions[0]` = `1st_headcrop_image_202506_00004_person__001_0.3993.jpg` (head `hardhat_wear`, classes `[0_no_helmet, 1_helmet]`, 두 경로 모두 기록)
  - `process.log` 에 `READY_WITH_SKIPS (skipped=1)` + skip 상세 출력 확인.
  - 디스크: `images/` 폴더 5612 파일, `manifest.jsonl` 5612 줄.
- 파이프라인 2건 성공 (사용자 확인):
  - `28ce7e89-3e58-4122-b439-596206f3d8ae`: 전 기능 포함
  - `75919089-11ce-4535-ac35-7a90612d0f6e`: 샘플 100개 추출 제외 전 기능
  - merge 후 `processed/hardhat_full_test_nosample/val/1.0/manifest.jsonl` 11224 줄 (5612 × 2) — content dedup 이 없으므로 정상 기대값.

---

## 2. 남아 있는 후속 작업

### 2-1. 데이터셋 상세 보기 파일명 표시 전환 (완료 · 커밋 `710fc88`)

방향 (2) "rename 된 경우만 원본 병기" 로 확정·반영됨.

- 백엔드 `ClassificationSampleImageItem` 스키마: `sha` 필드 제거, `file_name: str` (현재 파일명) + `original_file_name: str | None` (rename 시에만 값) 로 재구성.
- `get_classification_sample_list` 가 `stored_filename` 을 `file_name` 으로 내리고, 캐시된 `original_filename` 이 이와 다를 때만 `original_file_name` 을 세팅.
- 프론트 `ClassificationSampleViewerTab` 미리보기: 현재 파일명을 기본 표시, `original_file_name` 이 있으면 "(원본: …)" 를 secondary 스타일로 병기. 기존 `sha:` 라인 삭제.
- 좌측 리스트 검색: `file_name` + `original_file_name` 양쪽을 대상으로 매칭하여 merge rename 결과를 원본 이름으로도 찾을 수 있게 확장.
- 실데이터 검증: `hardhat` RAW (rename 없음) 는 한 줄만 노출, `hardhat_full_test_nosample` (merge 결과) 은 prefix 파일명 + "(원본: …)" 병기 정상 표시.

### 2-2. 기타 TODO (우선순위 낮음)

- `cls_merge_datasets` 의 `processing.log` 라인 포맷 (현재 summary 줄 + rename 내역) 에서 `dropped=` 필드가 사라졌는지 run-time 확인. 기대치: `cls_merge_datasets: renamed=M, promoted=K heads`.
- 주석 이관 점검: §2-11 내에 "SHA", "dedup" 같은 용어가 backend 주석에 산발적으로 남아있지 않은지 추가 sweep (짧은 grep 으로 끝나는 작업).

---

## 3. 검증 명령 체크리스트

```bash
# 백엔드 테스트
cd backend && uv run pytest tests/ -q

# 레거시 참조 회귀 검사 (tests / lib / app)
grep -RnE '\.sha|record\.sha|sha=|DuplicatePolicy|DuplicateImagePolicy|duplicate_policy|duplicate_image_policy|IntraClassDuplicate|skipped_conflicts|intra_class_duplicate|DuplicateConflict' backend/lib backend/app backend/tests frontend/src

# DB 메타데이터 검증 (hardhat val 기준)
docker compose exec -T postgres psql -U mlplatform -d mlplatform -c \
  "SELECT image_count, metadata->'class_info'->'skipped_collision_count' FROM datasets WHERE storage_uri='raw/hardhat/val/1.0';"
```

---

## 4. 참고

- 이전 핸드오프 019 까지의 흐름: detection stub 제거 → `null` unknown 규약 확정 → `cls_merge_classes` / `cls_demote_head_to_single_label` / `cls_sample_n_images` 실구현.
- 이번 세션은 019 와 독립된 refactor 성격. 신규 manipulator 는 없음, 대신 lib / app / frontend 전반의 identity 축을 바꿨다.
