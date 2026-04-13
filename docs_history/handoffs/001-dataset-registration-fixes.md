# 데이터셋 등록 오류 수정 및 UX 개선 기록

> 브랜치: `feature/data-insertion-error-correct-01`
> 작업 기간: 2026-04-01

---

## 원래 이슈 (1~6)

### 이슈 1: 네이밍 컨벤션 위반 수정

**목표:** CLAUDE.md 규칙에 따라 한 글자·한 단어 함수/변수명 제거

**수정 내용:**
- `_m()` → `_build_manipulator_seed_record()` 등 백엔드 전반 리네이밍
- CLAUDE.md에 네이밍 규칙 섹션 추가

**관련 파일:** 백엔드 전반 (services, models, config 등)

---

### 이슈 2: 중복 그룹명 문제

**목표:** 같은 이름의 그룹이 중복 생성되지 않도록 기존 그룹 선택 지원

**수정 내용:**
- 그룹명 텍스트 입력 → 드롭다운(기존 그룹 이름순 정렬 + "새 그룹 만들기" 옵션)
- 기존 그룹 선택 시 해당 그룹에 새 split/version 추가

**관련 파일:** `frontend/src/components/dataset/DatasetRegisterModal.tsx`

---

### 이슈 3: 파일 브라우저 z-index 문제

**목표:** 모달 위에 띄우는 파일 브라우저가 뒤에 가려지는 문제 해결

**수정 내용:** `ServerFileBrowser.tsx`의 Modal에 `zIndex={1010}` 적용

**관련 파일:** `frontend/src/components/common/ServerFileBrowser.tsx`

---

### 이슈 4: 경로 직접 입력 기능

**목표:** 깊은 디렉토리를 일일이 클릭하지 않고 경로를 직접 타이핑하여 이동

**수정 내용:**
- `ServerFileBrowser.tsx` 상단에 경로 입력 Input 추가 (`addonBefore`로 루트 경로 표시)
- `pathInputValue` 상태를 네비게이션과 동기화
- Enter 시 해당 경로로 이동, 존재하지 않는 경로면 에러 표시
- `rootPath` 상태를 `is_browse_root` 응답에서 캡처
- `toRelativePath()` 헬퍼로 절대/상대 경로 변환

**관련 파일:** `frontend/src/components/common/ServerFileBrowser.tsx`

---

### 이슈 5: 어노테이션 포맷 사전 검증

**목표:** 선택한 파일이 COCO/YOLO 포맷에 맞는지 등록 전에 검증 (경고 용도, 등록 차단 안 함)

**수정 내용:**
- 백엔드: `POST /api/v1/dataset-groups/validate-format` 엔드포인트 신규
  - COCO: JSON 파싱 → `images`, `annotations`, `categories` 키 존재 확인 + 데이터 요약 반환
  - YOLO: 대량 파일 시 최대 50개 랜덤 샘플링, 파일당 20줄 검사
- 프론트엔드: Step 2에 "포맷 검증" 버튼 + 성공/실패 결과 표시 (데이터 요약 포함)
- `FormatValidateRequest`, `FormatValidateResponse` 스키마 추가

**관련 파일:**
- `backend/app/api/v1/dataset_groups/router.py`
- `backend/app/schemas/dataset.py`
- `backend/app/services/dataset_service.py`
- `frontend/src/api/dataset.ts`
- `frontend/src/types/dataset.ts`
- `frontend/src/components/dataset/DatasetRegisterModal.tsx`

---

### 이슈 6: 파일 복사 중 상태 안내

**목표:** 대용량 등록 시 사용자에게 복사 진행 상태를 안내

**수정 내용:**
- 경과 시간 타이머 (`useRef` + `setInterval`)
- 타임아웃 시간 `.env`로 외부화 (`VITE_REGISTER_TIMEOUT_MINUTES`, 기본 60분)
- 복사 대상 경로(`raw/{그룹명}/{split}/`) 표시
- `ls` 명령어로 진행 상황 확인 가능하다는 힌트 표시
- `docker-compose.yml`에 `VITE_REGISTER_TIMEOUT_MINUTES` 환경변수 전달

**관련 파일:**
- `frontend/src/components/dataset/DatasetRegisterModal.tsx`
- `.env`, `.env.example`
- `docker-compose.yml`

---

## 추가 이슈 (A~E)

### 이슈 A: 그룹명 입력 폼 활성화 조건

**목표:** "새 그룹 만들기" 선택 시에만 그룹명 입력 활성화, 그 외엔 비활성

