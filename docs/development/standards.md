# 개발 기준과 입력 형식

[전체 설계 안내](../README.md)

## 1. 공통 구현 기준

구현된 지원 주택·결과 상태·오류 코드는 backend/app/domain/constants.py에 정의한다. DTO는 backend/app/schemas/contracts.py와 catalog.py에 정의하고 Pydantic 검증·camelCase·UTC·알 수 없는 입력 거부를 공통으로 적용한다. 프론트 타입은 OpenAPI에서 생성하며 직접 별도 정의해 복제하지 않는다. 확정 계약은 책임별 설계를 따른다. 코드와 설계의 모순은 별도 검토 기록에 남기고, 이 문서 정리만으로 어느 쪽도 임의 변경하지 않는다.

설문·현재 결과는 비회원과 회원, 챗봇·과거 이력은 회원에게만 제공한다. 답변·문의 문구의 연락처 금지와 내부 근거 우선 정책은 유지한다.

## 2. 카탈로그 입력

완성 목록은 schemas/catalog.schema.json의 JSON Schema와 CatalogDefinition의 연결 검증을 따른다. version, review, housingTypes, rooms, facilities, symptoms, questions를 사용한다. ID는 안정적인 문자열이며 시설물은 roomIds, 증상은 facilityIds, 질문은 symptomIds로 연결한다.

질문은 singleChoice이며 options·required·interruptValues·order·conditions를 포함한다. 조건은 housingType·roomId·facilityId·symptomId 또는 answers.질문ID의 equals/in만 허용한다. COMPLETE_VERIFIED 검토에는 검토자·검토일과 비어 있지 않은 목록이 필요하다. 목록은 사용자 지시에 따라 원문 기반으로 작성·검토하고 명시적 게시 명령으로 반영한다.

5개 주택 유형·고유한 옵션/연결·실제 조건 값·앞선 질문 참조를 검증한다. 게시본은 DB trigger로 수정·삭제를 차단하며 동일 게시 재전송은 기존 시각을 유지한다. 상세 형식은 [카탈로그 설계](../data/catalog.md)를 따른다.

backend/tests/fixtures/catalog.test.json과 frontend/src/features/survey/test-fixtures.ts는 시험 전용 합성 데이터다. 공개 목록·개발 홈·운영 목록에 게시하지 않는다. 기존 예시 증상은 복사하지 않는다.

원문은 제6조의2·제7~45조·실제 별표 2·3·4 전체를 먼저 정리하고 coverage·누락·시행일·조건·각주·검토·해시를 기록한다. 실제 추출 지시와 전체 정리 검토 전에는 청킹·임베딩하지 않는다. 완전성 검토와 법률·운영 적용 승인은 구분한다.

## 3. 실행 설정과 버전

.env.example은 로컬 Docker의 공개 개발 기본값이며 실제 비밀은 .env에서만 관리한다. APP_ENV는 development/test/tunnel_test/production, OPENAI_ENABLED는 예시 환경에서 기본 false다. 생성 모델은 gpt-5.4-mini, 임베딩 text-embedding-3-large·1536차원을 사용한다. 사용자 지정에 따라 임베딩 총비용 상한은 두지 않고 요청별 입력·시간 한도는 유지한다. 운영은 별도 DB 비밀번호·HTTPS origin을 요구한다. 질문·회원 결과는 3~5년 기본 5년, 상담·인증 24시간, 단기 기록 정리 유예 7일, 로그·백업 14일, 삭제 기록 15일이다.

Python 3.12, Node 22 계열을 기준으로 한다. FastAPI 0.142.2·Pydantic 2.13.5·SQLAlchemy 2.1.2·Psycopg 3.3.6·Alembic 1.20.0·pgvector Python 0.5.0을 선택했다. 프론트는 React 19.3.0·Vite 8.3.2·TypeScript 5.9.3을 사용한다. OpenAPI 타입 생성 도구의 TypeScript 5.x 호환 범위와 린트 도구의 호환 범위를 함께 만족하는 버전을 선택했다.

직접 의존성은 backend/requirements.in, 시험 의존성은 requirements-dev.in에 기록하고 설치된 전이 의존성을 requirements.txt/requirements-dev.txt에 고정한다. 프론트는 package.json의 정확 버전과 package-lock.json으로 고정한다. 이미지 버전·digest는 Docker 구성에 고정하고 실제 빌드 결과는 진행 기록에 남긴다. 실행 명령은 [로컬 개발](local.md)과 [배포](../operations/deployment.md)를 따른다.

구현 방식은 [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/), [Vite 요구 조건](https://vite.dev/guide/), [SQLAlchemy Psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg), [pgvector](https://github.com/pgvector/pgvector)를 참고한다.

## 4. 작업·검증·기록

산출물과 검증을 작업 단위로 정리한다. 진행 기록을 보관하는 작업 환경에서는 로컬 `progress/README.md`에 따라 작업판과 증거를 갱신하고 `python scripts/check_progress.py --write`로 색인을 검사한다. 진행 기록은 Git에서 제외한다.

Python은 Ruff·pytest, 프론트는 타입 검사·ESLint·Vitest·빌드를 사용한다. DB 제약·삭제·벡터 검증은 실제 PostgreSQL + pgvector에서 실행하며 SQLite로 대체하지 않는다.

외부 입력의 확인 상태와 운영 인수 항목은 로컬 `progress/current-status.md`에서 관리한다.

## 5. 계약과 스키마 변경

DB 변경은 최초 migration을 고치지 않고 새 migration과 MIGRATION_HEAD 갱신으로 반영한다. DTO·enum 변경 시 OpenAPI와 생성 프론트 타입을 함께 갱신한다. 계약·생성 타입·migration·화면·회귀 검증을 함께 확인한다. 설계 수정만으로 실행 검증 건수나 단계 완료 여부를 갱신하지 않는다.

## 6. 설계 문서 관리

`docs/`는 책임별 폴더에 현재 확정된 설계·계약·절차만 둔다. 책임과 진입점은 [설계 안내](../README.md)를 따른다. 규칙 변경은 해당 책임 문서의 본문을 직접 고쳐 하나의 최종 기준으로 유지하며, 별도의 변경 요구·이전안·단계별 완료 표를 덧붙이지 않는다. 다른 책임 문서는 세부 규칙을 복제하지 않고 정식 문서를 연결한다.

변경 이유·이전 동작·검증 수치·환경별 관측은 `progress/records/`에 남기고 현재 판단은 `progress/current-status.md`에서만 관리한다. 문서 이동 시 저장소 전체의 상대 링크·절 링크·경로 참조를 갱신하고 문서 검사기를 실행한다. 구현과 설계의 차이는 증거와 함께 진행 기록에 보고한다. 모순 보고만 요청된 문서 정리에서는 코드나 설계 계약을 임의로 일치시키지 않는다.
