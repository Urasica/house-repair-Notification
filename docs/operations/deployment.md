# 배포와 Windows 테스트 실행

환경별 적용 현황·실행 증거·출시 인수 상태는 [현재 작업판](../../progress/current-status.md)에서 관리한다. 이 문서는 실행 절차와 운영 조건을 정의한다.

개발 서비스 `http://localhost:8080`과 아래 `https://localhost:18880`의 preview 프로젝트는 별도 환경이다.

## Windows 실행

Docker Desktop의 Linux 엔진과 Compose 2.24.4 이상이 필요하다(`!override` 사용). 저장소 루트에서 실행한다.

```bat
test-deploy.bat
```

기본 주소는 `https://localhost:18880`이다. 기본 실행은 외부 터널을 만들지 않는다. 기존 `.env`에서 OpenAI 키·모델·한도만 이어받고 DB 비밀번호·백업 키는 별도로 생성한다. 비용 없는 기본 안내 검증은 다음과 같다.

```bat
test-deploy.bat -NoOpenAI
stop-test-deploy.bat
```

`-NoBuild`는 기존 이미지를 재사용하고, `-Port 18881`은 호스트 포트를 변경한다. 중지 BAT는 컨테이너·네트워크만 제거하며 DB·인증서 볼륨과 암호화 백업은 보존한다. 다른 프로젝트의 개발 서버(8080)를 중지하지 않는다. 다른 서비스가 포트를 사용 중이면 설정 변경 전에 실패한다.

로컬 HTTPS는 Caddy 내부 CA 인증서를 사용하므로 일반 브라우저에서 인증서 경고가 나타날 수 있다. 시스템 신뢰 저장소를 자동 수정하지 않는다. 자동 시험의 인증서 예외는 localhost에만 허용하며, 별도 배포 검증 명령은 해당 CA 파일을 지정해 실제 인증서 체인을 검사한다.

```powershell
powershell -NoProfile -File scripts/test-deploy.ps1 -Action Status
powershell -NoProfile -File scripts/test-deploy.ps1 -Action Daily
backend/.venv/Scripts/python.exe scripts/verify_preview.py
```

`Daily`는 삭제 기록 내보내기 → 암호화 백업 → 만료 정리를 실행한다. 모두 성공해야 `data/private/preview/daily-success.json`이 갱신된다. 시작 때도 같은 작업을 실행하지만 **매일 자동 실행하는 스케줄은 등록하지 않는다.** 장기간 켜 두는 환경은 별도 스케줄과 실패 감시가 필요하다.

## 선택 실행: 임시 터널

터널은 외부 공개를 명시적으로 선택한 경우에만 실행한다. 기본 실행·검증은 로컬로 한정한다.

cloudflared가 PATH에 있어야 한다. 설치가 필요하면 공식 [설치 안내](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)를 따른다. 외부에 공개할 때 직접 다음 명령을 실행한다.

```bat
test-deploy.bat -Tunnel
```

Cloudflare가 발급한 정확한 HTTPS Origin만 허용하고, 호스트 원본 포트는 `127.0.0.1`에 연결한다. 터널 프로세스의 PID와 시작 시각을 확인해 이 실행기가 시작한 프로세스만 종료한다. 기본은 터미널을 유지하며 Ctrl+C로 터널을 중단한다. `-Detached`는 터널을 백그라운드에 남긴다. 전체 테스트 배포 종료는 `stop-test-deploy.bat`를 사용한다.

Quick Tunnel은 주소를 아는 사람이 접근할 수 있고 주소가 재시작 때 바뀔 수 있다. 고정 도메인·가용성을 보장하는 운영 배포가 아니며 SSE와 동시 요청 제한도 있다. [Cloudflare Quick Tunnel 설명](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). 별도 Cloudflare 접근 인증은 구성하지 않았다. 시험 계정만 사용하고 운영 이용자 데이터를 넣지 않는다.

## 격리와 자료