**수정 내용:**
- 그룹명 Input을 조건부 렌더링에서 상시 렌더링 + `disabled={!isNewGroup}`으로 변경
- 비활성 시 안내 placeholder 표시

**관련 파일:** `frontend/src/components/dataset/DatasetRegisterModal.tsx`

---

### 이슈 B: 등록 시 자동 생성 버전 미리보기

**목표:** 등록 전에 자동 생성될 버전(예: v1.0.0, v2.0.0)을 사용자에게 표시

**수정 내용:**
- 백엔드: `GET /api/v1/dataset-groups/next-version?group_id=...&split=...` 엔드포인트 추가
- 프론트엔드: `nextVersion` 상태 + `fetchNextVersion()` 헬퍼
  - 그룹 드롭다운 변경, Split 변경, Step 2 진입 시 자동 조회
  - 신규 그룹은 항상 `v1.0.0` 표시 (API 호출 없이)
  - 요약 Descriptions에 "버전" 항목 표시

**관련 파일:**
- `backend/app/api/v1/dataset_groups/router.py`
- `frontend/src/api/dataset.ts`
- `frontend/src/components/dataset/DatasetRegisterModal.tsx`

---

### 이슈 C: 현재 폴더 전체 파일 선택 기능

**목표:** YOLO처럼 수천 개 어노테이션 파일이 있을 때 일일이 선택하지 않고 폴더 전체 선택

**수정 내용:**
- `ServerFileBrowser.tsx` footer에 "현재 폴더 전체 선택 (N개)" 버튼 추가
- `handleSelectAllFilesInCurrentDir()` — 현재 디렉토리의 모든 파일을 한 번에 선택
- file 모드 + multiple일 때만 표시

**관련 파일:** `frontend/src/components/common/ServerFileBrowser.tsx`

---

### 이슈 D: 대량 어노테이션 파일 폴더 축약 표시

**목표:** 수천 개 파일 선택 시 UI가 Tag로 넘치지 않도록 폴더 단위로 축약

**수정 내용:**
- `groupAnnotationFilesForDisplay()` 함수 — 같은 폴더 내 파일이 `FOLDER_COLLAPSE_THRESHOLD`(5)를 넘으면 폴더 단위로 축약
- 축약 표시: `labels/ (8,543개 파일)` 형태의 골드색 Tag
- 폴더 Tag 삭제 시 해당 폴더의 모든 파일 일괄 제거

**관련 파일:** `frontend/src/components/dataset/DatasetRegisterModal.tsx`

---

### 이슈 E: 어노테이션 파일 저장 경로 분리

**목표:** 어노테이션 파일을 이미지와 같은 레벨이 아닌 `annotations/` 하위 디렉토리에 저장

**수정 내용:**
- `LocalStorageClient.copy_annotation_files()` — 대상 경로에 `annotations/` 추가
- `get_annotation_path()` → `get_annotations_dir()`로 이름 변경
- `validate_structure()` — `annotations_dir` 존재 및 파일 수 검증
- `config.ini`에 `annotations_dirname = annotations` 설정 추가

**관련 파일:**
- `backend/app/core/storage.py`
- `backend/app/core/config.py`
- `config.ini`

---

## 부가 수정 (이슈 1~3과 함께 처리)

| 항목 | 내용 |
|------|------|
| Axios 타임아웃 | `register()` 호출에 타임아웃 파라미터 추가 (`.env`에서 읽음) |
| 백엔드 로깅 | 라우터(4개), 서비스, 스토리지, DB 세션에 structlog INFO 로그 추가 |
| 파일 브라우저 페이지네이션 | `ServerFileBrowser.tsx` Table에 `pagination={{ pageSize: 50 }}` |

---

## 커밋 이력

```
3d4b0fa fix: 데이터셋 등록 플로우 오류 수정 및 UX 개선 (이슈 1~3 + 부가 수정)
d2d8cc6 fix: 새 그룹명 입력 폼 — 드롭다운 "신규 생성" 선택 시에만 활성화
db2f3ec feat: ServerFileBrowser 경로 직접 입력 기능 추가 (이슈 4)
d03aa42 feat: 어노테이션 포맷 사전 검증 기능 추가 (이슈 5)
96d3ce9 feat: 이슈 C/D/E/6 — 전체 파일 선택, 폴더 축약 표시, annotations/ 경로 분리, 복사 중 안내
c443309 feat: 등록 시 자동 생성 버전 미리보기 표시 (이슈 B)
```
