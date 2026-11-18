# 로컬 실행과 개발 검증

개발 환경의 기준은 [개발 규칙](standards.md)을 따른다. Windows에서 별도 로컬 서버를 시작하는 BAT는 [Windows 실행](../operations/deployment.md#windows-실행)을 참고한다.

로컬 서비스는 `.env.ops`와 `compose.deletions.yaml`을 함께 사용한다. 아래 기본 명령은 비밀·자료가 없는 초기 환경 구성용이다. 보존할 서비스 재생성 시에는 `--env-file .env --env-file .env.ops -f compose.yaml -f compose.deletions.yaml`을 지정해 즉시 삭제 파일 내보내기를 유지한다. 기존 데이터 변경 전 백업·정리·복원과 별도 ops 이미지 설정은 [보존·백업 안내](../operations/retention-backup.md)를 따른다.

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

http://localhost:8080에서 홈 화면을 확인한다. /health/live는 API 프로세스, /health/ready는 DB·마이그레이션·초기 중단 요청 정리와 목록/지식 준비 상태를 확인한다. 새 DB에 목록을 게시하기 전에는 catalogReady=false, ragReady=false이며 /api/v1/catalog는 503 CATALOG_NOT_READY다. 예시 환경의 OpenAI는 기본 OFF이고 시작에 키가 필요하지 않다. 실제 API 검증은 비밀 .env의 키·모델·활성화 설정을 확인한 뒤 실행한다. 목록이 없어도 web과 API는 실행된다. DB 장애 시 ready와 catalog는 503 SERVICE_UNAVAILABLE, live는 200이다.

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

macOS/Linux의 venv 경로는 .venv/bin/python이다. 기본 pytest만으로 실제 DB 시험 통과를 판단하지 않는다. 실제 DB 시험은 다음 절차로 별도 실행해야 한다.

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

DB 시험은 계약·권한·관계/제약·요청 재생·삭제·게시 불변성·검색·생성 게이트를 실제 PostgreSQL + pgvector에서 검사한다. jsdom은 개발 시험 의존성이며 서비스에 브라우저 서버를 추가하지 않는다. test 빌드 단계는 같은 API의 일회성 시험 명령이다. upgrade → downgrade base → upgrade → upgrade 반복은 비어 있는 시험 DB에서만 검증한다. 데이터가 있는 개발/운영 DB에는 downgrade base를 실행하지 않는다.

빈 목록 상태의 web·프록시·API 확인은 저장소 루트에서 Python으로 scripts/smoke_api.py를 실행한다. --url http://127.0.0.1:8080도 지원한다. --database-unavailable은 DB가 중단된 상태의 기대 응답을 검사할 뿐 직접 DB를 중단하지 않는다.

## 4. 계약과 코드 연결

DB 모델은 `backend/app/db/models.py`, migration은 `backend/alembic/versions/`에서 관리한다. 스키마 변경은 새 migration을 추가하고 readiness의 MIGRATION_HEAD를 갱신한다. 앱 시작 시 migration을 자동 실행하지 않는다.

계약 변경 시 backend에서 `python -m scripts.export_openapi`를 실행한 뒤 frontend에서 `npm run types`를 실행한다. `schemas/openapi.json`과 `frontend/src/api/generated/schema.ts`를 함께 반영하며 생성 파일을 직접 편집하지 않는다. 카탈로그 입력 형식은 `python -m scripts.export_catalog_schema`로 갱신한다.

검토 자료의 반입·게시에는 [카탈로그](../data/catalog.md)와 [지식 게시](../ai/knowledge-publication.md)를 따른다. `ragReady`는 자료·설정 준비 상태이며 실제 검색·생성 품질의 통과 판정은 [검증 기준](../quality/verification.md)을 따른다.

## 5. 배포와 운영 검증

운영 설정과 릴리스 순서는 [배포 안내](../operations/deployment.md), 보존·삭제·백업·복원은 [운영 절차](../operations/retention-backup.md)에서 관리한다. 개발 `.env`를 운영 설정으로 재사용하지 않는다. 실제 빌드 digest·명령별 결과·시험 건수는 로컬 `progress/records/`에 남긴다.
