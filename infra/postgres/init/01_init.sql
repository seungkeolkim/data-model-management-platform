-- =============================================================================
-- PostgreSQL 초기화 스크립트
-- docker-entrypoint-initdb.d/ 에 위치 → 컨테이너 최초 시작 시 자동 실행
-- =============================================================================

-- uuid-ossp 확장 활성화 (UUID 생성 함수)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pgcrypto 확장 (선택적, 암호화 기능)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 타임존 설정
SET timezone = 'UTC';

-- =============================================================================
-- Celery 관련 테이블 생성
-- celery[sqlalchemy] 브로커/백엔드 사용 시 필요
-- 실제 테이블 생성은 Celery 첫 실행 시 자동으로 처리되지만
-- 권한 설정을 미리 해둔다.
-- =============================================================================

-- mlplatform 사용자에게 데이터베이스 전체 권한 부여
GRANT ALL PRIVILEGES ON DATABASE mlplatform TO mlplatform;

-- 스키마 권한
GRANT ALL ON SCHEMA public TO mlplatform;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO mlplatform;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO mlplatform;

-- 기본 권한 설정 (향후 생성될 테이블에도 자동 적용)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON TABLES TO mlplatform;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON SEQUENCES TO mlplatform;

-- =============================================================================
-- 로그 출력
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE 'ML Platform DB initialized: extensions enabled, permissions granted';
END $$;
