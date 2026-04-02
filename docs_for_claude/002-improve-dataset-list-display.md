# 데이터셋 목록/상세 페이지 개선 및 클래스 정보 검증 기능

> 브랜치: `feature/improve-dataset-list-display`
> 작업 기간: 2026-04-02

---

## 변경 요약

데이터셋 그룹 목록 페이지와 상세 페이지의 UI 개선, 어노테이션 포맷 인라인 변경 기능, 클래스 정보 검증/표시 기능 구현.

---

## 1. 데이터셋 그룹 목록 페이지 개선

**관련 파일:** `frontend/src/pages/DatasetListPage.tsx`

- 페이지 제목: `데이터셋` → `데이터셋 그룹`
- 등록 버튼: `데이터셋 등록` → `원천 데이터셋 등록`
- 데이터 유형 컬럼 추가: RAW/SOURCE/PROCESSED/FUSION Tag 표시

---

## 2. 데이터셋 그룹 상세 페이지 재구성

**관련 파일:** `frontend/src/pages/DatasetDetailPage.tsx`

- 기존 탭 구조(기본 정보 / 샘플 보기 / EDA / Lineage) 전면 제거
- 상단: 그룹 기본 정보 (Descriptions) — 유형, 포맷, 모달리티, 사용 목적, 출처, 등록일
- 하단: 소속 데이터셋 목록 테이블 — Split(TRAIN→VAL→TEST→NONE) 우선 정렬, 같은 Split 내 버전 내림차순(최신이 위)

---

## 3. 클래스 정보 검증 및 표시 기능

### 백엔드

**관련 파일:**
- `backend/app/schemas/dataset.py`
- `backend/app/services/dataset_service.py`
- `backend/app/api/v1/datasets/router.py`

**신규 엔드포인트:**
- `PATCH /api/v1/datasets/{id}` — 개별 데이터셋 수정 (annotation_format 등)
- `POST /api/v1/datasets/{id}/validate` — 등록된 데이터셋 어노테이션 검증 + 클래스 정보 DB 저장

**주요 변경:**
- `DatasetSummary`, `DatasetResponse` 스키마에 `metadata` 필드 추가 (`validation_alias="metadata_"`)
- `DatasetUpdate`, `DatasetValidateRequest` 스키마 신규
- COCO/YOLO 검증 summary에 `class_mapping` (id→name 딕셔너리) 추출 추가
- `validate_and_persist_class_info()` 메서드: 관리 스토리지의 파일을 읽어 검증 후 `class_count`, `metadata_` 저장
- `register_dataset()` 마지막에 COCO/YOLO 포맷이면 클래스 정보 자동 추출 (best-effort, 실패해도 등록 성공)
- `update_dataset()` — annotation_format 변경 시 `class_count`, `metadata_` 자동 초기화 (재검증 필요)

**metadata 저장 구조:**
```json
{
  "class_info": {
    "class_count": 5,
    "class_mapping": { "0": "person", "1": "car", "2": "bicycle" }
  }
}
```

### 프론트엔드

**관련 파일:**
- `frontend/src/types/dataset.ts`
- `frontend/src/api/dataset.ts`
- `frontend/src/pages/DatasetDetailPage.tsx`

**타입 추가:** `ClassInfo`, `DatasetMetadata`, `DatasetValidateRequest`
**API 추가:** `datasetsApi.update()`, `datasetsApi.validate()`

**UI 변경:**
- "클래스 수" 컬럼 → "클래스 정보" 컬럼
  - 클래스 정보 있으면: `N개` + `상세보기` 링크 → Popover로 ID→클래스명 매핑 테이블 표시
  - 클래스 정보 없으면: `검증` 버튼 (COCO/YOLO 포맷만 활성)
- "포맷" 컬럼: Tag + `변경` 링크 → 클릭 시 Select 드롭다운 + `확인`/`취소` 버튼으로 전환
  - 포맷 변경 시 백엔드에서 클래스 정보 자동 초기화 → 재검증 필요

---

## 4. Pydantic alias 이슈 해결

**문제:** ORM 속성명 `metadata_`와 JSON 응답 키 `metadata` 간 매핑에서 Pydantic v2의 `alias` 사용 시 직렬화 키도 alias로 출력됨

