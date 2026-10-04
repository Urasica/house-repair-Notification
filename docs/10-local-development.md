# 로컬 실행과 개발 검증

작성: 2026-10-03 · 기준: [개발 규칙](09-development-standards.md) · 상태: [진행표](../progress/README.md)

이 문서는 M01~M09 코드·자료와 로컬 검증 기록이다. DELETED·REQUEST_DELETED는 M06 API/DB와 M07 화면에 구현했다. 실제 목록은 M08A에서 게시했고 원문은 M08에서 파일로 정리했다. M09에서 실제 RAG 검색을 설문에 연결했다. ChatHistory·생성 답변은 [진행표](../progress/README.md)의 M10에서 연결한다.

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

http://localhost:8080에서 홈 화면을 확인한다. /health/live는 API 프로세스, /health/ready는 DB·마이그레이션·초기 중단 요청 정리와 목록/지식 준비 상태를 확인한다. 새 DB에 목록을 게시하기 전에는 catalogReady=false, ragReady=false이며 /api/v1/catalog는 503 CATALOG_NOT_READY다. M08A 목록과 M09 지식을 게시한 현재 로컬 DB는 catalogReady=true, ragReady=true이며 실제 목록을 반환한다. 예시 환경의 OpenAI는 기본 OFF이고 시작에 키가 필요하지 않다. 현재 로컬 실행은 키가 있는 .env와 OPENAI_ENABLED=true를 사용한다. 목록이 없어도 web과 API는 실행된다. DB 장애 시 ready와 catalog는 503 SERVICE_UNAVAILABLE, live는 200이다.

web·api·db 3개 서비스만 상시 실행한다. API는 1개 워커다. 외부 연결은 로컬 web 포트에만 허용하며 API·DB 포트는 호스트에 공개하지 않는다. PostgreSQL 18 데이터는 /var/lib/postgresql의 named volume에 유지한다.

.env.example의 비밀번호는 로컬 시험 전용 공개 값이다. 개인 설정은 .env에 복사해 변경한 뒤 --env-file .env를 사용한다. 실제 비밀은 Git에 넣지 않는다. 최초 DB 초기화 시 postgres 관리자와 DML 전용 앱 계정을 분리한다. compose.admin.yaml은 같은 API 이미지의 일회성 관리 명령에만 사용하며, up에 포함하지 않는다. API 런타임에는 관리자 URL을 주입하지 않는다.

기존 DB의 계정 비밀번호는 .env만 수정해도 바뀌지 않는다. 데이터 보존이 필요하면 SQL로 계정 비밀번호와 설정을 함께 변경한다. down은 컨테이너만 중단하며 down -v는 데이터를 삭제하므로 일반 종료에는 사용하지 않는다.

```sh
docker compose --env-file .env.example logs --tail 100 api web
docker compose --env-file .env.example down
```

기본 Docker context에 접근할 수 없는 Windows 환경에서는 명령에 --config .cache/docker -H npipe:////./pipe/dockerDesktopLinuxEngine을 docker 바로 뒤에 지정할 수 있다. .cache/docker에는 빈 개발 전용 설정만 두고 사용자 자격 증명 파일을 복사하지 않는다.

## 2. 직접 개발

Node 22.22.2 이상 23 미만, Python 3.12를 사용한다. 화면 시험용 jsdom의 Node 요구 조건을 함께 적용하며 Docker는 Node 22.23.1을 사용한다. Windows에서는 python 대신 설치된 Python 실행 경로 또는 py -3.12를 사용할 수 있다.

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

macOS/Linux의 venv 경로는 .venv/bin/python이다. M09 기준 기본 pytest는 DB 시험 69건을 skip하고 독립 시험 132건을 실행한다. 실제 DB 시험은 다음 절차로 별도 실행해야 한다.

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

M09 기준 백엔드 201건은 실제 원문/청크·임베딩·검색·게시/철회 검증 및 계약·설정·오류·잠금·실제 DB 관계/제약·요청 재생/실패·트랜잭션·재시작 정리·벡터/자료 적격성·가입/인증/만료/CSRF/소유권·목록 게시/불변성/분기/선택 정리 시험을 포함한다. M08A 프론트는 인증·저장소·설문/분기·위험 선택·응답 복구·계정 전환·이력/삭제·오류/접근성·초점 복원을 포함해 Vitest 35건과 타입/린트/빌드를 검증한다. jsdom은 개발 시험 의존성이며 서비스에 브라우저 서버를 추가하지 않는다. test 빌드 단계는 같은 API의 일회성 시험 명령용이며 상시 서비스를 추가하지 않는다. upgrade → downgrade base → upgrade → upgrade 반복은 비어 있는 시험 DB에서만 검증한다. 데이터를 가진 개발/운영 DB에는 downgrade base를 실행하지 않는다.

