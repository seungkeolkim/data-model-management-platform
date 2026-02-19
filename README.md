# ML Platform - 데이터 관리 & 학습 자동화 플랫폼

데이터셋 관리, 파이프라인 처리, 모델 학습 자동화를 위한 통합 플랫폼.  
Phase 0(인프라) 구축 완료 상태.

---

## 빠른 시작

```bash
# 1. 환경 파일 복사 및 수정
cp .env.example .env
# .env에서 POSTGRES_PASSWORD, LOCAL_STORAGE_BASE 등 수정

# 2. 환경 검사
make check

# 3. 서비스 시작
make up

# 4. 헬스체크
make health
# 또는
curl http://localhost/health
```

접속 URL:
- **웹 UI**: http://localhost
- **API 문서**: http://localhost/api/docs
- **ReDoc**: http://localhost/api/redoc

---

## 프로젝트 구조

```
.
├── backend/                # FastAPI 백엔드
│   ├── app/
│   │   ├── api/v1/         # REST API 라우터
│   │   ├── core/           # config, database, storage
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── schemas/        # Pydantic 스키마
│   │   ├── services/       # 비즈니스 로직
│   │   ├── tasks/          # Celery 태스크
│   │   └── pipeline/       # 파이프라인 인터페이스
│   ├── migrations/         # Alembic 마이그레이션
│   └── pyproject.toml      # 의존성 (uv)
│
├── frontend/               # React 18 + TypeScript 프론트엔드
│   └── src/
│       ├── api/            # Axios API 클라이언트
│       ├── components/     # UI 컴포넌트
│       ├── pages/          # 페이지
│       ├── stores/         # Zustand 상태 관리
│       └── types/          # TypeScript 타입
│
├── infra/
│   ├── nginx/              # Nginx 설정
│   └── postgres/init/      # DB 초기화 SQL
│
├── scripts/
│   ├── setup_dev.sh        # 개발 환경 구축
│   ├── check_env.sh        # 환경 사전 검사
│   └── init_db.sh          # DB 마이그레이션 (직접 실행)
│
├── data/                   # 개발용 로컬 데이터 (NAS 대체)
│   ├── datasets/
│   └── eda/
│
├── .env.example            # 환경변수 예시
├── config.ini              # 비민감 설정 (NAS 디렉토리 규칙 등)
├── docker-compose.yml
├── environment.yml         # conda 환경 설정
└── Makefile                # 개발 편의 명령어
```

---

## 설정 파일 구조

### `.env` (민감 정보)
```ini
POSTGRES_PASSWORD=...          # DB 비밀번호
DATABASE_URL=...               # FastAPI용 async DB URL
CELERY_BROKER_URL=...          # Celery broker (PostgreSQL)
LOCAL_STORAGE_BASE=/mnt/nas/datasets  # NAS 마운트 경로 ← 변경 포인트
LOCAL_EDA_BASE=/mnt/nas/eda
SECRET_KEY=...
```

### `config.ini` (비민감 설정)
```ini
[storage]
dir_raw = raw
dir_source = source
dir_processed = processed
dir_fusion = fusion
annotation_filename = annotation.json
images_dirname = images

[pipeline]
progress_update_interval = 100
default_jpeg_quality = 95

[celery]
worker_concurrency = 4
```

---

## NAS 스토리지 구조

```
{LOCAL_STORAGE_BASE}/
├── raw/{name}/{split}/{version}/
│   ├── images/
│   └── annotation.json
├── source/...
├── processed/...
└── fusion/...

{LOCAL_EDA_BASE}/
└── {dataset_id}/
    ├── class_distribution.png
    └── eda_result.json
```

---

## 개발 명령어 (Makefile)

```bash
make up           # 서비스 시작
make down         # 서비스 중단
make logs SERVICE=backend  # 로그 확인
make migrate      # DB 마이그레이션
make db-shell     # PostgreSQL 콘솔
make health       # 헬스체크
make backend-lint # 백엔드 린트
make help         # 전체 명령어 목록
```

---

## 개발 단계 (Roadmap)

| Phase | 기능 | 상태 |
|-------|------|------|
| **Phase 0** | 인프라, DB 스키마, /health | ✅ **완료** |
| **Phase 1** | Dataset CRUD GUI | 🚧 진행 예정 |
| **Phase 2** | Manipulator + Celery 파이프라인 | ⏳ |
| **Phase 2-a** | EDA 자동화 | ⏳ |
| **Phase 2-b** | 샘플 보기 + Lineage 시각화 | ⏳ |
| **Phase 3** | 학습 실행 (2차 준비) | ⏳ |

---

## API 엔드포인트 (현재 활성)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 (DB + 스토리지 상태) |
| GET | `/api/v1/dataset-groups` | 데이터셋 그룹 목록 |
| POST | `/api/v1/dataset-groups` | 그룹 생성 |
| GET | `/api/v1/dataset-groups/{id}` | 그룹 상세 |
| PATCH | `/api/v1/dataset-groups/{id}` | 그룹 수정 |
| DELETE | `/api/v1/dataset-groups/{id}` | 그룹 삭제 |
| POST | `/api/v1/dataset-groups/validate-path` | NAS 경로 검증 |
| POST | `/api/v1/dataset-groups/register` | 데이터셋 등록 (GUI) |
| GET | `/api/v1/datasets` | Dataset 목록 |
| GET | `/api/v1/manipulators` | Manipulator 목록 |

---

## 기술 스택

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery
- **DB**: PostgreSQL 16 (메타데이터 + Celery broker/backend 통합)
- **Storage**: NAS 직접 마운트 (StorageClient 추상화로 향후 S3 전환 가능)
- **Frontend**: React 18, TypeScript, Vite, Ant Design, TanStack Query, Zustand
- **Infra**: Docker, Docker Compose, Nginx

---

## GitHub

Repository: https://github.com/seungkeolkim/data-model-management-platform