**해결:** `alias="metadata_"` → `validation_alias="metadata_"` 변경
- `validation_alias`: 입력(ORM 읽기)만 `metadata_`로 처리
- 출력(JSON 직렬화): 필드명 `metadata`로 내보냄

---

## 5. 데이터셋 그룹 / 데이터셋 삭제 기능

### 설계: Soft Delete + 버전 이력 보존

**요구사항:** v1.0.0, v1.0.1, v1.0.2 중 v1.0.2를 삭제해도 다음 생성 시 v1.0.3이 되어야 함.

**해결:** `deleted_at` TIMESTAMP 컬럼으로 소프트 삭제. `_next_version()`은 삭제 필터 없이 전체 레코드 조회하여 버전 연속성 보장.

### DB 마이그레이션

**관련 파일:** `backend/migrations/versions/004_add_deleted_at_soft_delete.py`

- `dataset_groups`, `datasets` 테이블에 `deleted_at` 컬럼 추가
- NULL이면 활성 상태, 값이 있으면 삭제된 상태

### 백엔드

**관련 파일:**
- `backend/app/models/all_models.py`
- `backend/app/services/dataset_service.py`
- `backend/app/api/v1/datasets/router.py`
- `backend/app/api/v1/dataset_groups/router.py`
- `backend/app/core/storage.py`

**주요 변경:**
- `DatasetGroup`, `Dataset` 모델에 `deleted_at` 필드 추가
- 모든 조회(목록/단건/selectinload)에 `deleted_at IS NULL` 필터 적용
- `_next_version()`은 삭제 포함 조회 유지 (버전 이력 보존 핵심)
- `delete_group()`: 하위 활성 데이터셋 스토리지 파일 삭제 → DB 일괄 soft delete
- `delete_dataset()`: 스토리지 파일 삭제 → DB soft delete
- `StorageClient.delete_dataset_directory()` 추상 메서드 신규
- `LocalStorageClient.delete_dataset_directory()`: 디렉토리 삭제 + 빈 상위 디렉토리 재귀 정리
- `create_group()`에 활성 그룹 동일 이름 중복 검사 추가
- 스토리지 삭제 실패 시에도 DB 삭제는 계속 진행 (best-effort)

### 프론트엔드

**관련 파일:**
- `frontend/src/pages/DatasetDetailPage.tsx`
- `frontend/src/pages/DatasetListPage.tsx`

**UI 변경:**
- 그룹 목록 페이지: 각 행 액션 컬럼에 삭제 버튼(Popconfirm) 추가
- 그룹 상세 페이지: 우측 상단에 "그룹 삭제" 버튼(Popconfirm) — 하위 데이터셋 수 표시
- 데이터셋 테이블: 각 행 맨 오른쪽에 삭제 버튼(Popconfirm) 추가
- 그룹 삭제 시 목록 페이지로 이동, 데이터셋 삭제 시 상세 페이지 새로고침

### 동일 그룹명 재생성 시 동작

- 삭제된 그룹은 `deleted_at IS NULL` 필터로 제외되므로 동일 이름 재생성 가능
- 새 그룹은 새 UUID → 버전 v1.0.0부터 독립 시작

---

## 커밋 이력

```
d43c01d feat: 데이터셋 목록/상세 페이지 개선 및 클래스 정보 검증 기능
07e7566 fix: metadata 필드 Pydantic alias → validation_alias 변경
6067dcc feat: 데이터셋 상세 페이지에서 어노테이션 포맷 인라인 변경 기능
fe16f4d feat: 포맷 변경 시 '변경→확인' 2단계 UI + 클래스 정보 자동 초기화
d085c35 feat: 데이터셋 그룹 삭제 기능 추가
```

---

## 미완료 / 후속 작업

- 샘플 보기, EDA, Lineage 기능은 Phase 2에서 구현 예정 (이번에 탭 제거함)
- 포맷 변경은 현재 개별 Dataset 단위. 그룹 단위 일괄 변경은 미구현
- YOLO class_mapping은 이름 없이 ID만 표시 (YOLO 포맷 자체에 클래스명이 없음). data.yaml/classes.txt 파싱은 미구현