빈 목록 상태의 web·프록시·API 확인은 저장소 루트에서 Python으로 scripts/smoke_api.py를 실행한다. --url http://127.0.0.1:8080도 지원한다. --database-unavailable은 DB가 중단된 상태의 기대 응답을 검사할 뿐 직접 DB를 중단하지 않는다.

## 4. 계약과 코드 연결

backend/app/db/models.py는 12개 테이블, alembic/versions/0001_m03_initial_business_and_knowledge_schema.py는 최초 변경 이력이다. M05의 0002_m05_immutable_catalogs.py는 게시된 카탈로그의 UPDATE/DELETE를 차단하는 trigger를 추가한다. M06의 0003_m06_deleted_requests.py는 DELETED 요청의 본문 없는 종료 상태를 추가한다. M09의 0004_m09_knowledge_immutability.py는 게시된 지식 묶음·원문·청크 불변성과 철회 경계를 추가한다. 현재 MIGRATION_HEAD는 0004_m09다. DB 스키마를 바꾸면 새 migration을 추가하고 readiness의 MIGRATION_HEAD를 함께 갱신한다. 앱 시작 시 migration을 자동 실행하지 않는다.

Database는 한 연결 풀과 요청별 AsyncSession을 제공한다. transaction은 호출자 쓰기를 한 번에 확정한다. RequestRepository는 스스로 commit하지 않으며 완료 결과·정제 질문·완료 상태를 같은 트랜잭션에 넣을 수 있다. M04에서 계정/익명 권한·소유권 검사 함수를 구현했다. M06에서 isCurrent·revision·상담/설문/이력/삭제 API를 연결했다.

로컬 `/login`에서 가입/로그인할 수 있고 `/api/v1/auth/me`는 미로그인일 때 user=null을 반환한다. 회원 경로는 미로그인 요청을 서버에서도 401로 차단한다. M06 이력 API와 M07 화면을 연결했고 챗봇은 M10에서 연결한다. 운영 쿠키는 Secure이며 로컬 HTTP에서만 개발 쿠키를 사용한다. API의 프록시 헤더 신뢰 설정은 API 포트 비공개·Caddy 내부 연결을 전제로 한다.

ConsultationLocks는 단일 프로세스의 같은 상담 변경을 즉시 409로 차단하고 다른 상담은 동시에 처리한다. 중단 요청 정리는 이전 프로세스가 완전히 종료된 뒤 시작 때 한 번 실행하며 readiness 조회가 활성 요청을 실패로 바꾸지 않는다. DB 장애 중 활성 변경 취소·재시도 제어는 실제 변경 서비스와 함께 M06에서 연결한다.

API의 knowledgeReleaseId는 knowledge_sets.id에 대응한다. ragReady는 OpenAI 설정·검토 완료 manifest·호환 게시본·유효 승인 문서·임베딩 해시를 확인한다. 이 상태는 자료 준비 점검이며 실제 검색·생성 품질 검증은 M09/M10의 완료 기준이다.

계약 변경 시 backend에서 python -m scripts.export_openapi를 실행한 뒤 frontend에서 npm run types를 실행한다. schemas/openapi.json과 src/api/generated/schema.ts를 함께 커밋한다. 생성 파일은 직접 편집하지 않는다. 후속 DTO도 OpenAPI components에 포함하지만 아직 구현하지 않은 API 경로는 노출하지 않는다. 카탈로그 입력 형식은 python -m scripts.export_catalog_schema로 갱신한다.

M05의 카탈로그 명령·검토·게시본 불변성·질문 정책은 [카탈로그 안내](11-catalog-publication.md)를 따른다. 최신 버전 확인·QuestionsResponse·설문 정책을 M06 상담 API에 연결했다. 실제 목록 작성·검토·게시와 통합 검증은 M08A에서 완료했다. 브라우저에서 로컬 로그인 화면·비회원 이력 접근 제한·홈의 준비 중 상태를 확인했다.

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

운영 변경은 먼저 백업을 확인한 뒤 수행한다. OpenAI 연동은 키·모델·사용량 설정과 검토 완료 자료를 확인한 뒤 켠다. 현재 로컬에는 M08 정리 원문·M08A 게시 목록·M09 게시 지식이 있으며 실제 OpenAI 임베딩과 설문 검색을 검증했다. 생성 API 호출은 M10에서 연결한다. 운영 서버 배포는 M12다.

