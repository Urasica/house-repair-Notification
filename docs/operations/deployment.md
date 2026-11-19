# 배포와 Windows 로컬 실행

## Windows 실행

Docker Desktop을 Linux 컨테이너 모드로 시작한 뒤 `test-deploy.bat`를 실행한다. Docker Compose가 이미지를 빌드하고 DB 스키마와 검토된 설문 목록을 준비한다. 완료되면 콘솔에 표시된 로컬 주소에 접속한다.

Windows 배치는 [localhost:8080](http://localhost:8080)에서 로컬·터널 테스트에 공통으로 사용할 서버를 실행한다. `.env`가 있으면 `.env.example` 위에 적용하고 기존 개발 Compose 프로젝트 `repair-guide`와 DB 볼륨을 사용한다. `WEB_ORIGINS`의 로컬 주소는 8080과 맞춘다. OpenAI 사용 여부는 `OPENAI_ENABLED`를 따르며, 검색에는 같은 DB에 게시된 지식 자료를 사용한다. `.env.ops`도 있으면 개발 프로젝트의 삭제 기록 내보내기를 적용한다. DB 접속값을 수정할 때는 기존 볼륨의 계정·암호와 맞춰야 한다.

`.env`가 없으면 예제 설정으로 `repair-guide-local` 프로젝트를 같은 8080 포트에서 실행한다. 이 경우 OpenAI는 꺼져 있다. `stop-test-deploy.bat`는 같은 설정 파일을 기준으로 프로젝트를 선택하며 DB 볼륨은 보존한다. `.env`를 추가하거나 제거해서 실행 방식을 바꿀 때는 먼저 실행 중인 서버를 종료한다.

## Windows Cloudflare Quick Tunnel 테스트

공통 서버가 실행 중이면 `api-tunnel -Port 8080 -LocalHostHeader`를 실행한다. 서버와 터널을 한 번에 시작하려면 Docker Desktop과 `api-tunnel.cmd`를 사용할 수 있는 터미널에서 `test-deploy.bat -OpenTunnel`을 실행한다. 출력된 HTTPS 주소에서 테스트한다. Ctrl+C로 공개 터널을 끊고, 서버까지 종료하려면 `stop-test-deploy.bat`를 실행한다. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

기존 `test-tunnel-deploy.bat`와 `stop-test-tunnel-deploy.bat`는 같은 시작·종료 배치를 실행한다. 공개 주소에서 생성된 설문과 계정은 공통 DB에 저장되며, OpenAI 사용량은 `.env`에 설정한 계정에 반영된다.

FastAPI의 `tunnel_test` 설정에서만 HTTPS `*.trycloudflare.com`의 동일 출처 브라우저 요청을 허용한다. `-LocalHostHeader`를 사용해도 브라우저 Origin은 공개 주소로 전달된다. 로그인 쿠키에는 `Secure`와 `__Host-` 접두사를 적용하고 변경 요청은 기존 CSRF 토큰도 검사한다. 교차 출처 CORS는 `WEB_ORIGINS`의 명시 주소를 따른다.

## 실제 운영 서버 구성

`.env.production.example`을 비밀 파일 `.env.production`으로 복사하고 고유 앱/관리자 DB 비밀번호·실제 HTTPS Origin·도메인·릴리스 태그를 설정한다. `.env.ops.example`을 별도 `.env.production.ops`로 복사해 BACKUP_SCOPE·암호화 키·삭제 기록·검토 파일·백업 경로를 설정한다. 로컬 `.env.ops`와 섞지 않는다. 원격 디렉터리가 실제 서버 밖 저장소에 마운트되었는지 확인해야 한다.

이미지는 Python 3.12.14, Node 22.23.1, Caddy 2.11.4, pgvector 0.8.7/PostgreSQL 18 기반 digest를 고정한다. 릴리스별 `RELEASE_TAG`를 재사용하지 않고 결과 이미지 ID/digest를 기록한다. API·DB 초기화·Caddy 설정은 이미지에 포함한다. 상시 소스 bind mount는 없고 API는 비관리자 사용자·읽기 전용 루트·단일 워커로 실행한다. 백업/삭제 기록 등 데이터 폴더 마운트는 별도다.

운영 Compose 파일 순서는 `compose.yaml`, `compose.prod.yaml`, `compose.deletions.yaml`, 필요할 때 `compose.ops.yaml`이다. `compose.admin.yaml`은 migration 일회성 명령에만 추가하며 `up`에 넣지 않는다. 운영 프로젝트 이름도 고정한다. 서버는 80/443만 외부에 개방하고 API/DB는 내부 네트워크에 둔다. DNS와 Caddy 인증서 발급·갱신, database/caddy-data/caddy-config 볼륨을 인수한다.

릴리스 순서:

1. 현재 이미지 태그·스키마·자료 버전과 이전 릴리스 이미지를 보존한다. **현재 스키마에 맞는 이전 ops 이미지**로 최신 삭제 내보내기·백업을 완료하고 원격 도착을 확인한다.
2. 기존 web/API를 완전히 중지한다. DB가 준비됐는지 확인한다. 새 이미지의 관리 URL로 `python -m alembic upgrade head`를 한 번 실행한다.
3. 새 API를 제한된 DB 계정으로 시작한다. 중단 요청 정리와 `/health/ready`, catalogReady·ragReady, 카탈로그·지식 검토 기한을 확인한다. 이어 web을 시작한다.
4. 실제 HTTPS에서 비회원 설문, 가입/재로그인, 회원 이력·챗봇, 문의 안내, 삭제, CSRF·쿠키를 검증한다. 시험 전에 생성·임베딩 사용 여부를 기록한다.
5. 배포 후 Daily와 원격 복원 시험을 실행하고 이미지 ID·schema·자료·모델·시험·담당자·남은 제한을 기록한다.

운영 백업 단계에서 schema 불일치가 나면 호환되는 이전 ops 이미지로 먼저 백업한다.

## 로그·스케줄·경보 인수

API는 원시 Uvicorn access log를 끄고 시간·정의된 경로 템플릿·HTTP method·status·지연·서버 traceId만 JSON으로 남긴다. URL query·경로의 실제 ID·쿠키·원문·이메일을 기록하지 않는다. Caddy access log는 켜지 않는다.

기본 production 설정의 Docker local 로그는 컨테이너당 10MB×3 회전이다. **용량 회전은 14일 보존을 보장하지 않는다.** Linux 운영 서버에는 `compose.journald.yaml`과 `docker/operations/journald.conf.example`을 제공한다. 후자는 호스트 전체 journal에 적용되므로 기존 정책과 검토한 뒤 설치·재시작하고, 회전된 journal의 14일 정리와 디스크 사용량을 검증한다. 이 호스트 정책은 Linux journald용이며 Windows Docker Desktop에 그대로 적용하지 않는다. [Docker journald 설정](https://docs.docker.com/engine/logging/drivers/journald/).

운영 호스트에서 일일 삭제 내보내기·백업·정리를 같은 프로젝트/비밀 설정으로 순차 실행하도록 스케줄한다. 실패하면 이후 성공 기록을 덮어쓰지 않고 비정상 종료한다. 담당자가 받을 실제 경보 채널을 정한 뒤 ready 실패, 마지막 성공 24시간 초과, 저장소 여유 공간, 원격 마운트 해제, 암호화 실패, API 오류율, OpenAI 사용량과 생성 중단을 시험한다. 금액 기준 경보는 과금 반영 지연을 고려한다. 상담 생성에 별도 IP 제한이 없고 인증 시도 제한은 API 재시작 때 초기화되는 점도 공개 출시 전 남용 방지 검토에 포함한다.

## 장애와 되돌리기

정상 schema와 호환이 입증된 경우에만 이전 web/API 이미지로 되돌린다. 태그 교체 전에 web/API를 중지하고 DB schema와 이전 코드의 호환성을 확인한다. 자동 downgrade나 운영 볼륨 삭제는 하지 않는다.

schema가 호환되지 않으면 점검 상태를 유지하고 [암호화 복원 절차](retention-backup.md)로 빈 `_restore` DB에 복원한다. 최신 삭제 기록·만료 적용, 앱 역할 권한, 인증 폐기, 지식 철회 상태를 검사한다. 지식 재검토/게시 없이 RAG를 다시 공개하지 않는다. RPO 24시간/RTO 4시간은 목표이며 실제 운영 서버에서 복원 시간을 측정하기 전 달성으로 표시하지 않는다.
