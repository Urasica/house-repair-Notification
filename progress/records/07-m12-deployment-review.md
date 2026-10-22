# M12 배포 준비와 로컬 HTTPS 검증

> 기록 ID: R007 · 기준일: 2026-10-06 · 환경: 격리 preview HTTPS·OpenAI OFF
> 관계: R010은 별도 개발 서비스 재배포이며 preview 재검증이나 운영 출시를 대신하지 않음.
> 당시의 증거 기록이다. 본문의 상태·수치·다음 작업은 해당 시점에 한정한다. [최신 상태](../current-status.md)와 [남은 작업](../current-status.md#남은-작업)을 먼저 확인한다.

기록일: 2026-10-06 (Asia/Seoul). 상태: **운영 이미지/로컬 테스트 배포 완료, 실제 운영 출시 인수 대기**.

## 구현

- `test-deploy.bat` / `stop-test-deploy.bat`: 격리된 preview DB·인증서 볼륨, 무작위 DB/백업 키, 실제 검토 자료만 초기 복사, 백업→API 중지→단일 migration→시작→정리/백업.
- 기본은 localhost HTTPS. `-Tunnel`일 때만 cloudflared 임시 주소 발급·정확한 Origin 설정·터널 소유 프로세스 종료. 이번 사용자 지시는 공개 없이 로컬 검증이며 실행 중인 cloudflared는 0개다.
- 이미지 기반 Python/Node/Caddy/pgvector digest 고정, 운영 RELEASE_TAG 필수, DB 초기화와 Caddy 설정 이미지 내장, API 읽기 전용·비관리자·내부 포트.
- API 요청 로그에서 원시 URL/query/쿠키/식별자를 제외하고 경로 템플릿·상태·지연·traceId만 구조화. 운영 모드 ops의 HTTPS Origin 누락 수정.
- 64KB 프록시 본문 제한·40초 응답 헤더 제한, HTTPS 보안 쿠키/Origin/CSRF 시험 추가.
- 용량 로그 회전, Linux journald 14일 정책 예시, 배포·스케줄/경보 인수·schema 호환 rollback 안내. 실제 호스트에 스케줄이나 journald 정책을 설치하지 않았다.

## 실제 검증

| 검증 | 결과 |
| --- | --- |
| 격리 PostgreSQL 전체 백엔드 | **238 통과**, 실제 DB 82 + 독립 156 |
| API 메타데이터 로그 회귀 | 가짜 민감 경로/query/header 미출력, traceId/상태/지연 확인 |
| 프론트 단위 시험 | **40 통과**, OpenAPI·생성 타입 일치 |
| 로컬 HTTPS Chromium 360×800 | **3 통과**: 비회원 설문·삭제·회원 제한, 회원 로그인/챗봇 복구/이력/삭제/로그아웃, 배포 보안 |
| 자동 접근성 | 위 핵심 화면의 axe WCAG A/AA 위반 0, 가로 넘침 없음 |
| HTTPS 배포 보안 | `__Host-repair_auth` Secure/HttpOnly/SameSite=Lax/Path=/, 잘못된 Origin/누락 CSRF 403, 초과 본문 413 |
| 배포 직접 검사 | 실제 CA로 localhost 인증서 검증, 운영 APP_ENV·Origin·모델·차원·schema 확인 |
| 컨테이너 경계 | web만 127.0.0.1:18880→443, API/DB 외부 포트 없음, 앱 DB 계정 비관리자, 소스 bind mount 없음 |
| 백업·정리 | 약 3MB 암호화 pg_dump+검토 파일 29개, 로컬 대체 원격 사본 바이트 일치, 삭제 내보내기·cleanup 성공 |
| 중지·재실행 | preview 볼륨/자료 유지, 재실행 백업·migration 성공, 기존 8080 개발 서버 catalogReady/ragReady=true 유지 |
| 포트 충돌 | 개발 서버의 8080 지정 시 설정 변경 전에 exit 1로 중단 |
| 설정 검사 | PowerShell 파싱, 세 가지 Caddy config 유효, journald Compose 병합 확인 |
| 프론트/백엔드 정적 검사 | 타입·린트·빌드, Ruff/format 통과 |

Docker 이미지 ID·schema·모델·준비 상태와 비밀 없는 실행 증거는 [preview-verification.json](../../data/operations/m12-20261006/preview-verification.json)에 기록했다. API schema는 `0005_m10`, 카탈로그는 `m08a-20261004-v2`다. 자료의 적용 범위·검토 기한·법령 설명 한정은 M09/M10 기록을 유지한다.

이번 preview 시험은 `-NoOpenAI`여서 catalogReady=true/ragReady=false다. 새로운 임베딩·생성 API 호출을 수행하지 않았으며 모델의 실제 호출 품질 검증은 M09/M10 기록에 있다. 회원 채팅은 모델 OFF의 안전한 기본 안내 저장/복구까지 시험했다. 개발 환경의 OpenAI 설정은 바꾸지 않았다.

## 남은 출시 조건

실제 서버·도메인/DNS·공인 인증서, 운영 키 주입, 서버 밖 백업과 별도 키 보관, 일일 정리/백업 스케줄, 디스크/실패/사용량 경보 수신, 실제 호스트 로그 14일 정책, 운영 복원 RPO/RTO 측정, 스크린리더·확대 최종 인수, 운영 담당자 확정이 필요하다. 상담 생성 남용 방지와 터널 공유 IP의 인증 시도 제한도 공개 경계에서 점검한다.

공개 터널 종단 검증은 사용자의 로컬 전용 지시에 따라 수행하지 않았다. `remoteVerified=true`는 같은 PC의 별도 시험 디렉터리를 뜻하며 실제 원격 백업 완료가 아니다. 원격 GitHub CI 실행 성공도 보고하지 않는다. 이 조건을 충족하기 전 M12 전체나 MVP 운영 출시를 완료로 표시하지 않는다.

실행과 장애 대응은 [배포 안내](../../docs/operations/deployment.md)를 따른다.