| 항목 | 테스트 배포 |
| --- | --- |
| Compose 프로젝트 / DB | `repair-guide-preview` / `repair_guide_preview` |
| 설정·키 | `.env.preview` — Git 제외, 백업 키를 다른 보호 위치에도 보관 |
| 보호 파일 | `data/private/preview/` — Git 제외 |
| 초기 자료 | 개발 DB의 catalogs·knowledge_sets·knowledge_documents·knowledge_chunks만 복사 |
| 개인정보 | 기존 회원·세션·상담·질문·결과를 복사하지 않음; 시험 중 생성한 계정은 재시작 후에도 유지 |
| 개발 DB 부재 | 검토된 카탈로그만 게시; 검토 지식 반입 전 RAG 미준비 |
| 백업 | 로컬 암호화 사본 + 같은 PC의 remote-test 사본; 실제 원격 백업이 아님 |
| 모델 | gpt-5.4-mini / text-embedding-3-large·1536차원; 임베딩 총량 제한 없음 |

원본 검토 파일 `data/private/m08/2026-10-04/manifest.json`과 해당 폴더가 필요하다. 기존 preview 데이터가 있으면 다시 복사하지 않는다. 자료 갱신은 검토·게시 절차를 따른다. `.env.preview`만 삭제하면 기존 DB의 비밀번호는 바뀌지 않으므로 재설정 수단으로 사용하지 않는다.

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

테스트 BAT는 실행 이미지와 DB 스키마가 호환되는 환경의 반복 실행용이다. 새 schema에서 이전 schema로 변경하는 범용 무중단 릴리스 도구가 아니다. 백업 단계에서 schema 불일치가 나면 생략하지 말고 이전 ops 이미지로 먼저 백업한다.

## 로그·스케줄·경보 인수

API는 원시 Uvicorn access log를 끄고 시간·정의된 경로 템플릿·HTTP method·status·지연·서버 traceId만 JSON으로 남긴다. URL query·경로의 실제 ID·쿠키·원문·이메일을 기록하지 않는다. Caddy access log는 켜지 않는다.

기본 production/preview 설정의 Docker local 로그는 컨테이너당 10MB×3 회전이다. **용량 회전은 14일 보존을 보장하지 않는다.** Linux 운영 서버에는 `compose.journald.yaml`과 `docker/operations/journald.conf.example`을 제공한다. 후자는 호스트 전체 journal에 적용되므로 기존 정책과 검토한 뒤 설치·재시작하고, 회전된 journal의 14일 정리와 디스크 사용량을 검증한다. 이 호스트 정책은 Linux journald용이며 Windows Docker Desktop에 그대로 적용하지 않는다. [Docker journald 설정](https://docs.docker.com/engine/logging/drivers/journald/).

운영 호스트에서 일일 삭제 내보내기·백업·정리를 같은 프로젝트/비밀 설정으로 순차 실행하도록 스케줄한다. 실패하면 이후 성공 기록을 덮어쓰지 않고 비정상 종료한다. 담당자가 받을 실제 경보 채널을 정한 뒤 ready 실패, 마지막 성공 24시간 초과, 저장소 여유 공간, 원격 마운트 해제, 암호화 실패, API 오류율, OpenAI 사용량과 생성 중단을 시험한다. 금액 기준 경보는 과금 반영 지연을 고려한다. 상담 생성에 별도 IP 제한이 없고 인증 시도 제한은 API 재시작 때 초기화되는 점도 공개 출시 전 남용 방지 검토에 포함한다.

## 장애와 되돌리기

정상 schema와 호환이 입증된 경우에만 이전 web/API 이미지로 되돌린다. 태그 교체 전에 web/API를 중지하고 DB schema와 이전 코드의 호환성을 확인한다. 자동 downgrade나 운영 볼륨 삭제는 하지 않는다.

schema가 호환되지 않으면 점검 상태를 유지하고 [암호화 복원 절차](retention-backup.md)로 빈 `_restore` DB에 복원한다. 최신 삭제 기록·만료 적용, 앱 역할 권한, 인증 폐기, 지식 철회 상태를 검사한다. 지식 재검토/게시 없이 RAG를 다시 공개하지 않는다. RPO 24시간/RTO 4시간은 목표이며 실제 운영 서버에서 복원 시간을 측정하기 전 달성으로 표시하지 않는다.