## 6. 이미지 기준과 확인 기록

Python 3.12.14-slim, Node 22.23.1-alpine, Caddy 2.11.4-alpine, pgvector/pgvector 0.8.7-pg18-trixie를 정확 태그로 지정했다. [Python](https://hub.docker.com/_/python), [Node](https://hub.docker.com/_/node), [Caddy](https://hub.docker.com/_/caddy), [pgvector](https://hub.docker.com/r/pgvector/pgvector)의 공식 이미지/프로젝트 이미지를 사용한다.

2026-10-03 실제 빌드에서 확인한 registry manifest digest다. 태그가 갱신될 수 있으므로 운영 출시 때 다시 확인하고 사용 이미지를 고정한다.

| 이미지 | 확인 digest |
| --- | --- |
| python:3.12.14-slim | sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f |
| node:22.23.1-alpine | sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 |
| caddy:2.11.4-alpine | sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b |
| pgvector/pgvector:0.8.7-pg18-trixie | sha256:9d9c930220cb9bf2f956d10a8f909cf9973d9672ca0278aef2c1e6facccad2e0 |

## 7. M06 상담·저장·삭제 검증

POST /api/v1/sessions는 게시된 최신 catalogVersion만 허용하며 실제 목록이 없으면 상담 시작을 차단한다. 익명은 응답의 sessionToken을 Bearer로 사용하고 회원은 쿠키·CSRF·Origin을 사용한다. 맥락 저장은 expectedRevision이 일치해야 하며 실제 변경에만 revision을 증가시킨다.

M06 당시 설문은 검토된 카탈로그 정책으로 위험·범위·입력 상태를 확인하고 운영 근거가 연결되지 않았으면 연락처 없는 직접 문의 템플릿을 반환한다. 당시에는 OpenAI/외부 검색을 호출하지 않았다. 현재 M09는 검토된 라벨의 질문 임베딩과 내부 검색을 수행한다. 결과·정제 질문·완료 요청을 한 트랜잭션에서 저장한다. 장기 질문에는 코드·라벨만 저장하고 자유 입력 원문을 복사하지 않는다.

완료된 같은 요청은 200으로 재생하고 새 결과/질문을 만들지 않는다. 결과 삭제는 연결 질문과 재생 본문을 삭제하고 DELETED를 유지한다. 같은 ID의 재전송은 입력 해시 비교 전에 410이다. 질문만 삭제한 경우 결과 재생이 질문을 복원하지 않는다. 회원 상담 종료는 결과/질문을 보존하며 익명은 원본 결과를 지우고 정제 질문은 eraseRecords=true일 때만 함께 삭제한다.

계정 이력은 상담 만료·종료 후에도 본인에게 조회되며 isCurrent=false로 표시한다. 실패/시간 초과/취소는 가능한 짧은 정리 트랜잭션에서 FAILED로 기록하고 늦은 완료는 저장하지 않는다. DB 장애를 감지하면 활성 변경을 취소하고 새 변경을 막는다. 활성 변경이 모두 끝난 뒤 DB 복구 시 PROCESSING을 정리한다. 단일 API 워커를 유지한다.

전용 시험 DB에서 M06 정책·소유권·회원 이력/페이지·원자 저장·재생·삭제/종료·취소/시간 초과/늦은 완료를 검증했다. 실제 목록 통합 검증은 M08A에서 완료했다.

## 8. M07 화면·복구 검증

목록이 게시되면 홈에서 새 상담을 생성하고 /select → /survey → /result/:resultId로 진행한다. 현재 로컬 개발 DB에는 M08A 목록이 게시되어 설문을 시작할 수 있다. 회원 이력은 /history와 /history/:resultId에서 제공하며 실제 목록 기반 결과 저장·회원 이력 연결을 M08A에서 확인했다. 회원 챗봇은 접근 제한과 준비 중 안내만 제공한다.

익명 저장소에는 상담 ID·Bearer·만료 시각, 회원은 상담 ID만 보관한다. 처리 중 평가는 requestId·expectedRevision만 보관하고 원문 입력·답·결과·CSRF·계정 토큰은 저장소에 넣지 않는다. 로그인/로그아웃·인증 만료·계정 재확인에서 신원이 바뀌면 사용자 캐시와 양쪽 상담 복구 정보를 제거한다. 진행 중 변경의 늦은 응답은 이전 화면·캐시를 복원하지 않는다.

응답 유실은 상태 조회 또는 같은 ID/입력 재전송으로 복구한다. 자동 새 평가·자동 polling은 없다. PROCESSING의 대기 시간과 변경 요청의 Retry-After/retryAfterMs를 따르고 FAILED/DELETED 뒤 새 평가는 사용자 버튼으로만 시작한다. 삭제된 요청은 캐시·처리 중 ID를 제거한다. revision 충돌에서 미저장 선택을 자동 덮어쓰지 않으며 사용자가 최신 입력을 불러와 확인한다.

합성 fixture는 frontend/src/features/survey/test-fixtures.ts와 backend/tests/fixtures에만 있고 자동 시험에서만 사용한다. 공개 목록·화면 fallback·RAG로 반입하지 않는다. DOM 시험에서 라디오/fieldset/legend·필수 확인·오류 연결·입력 길이·텍스트 이스케이프·HTTPS 출처 링크를 확인했다. 좁은 실제 브라우저에서 준비 중·회원 접근 제한·로그인과 이메일→비밀번호 Tab 이동을 확인했다. 실제 목록의 모바일/키보드 대표 흐름은 M08A에서 검증했고, 모든 목록 연결/답 옵션은 정책 시험으로 검증했다. 확대·스크린리더 인수는 M12다.

## 9. M08A 실제 목록 게시와 검증

완성 목록은 `data/catalog/m08a-20261004/catalog.json`, 출처·항목·질문 대응 및 해시는 같은 디렉터리의 `review.json`에 있다. [완료 기록](../progress/03-m08a-catalog-review.md)에 검토 범위와 적용 제한을 남겼다. 기존 합성 fixture는 게시하지 않는다.

```sh
docker compose --env-file .env.example run --rm --no-deps --volume C:/Users/dlqnf/Desktop/teamproject/data/catalog/m08a-20261004/catalog.json:/input/catalog.json:ro api python -m app.commands.catalog validate /input/catalog.json
docker compose --env-file .env.example run --rm --no-deps --volume C:/Users/dlqnf/Desktop/teamproject/data/catalog/m08a-20261004/catalog.json:/input/catalog.json:ro api python -m app.commands.catalog publish /input/catalog.json
backend/.venv/Scripts/python.exe scripts/smoke_api.py --catalog-version m08a-20261004-v2 --rag-ready
```

smoke의 --rag-ready는 M09까지 게시한 현재 로컬 상태 기준이며 목록만 게시한 새 환경에서는 생략한다. 다른 체크아웃에서는 마운트 원본을 그 환경의 절대 경로로 바꾼다. `compose.test.yaml`은 실제 카탈로그를 시험 컨테이너의 `/data/catalog`에 읽기 전용 마운트한다. 과거/최신 검증용 별도 버전은 전용 시험 DB 트랜잭션 안에서만 만들고 되돌린다. 로컬 개발 DB에는 v1과 외부 공간 연결을 보완한 최신 v2가 있고 두 버전의 조회를 확인했다.

M08A에서 `survey-v2`로 결과 생성 규칙을 갱신했다. 위험/범위 밖 결과는 미응답 설문 재개를 요청하지 않으며 입력 부족 확인 질문은 중복 제거한다. 기존 결과는 스냅샷으로 보존하고 이전 엔진 결과의 isCurrent=false 처리를 유지한다. 모바일 설문 저장 후 초점 복원과 보조 링크 색 대비도 수정했다. 검증용 계정·상담은 로컬 개발 데이터이며 실제 사용자 정보를 사용하지 않았다.

## 10. M09 실제 지식 게시와 설문 검색

49개 청크를 text-embedding-3-large·1536차원으로 임베딩하고 카탈로그 태그/명시적 조문 기준 53건 실제 평가 후 로컬 개발 DB에 게시했다. 최종 릴리스는 ebf3dec4-3905-5932-b29e-9651f438a937, 엔진은 survey-v3다. 일반 설문은 LH 운영 근거가 없어 RELATED 법령 인용·NEED_CONFIRMATION을 유지한다. 저장 전 철회·기한·필수 별표/문맥을 재확인한다.

[관리 명령·검색 계약](12-knowledge-publication.md)과 [M09 완료 기록](../progress/04-m09-knowledge-review.md)에 원문 지문·게시 시각·평가·실제 API 증거를 기록했다. M09는 컴퓨터 유즈 없이 CLI·DB·API로 검증했다. GPT 생성과 회원 챗봇 본문은 M10에서 구현한다.
