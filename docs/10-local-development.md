# 로컬 실행과 개발 검증

작성: 2026-10-03 · 기준: [개발 규칙](09-development-standards.md) · 상태: [진행표](../progress/README.md)

## 1. Docker 실행

Docker Desktop의 Linux 컨테이너 엔진과 Docker Compose를 실행한다. 아래 명령은 저장소 루트에서 실행한다.

```sh
docker compose --env-file .env.example up -d --build
docker compose --env-file .env.example ps
```

http://localhost:8080에서 준비 중 화면을 확인한다. /health/live는 API 프로세스, /health/ready는 DB 연결과 준비 상태를 확인한다. 실제 완성 목록이 없으므로 /api/v1/catalog는 503 CATALOG_NOT_READY를 반환한다. OpenAI는 기본 OFF이며 개발 시작에 키가 필요하지 않다.

web·api·db 3개 서비스만 상시 실행한다. API는 1개 워커다. 외부 연결은 로컬 web 포트에만 허용하며 API·DB 포트는 호스트에 공개하지 않는다. PostgreSQL 18 데이터는 /var/lib/postgresql에 연결한 named volume에 유지한다.

.env.example의 비밀번호는 로컬 시험 전용 공개 값이다. 개인 설정은 .env에 복사해 변경한 뒤 --env-file .env를 사용한다. .env와 실제 키·비밀번호는 Git에 넣지 않는다.

DB 최초 생성 시 postgres 관리자와 DML 전용 앱 계정을 분리한다. 기존 DB의 계정 비밀번호는 .env만 수정해도 바뀌지 않는다. 데이터 보존이 필요하면 SQL로 계정 비밀번호를 변경하고 설정을 함께 바꾼다. down은 컨테이너만 중단하며, down -v는 저장 데이터를 삭제하므로 일반 종료에는 사용하지 않는다.

```sh
docker compose --env-file .env.example logs --tail 100 api web
docker compose --env-file .env.example down
```

## 2. 직접 개발

Node 22.12 이상 23 미만, Python 3.12를 사용한다. Windows에서는 python 대신 설치된 Python 실행 경로 또는 py -3.12를 사용할 수 있다.

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m pytest
cd ../frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm run dev
```

macOS/Linux의 venv 실행 경로는 .venv/bin/python이다. 프론트 개발 서버는 /api·/health를 127.0.0.1:8000에 프록시한다. API는 backend 디렉터리에서 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1로 실행한다. DB 포트가 공개되지 않은 기본 Compose 구성에서는 실제 DB를 이용하는 API 검증을 컨테이너 안에서 실행한다.

직접 의존성 변경 시 설치 후 저장소 루트에서 backend의 Python으로 scripts/lock_python.py를 실행한다. 프론트는 package.json과 package-lock.json을 함께 갱신하고 npm ci로 다시 검증한다.

## 3. 운영 설정

compose.prod.yaml은 도메인·80/443·Caddy HTTPS 설정을 적용하는 별도 덮어쓰기 파일이다. 로컬 검증을 운영 배포로 간주하지 않는다. 운영 비밀·도메인·백업 준비는 M12에서 확인한다.

```sh
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml config --quiet
docker compose --env-file .env -f compose.yaml -f compose.prod.yaml up -d --build
```

.env에는 APP_ENV=production, 고유 DB 비밀번호, HTTPS WEB_ORIGINS, PUBLIC_DOMAIN을 지정한다. OpenAI 실제 연동은 후속 단계에서 서버 키·모델·사용량 설정을 확인한 뒤 켠다.

## 4. 이미지 기준

Python 3.12.14-slim, Node 22.23.1-alpine, Caddy 2.11.4-alpine, pgvector/pgvector 0.8.7-pg18-trixie를 정확 태그로 고정한다. [Python 공식 이미지](https://hub.docker.com/_/python), [Node 공식 이미지](https://hub.docker.com/_/node), [Caddy 공식 이미지](https://hub.docker.com/_/caddy), [pgvector 이미지](https://hub.docker.com/r/pgvector/pgvector)를 기준으로 한다. 운영 출시 시 실제 이미지 digest를 확인하고 기록한다.
