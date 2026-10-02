# 개발 기준과 입력 형식

작성: 2026-10-03 · 적용: M01~M03 및 후속 구현

기준: [전체 안내](README.md) · 진행: [MVP 작업](../progress/README.md)

## 1. 공통 구현 기준

지원 주택·결과 상태·오류 코드는 backend/app/domain/constants.py를 기준으로 한다. DTO는 backend/app/schemas/contracts.py와 catalog.py에 정의하고 Pydantic 검증·camelCase·UTC·알 수 없는 입력 거부를 공통으로 적용한다. 프론트 타입은 OpenAPI에서 생성하며 직접 별도 정의해 복제하지 않는다.

설문·현재 결과는 비회원과 회원, 챗봇·과거 이력은 회원에게만 제공한다. M01~M03에서는 계약·실행 환경·DB/API 기반을 구현하고 계정/설문 기능은 M04 이후 연결한다. 답변·문의 문구의 연락처 금지와 내부 근거 우선 정책은 유지한다.

## 2. 카탈로그 입력

완성 목록은 schemas/catalog.schema.json의 JSON Schema와 CatalogDefinition의 연결 검증을 따른다. version, review, housingTypes, rooms, facilities, symptoms, questions를 사용한다. ID는 안정적인 문자열이며 시설물은 roomIds, 증상은 facilityIds, 질문은 symptomIds로 연결한다.

질문은 singleChoice이며 options·required·interruptValues·order·conditions를 포함한다. 조건은 housingType·roomId·facilityId·symptomId 또는 answers.질문ID의 equals/in만 허용한다. COMPLETE_VERIFIED 검토에는 검토자·검토일과 비어 있지 않은 목록이 필요하다. 실제 목록은 아직 제공되지 않았으며 자동 게시하지 않는다.

backend/tests/fixtures/catalog.test.json은 구조 검증용 시험 데이터다. 공개 목록·개발 홈·운영 목록에 게시하지 않는다. 기존 예시 증상은 복사하지 않는다.

원문은 제6조의2·제7~45조·실제 별표 2 전체를 먼저 정리하고 coverage·누락·시행일·조건·각주·검토·해시를 기록한다. 실제 추출 지시와 전체 정리 검토 전에는 청킹·임베딩하지 않는다.

## 3. 실행 설정과 버전

.env.example은 로컬 Docker의 공개 개발 기본값이며 실제 비밀은 .env에서만 관리한다. APP_ENV는 development/test/production, OPENAI_ENABLED는 기본 false다. 운영은 별도 DB 비밀번호·HTTPS origin을 요구한다. 질문·회원 결과는 3~5년 기본 5년, 상담·인증 24시간, 단기 기록 정리 유예 7일, 로그·백업 14일, 삭제 기록 15일이다.

Python 3.12, Node 22 계열을 기준으로 한다. FastAPI 0.142.2·Pydantic 2.13.5·SQLAlchemy 2.1.2·Psycopg 3.3.6·Alembic 1.20.0·pgvector Python 0.5.0을 선택했다. 프론트는 React 19.3.0·Vite 8.3.2·TypeScript 5.9.3을 사용한다. OpenAPI 타입 생성 도구의 TypeScript 5.x 호환 범위와 린트 도구의 호환 범위를 함께 만족하는 버전을 선택했다.

직접 의존성은 backend/requirements.in, 시험 의존성은 requirements-dev.in에 기록하고 설치된 전이 의존성을 requirements.txt/requirements-dev.txt에 고정한다. 프론트는 package.json의 정확 버전과 package-lock.json으로 고정한다. 이미지 버전·검증 digest와 실행 명령은 실행 안내에 기록한다.

버전은 공식 npm/PyPI 저장소에서 확인했다. 구현 방식은 [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/), [Vite 요구 조건](https://vite.dev/guide/), [SQLAlchemy Psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg), [pgvector](https://github.com/pgvector/pgvector)를 참고한다.

## 4. 작업·검증·기록

작업 단위마다 산출물·필요한 검증·progress 상태를 함께 커밋한다. Python은 Ruff·pytest, 프론트는 타입 검사·ESLint·Vitest·빌드를 사용한다. DB 제약·삭제·벡터 검증은 실제 PostgreSQL + pgvector에서 실행하며 SQLite로 대체하지 않는다.

현재 대기 항목은 완성 목록·실제 원문 추출 지시·검토 완료 원문·운영 OpenAI 설정·배포 대상이다. M01~M03의 개발 환경에서는 OpenAI를 호출하지 않는다.
