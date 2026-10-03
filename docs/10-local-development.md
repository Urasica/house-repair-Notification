# 로컬 실행과 개발 검증

작성: 2026-10-03 · 기준: [개발 규칙](09-development-standards.md) · 상태: [진행표](../progress/README.md)

이 문서의 실행·시험 기록은 M01~M03 기반에 대한 것이다. 이후 계획 점검에서 확정한 DELETED·REQUEST_DELETED·ChatHistory는 아직 구현하지 않았으며 [후속 반영 표](09-development-standards.md#5-계획-정합성-개정과-후속-반영)의 단계에서 코드·migration·생성 타입과 검증을 갱신한다.

## 1. Docker 실행

Docker Desktop의 Linux 컨테이너 엔진과 Docker Compose를 실행한다. 저장소 루트에서 이미지를 만든 뒤 DB를 준비하고 마이그레이션을 한 번 적용한다. 기존 API가 있으면 먼저 완전히 중단한다.

```sh
docker compose --env-file .env.example build api web
docker compose --env-file .env.example stop api
docker compose --env-file .env.example up -d --wait db
docker compose --env-file .env.example -f compose.yaml -f compose.admin.yaml run --rm --no-deps api python -m alembic upgrade head
docker compose --env-file .env.example up -d --no-build
docker compose --env-file .env.example ps
```

http://localhost:8080에서 준비 중 화면을 확인한다. /health/live는 API 프로세스, /health/ready는 DB·마이그레이션·초기 중단 요청 정리와 목록/지식 준비 상태를 확인한다. 완성 목록이 없으므로 catalogReady=false, ragReady=false이며 /api/v1/catalog는 503 CATALOG_NOT_READY다. OpenAI는 기본 OFF이고 시작에 키가 필요하지 않다. 목록이 없어도 web과 API는 실행된다. DB 장애 시 ready와 catalog는 503 SERVICE_UNAVAILABLE, live는 200이다.

web·api·db 3개 서비스만 상시 실행한다. API는 1개 워커다. 외부 연결은 로컬 web 포트에만 허용하며 API·DB 포트는 호스트에 공개하지 않는다. PostgreSQL 18 데이터는 /var/lib/postgresql의 named volume에 유지한다.

.env.example의 비밀번호는 로컬 시험 전용 공개 값이다. 개인 설정은 .env에 복사해 변경한 뒤 --env-file .env를 사용한다. 실제 비밀은 Git에 넣지 않는다. 최초 DB 초기화 시 postgres 관리자와 DML 전용 앱 계정을 분리한다. compose.admin.yaml은 같은 API 이미지의 일회성 관리 명령에만 사용하며, up에 포함하지 않는다. API 런타임에는 관리자 URL을 주입하지 않는다.

기존 DB의 계정 비밀번호는 .env만 수정해도 바뀌지 않는다. 데이터 보존이 필요하면 SQL로 계정 비밀번호와 설정을 함께 변경한다. down은 컨테이너만 중단하며 down -v는 데이터를 삭제하므로 일반 종료에는 사용하지 않는다.

```sh
docker compose --env-file .env.example logs --tail 100 api web
docker compose --env-file .env.example down
```

기본 Docker context에 접근할 수 없는 Windows 환경에서는 명령에 --config .cache/docker -H npipe:////./pipe/dockerDesktopLinuxEngine을 docker 바로 뒤에 지정할 수 있다. .cache/docker에는 빈 개발 전용 설정만 두고 사용자 자격 증명 파일을 복사하지 않는다.

## 2. 직접 개발

Node 22.12 이상 23 미만, Python 3.12를 사용한다. Windows에서는 python 대신 설치된 Python 실행 경로 또는 py -3.12를 사용할 수 있다.

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m pytest
.venv/Scripts/python -m scripts.export_openapi --check
cd ../frontend
npm ci
npm run types -- --check
npm run typecheck
npm run lint
npm test
npm run build
npm run dev
```

macOS/Linux의 venv 경로는 .venv/bin/python이다. M04 기준 기본 pytest는 DB 시험 27건을 skip하고 독립 시험 27건을 실행한다. 실제 DB 시험은 다음 절차로 별도 실행해야 한다.

프론트 개발 서버는 /api·/health를 127.0.0.1:8000에 프록시한다. API는 backend에서 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1로 실행한다. 기본 Compose의 DB 포트는 비공개이므로 실제 DB 검증은 컨테이너 안에서 실행한다. 호스트 API 개발 시 별도 개발 DB 연결 URL을 설정한다.

직접 의존성 변경 시 설치 후 저장소 루트에서 backend의 Python으로 scripts/lock_python.py를 실행한다. 프론트는 package.json과 package-lock.json을 함께 갱신한다. Docker 빌드의 npm ci는 설치만 수행하고 보안 점검은 개발 환경의 npm audit로 별도 수행한다.

## 3. 실제 DB 시험

개발 DB와 분리된 Compose 프로젝트·DB를 사용한다. 아래 --env-file 두 개와 -p repair-guide-test를 모두 유지한다. .env.test.example의 DB 이름은 repair_guide_test이며 시험 코드도 APP_ENV=test·RUN_DB_TESTS=1·DB 이름을 확인한다. 합성 자료는 이 DB의 시험 트랜잭션에만 넣고 종료 시 되돌린다.

```sh
docker compose -p repair-guide-test --env-file .env.example --env-file .env.test.example -f compose.yaml -f compose.test.yaml up -d --wait db
docker compose -p repair-guide-test --env-file .env.example --env-file .env.test.example -f compose.yaml -f compose.test.yaml build api
docker compose -p repair-guide-test --env-file .env.example --env-file .env.test.example -f compose.yaml -f compose.test.yaml -f compose.admin.yaml run --rm --no-deps api python -m alembic upgrade head
docker compose -p repair-guide-test --env-file .env.example --env-file .env.test.example -f compose.yaml -f compose.test.yaml run --rm --no-deps api python -m pytest -q -p no:cacheprovider
docker compose -p repair-guide-test --env-file .env.example --env-file .env.test.example -f compose.yaml -f compose.test.yaml -f compose.admin.yaml run --rm --no-deps api python -m alembic check
docker compose -p repair-guide-test --env-file .env.example --env-file .env.test.example -f compose.yaml -f compose.test.yaml down
```

M04 기준 54건은 계약·설정·오류·잠금·실제 DB 관계/제약·요청 재생/실패·트랜잭션·재시작 정리·벡터/자료 적격성·가입/인증/만료/CSRF/소유권 시험을 포함한다. 프론트는 인증·캐시·회원 경로를 포함해 Vitest 8건과 타입/린트/빌드를 검증한다. test 빌드 단계는 같은 API의 일회성 시험 명령용이며 상시 서비스를 추가하지 않는다. upgrade → downgrade base → upgrade → upgrade 반복은 비어 있는 시험 DB에서만 검증한다. 데이터를 가진 개발/운영 DB에는 downgrade base를 실행하지 않는다.

빈 목록 상태의 web·프록시·API 확인은 저장소 루트에서 Python으로 scripts/smoke_api.py를 실행한다. --url http://127.0.0.1:8080도 지원한다. --database-unavailable은 DB가 중단된 상태의 기대 응답을 검사할 뿐 직접 DB를 중단하지 않는다.

## 4. 계약과 코드 연결

backend/app/db/models.py는 12개 테이블, alembic/versions/0001_m03_initial_business_and_knowledge_schema.py는 최초 변경 이력이다. DB 스키마를 바꾸면 새 migration을 추가하고 readiness의 MIGRATION_HEAD를 함께 갱신한다. 앱 시작 시 migration을 자동 실행하지 않는다.

Database는 한 연결 풀과 요청별 AsyncSession을 제공한다. transaction은 호출자 쓰기를 한 번에 확정한다. RequestRepository는 스스로 commit하지 않으며 완료 결과·정제 질문·완료 상태를 같은 트랜잭션에 넣을 수 있다. M04에서 계정/익명 권한·소유권 검사 함수를 구현했다. isCurrent·revision과 상담/결과 API 연결은 M06에서 구현한다.

로컬 `/login`에서 가입/로그인할 수 있고 `/api/v1/auth/me`는 미로그인일 때 user=null을 반환한다. 회원 경로는 미로그인 요청을 서버에서도 401로 차단한다. 로그인한 사용자의 챗봇·이력 본문은 후속 단계 준비 중이다. 운영 쿠키는 Secure이며 로컬 HTTP에서만 개발 쿠키를 사용한다. API의 프록시 헤더 신뢰 설정은 API 포트 비공개·Caddy 내부 연결을 전제로 한다.

ConsultationLocks는 단일 프로세스의 같은 상담 변경을 즉시 409로 차단하고 다른 상담은 동시에 처리한다. 중단 요청 정리는 이전 프로세스가 완전히 종료된 뒤 시작 때 한 번 실행하며 readiness 조회가 활성 요청을 실패로 바꾸지 않는다. DB 장애 중 활성 변경 취소·재시도 제어는 실제 변경 서비스와 함께 M06에서 연결한다.

API의 knowledgeReleaseId는 knowledge_sets.id에 대응한다. ragReady는 OpenAI 설정·검토 완료 manifest·호환 게시본·유효 승인 문서·임베딩 해시를 확인한다. 이 상태는 자료 준비 점검이며 실제 검색·생성 품질 검증은 M09/M10의 완료 기준이다.

계약 변경 시 backend에서 python -m scripts.export_openapi를 실행한 뒤 frontend에서 npm run types를 실행한다. schemas/openapi.json과 src/api/generated/schema.ts를 함께 커밋한다. 생성 파일은 직접 편집하지 않는다. 후속 DTO도 OpenAPI components에 포함하지만 아직 구현하지 않은 API 경로는 노출하지 않는다. 카탈로그 입력 형식은 python -m scripts.export_catalog_schema로 갱신한다.

## 5. 운영 설정

compose.prod.yaml은 도메인·80/443·Caddy HTTPS를 적용한다. 운영 비밀·도메인·백업 준비와 실제 배포는 M12에서 확인한다. .env에는 APP_ENV=production, 고유 앱/관리자 DB 비밀번호, HTTPS WEB_ORIGINS, PUBLIC_DOMAIN을 지정한다.

```sh
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml config --quiet
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml build api web
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml stop api
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml up -d --wait db
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml -f compose.admin.yaml run --rm --no-deps api python -m alembic upgrade head
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml up -d --no-build
```

운영 변경은 먼저 백업을 확인한 뒤 수행한다. OpenAI 연동은 키·모델·사용량 설정과 검토 완료 자료를 확인한 뒤 켠다. 현재 완성 목록·실제 원문·OpenAI 호출은 없다.

## 6. 이미지 기준과 확인 기록

Python 3.12.14-slim, Node 22.23.1-alpine, Caddy 2.11.4-alpine, pgvector/pgvector 0.8.7-pg18-trixie를 정확 태그로 지정했다. [Python](https://hub.docker.com/_/python), [Node](https://hub.docker.com/_/node), [Caddy](https://hub.docker.com/_/caddy), [pgvector](https://hub.docker.com/r/pgvector/pgvector)의 공식 이미지/프로젝트 이미지를 사용한다.

2026-10-03 실제 빌드에서 확인한 registry manifest digest다. 태그가 갱신될 수 있으므로 운영 출시 때 다시 확인하고 사용 이미지를 고정한다.

| 이미지 | 확인 digest |
| --- | --- |
| python:3.12.14-slim | sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f |
| node:22.23.1-alpine | sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 |
| caddy:2.11.4-alpine | sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b |
| pgvector/pgvector:0.8.7-pg18-trixie | sha256:9d9c930220cb9bf2f956d10a8f909cf9973d9672ca0278aef2c1e6facccad2e0 |
