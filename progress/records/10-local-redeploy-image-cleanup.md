# 오래된 Docker 이미지 정리와 M13 로컬 재배포

> 기록 ID: R010 · 기준일: 2026-10-18 · 환경: repair-guide 개발 서비스·localhost:8080
> 관계: 로컬 재배포 완료; 실제 운영·서버 밖 백업·스케줄 인수는 M12 작업으로 남음.
> 당시의 증거 기록이다. 본문의 상태·수치·다음 작업은 해당 시점에 한정한다. [최신 상태](../current-status.md)와 [남은 작업](../current-status.md#남은-작업)을 먼저 확인한다.

작성: 2026-10-18 · 상태: 완료 · 대상: `repair-guide` / `http://localhost:8080`

기준: [M13 구현·검증](09-m13-chat-review.md), [배포 절차](../../docs/operations/deployment.md)

## 이미지 정리

사용자 요청에 따라 생성 시각이 2026-07-18 00:00 Asia/Seoul 이전이고 어떤 컨테이너에서도 참조하지 않는 이미지 18개를 정리했다. 중지된 컨테이너의 이미지도 보호했고 현재 빌드에 필요한 Node 이미지를 보존했다. 삭제 직전 컨테이너 참조를 다시 확인했으며 강제 삭제는 사용하지 않았다.

| 분류 | 정리한 이미지 |
| --- | --- |
| 이전 앱 빌드 | infra-api:latest, infra-frontend:latest, infra-migrate:latest |
| 미사용 DB·웹 서버 | postgres:16.6-alpine, postgres:15-alpine, redis:latest, redis:7-alpine, nginx:1.28-alpine, nginx:1.20.1-alpine |
| 도구·개발 환경 | grafana/k6:1.5.0, bash:5.3, rhysd/actionlint:1.7.12, testcontainers/ryuk:0.12.0, ghcr.io/shopify/toxiproxy:2.5.0, ghcr.io/shopify/toxiproxy:2.12.0, localstack/localstack:3.8.1, python:3.11.13-slim, hello-world:latest |

정리 직후 Docker의 이미지 표시 용량은 15.62GB에서 10.01GB로 감소했고 이미지 수는 50개에서 32개가 됐다. 이후 새 배포 이미지를 빌드했으므로 최종 이미지 수·용량은 이 정리 직후 수치와 구분한다. 공유 레이어·빌드 캐시가 있어 이를 호스트 디스크의 실제 회수량으로 해석하지 않는다. 컨테이너·데이터 볼륨·빌드 캐시는 정리 대상에 포함하지 않았다. 마지막에 삭제 대상 18개 ID가 모두 사라졌는지 확인했다.

## 백업과 재배포

1. 기존 API/web 및 스키마 0005_m10용 ops 이미지를 `pre-m13-20261018` 태그로 보존했다. 현재 DB와 일치하는 기존 ops 이미지로 최신 삭제 기록을 내보내고 암호화 백업했다.
2. 배포 전 백업 `backup-20261018T002701Z-6711c750beb94b59bb9e5d533fd5b05e.fernet`은 3,011,852바이트이며 검토 파일 29개를 포함한다. 두 로컬 사본의 SHA-256 일치를 확인했다.
3. API/web/ops를 새 코드로 빌드했다. 기존 API/web 중지를 확인하고 관리자 연결로 `alembic upgrade head`를 한 번 실행해 0006_m13으로 갱신했다.
4. 기존 `.env`·`.env.ops`와 `compose.yaml`·`compose.deletions.yaml`로 단일 API/web을 시작했다. DB·인증서 볼륨과 기존 설정을 유지했다.
5. 검증 후 새 0006_m13 ops 이미지로 삭제 기록과 배포 후 백업을 만들었다. `backup-20261018T003148Z-892e50e76446422b9ae2d038f0d30dac.fernet`은 3,013,796바이트이며 사본 일치 검증을 통과했다.

백업은 `data/private/operations/backups/`와 `data/private/operations/remote/`에 암호화해 저장했다. 두 경로 모두 작업 폴더 안의 일반 로컬 디렉터리임을 확인했으며 실제 원격 백업으로 간주하지 않는다. 백업 키와 실제 환경 값은 기록에 포함하지 않는다.

배포 이미지 ID: API `9036f627d075`, web `5398090c3087`. DB 이미지는 기존 pgvector/PostgreSQL 18을 유지했다. 별도 preview/운영 프로젝트나 외부 터널은 시작하지 않았다.

## 데이터와 동작 확인

| 항목 | 재배포 직전 | migration 직후 |
| --- | --- | --- |
| schema | 0005_m10 | 0006_m13 |
| 사용자 | 8 | 8 |
| 저장 결과 | 6 | 6 |
| 상담 | 9 | 9 |
| 정제 질문 | 10 | 10 |
| 지식 청크 | 98 | 98 |

모든 기존 기록의 건수가 유지됐다. 배포 검증 도구가 합성 회원 2개를 추가해 최종 사용자 수는 10명이다. 검증용 상담·대화·정제 질문은 본인 API로 정리했고 기존 결과 6개·상담 9개·정제 질문 10개·지식 청크 98개는 최종 확인에서도 유지됐다. 합성 회원 계정과 해당 사용량 예약은 기존 정책대로 남긴다.

- API·DB 컨테이너 정상 상태와 web HTTP 응답을 확인했다. `/health/ready`는 status=ok, catalogReady=true, ragReady=true다.
- [기본 API 점검](../../scripts/smoke_api.py)에서 화면·카탈로그·준비 상태·인증·권한·오류 응답을 통과했다. API 내부 OpenAPI에서 Session.purpose도 확인했다.
- 실제 배포 사이트의 360px Chromium에서 설문/챗봇 세션 분리, 화면 내 안전 안내, 초기화 취소/성공, 이전 세션 종료, 설문 유지, 입력창 초점, 새로고침 후 빈 대화를 확인했다. axe WCAG AA 위반과 가로 넘침은 없었다.
- 검증 요청의 채팅은 서버가 Embeddings/Responses 호출 전에 즉시 SAFETY_PRIORITY로 반환하는 안전 신호 1건만 사용했다. 실제 OpenAI 설정은 유지했고 해당 검증의 외부 API 호출은 0건이다. 실제 생성 호출이 포함될 수 있는 종단 시험은 자동 승인 검토에서 외부 전송 사유로 거부되어 실행하지 않았다. 생성·근거 계약은 기존 M13 격리 회귀 결과를 따른다.

로컬 검증 산출물은 `artifacts/m13-deployment/report.json`, `chat-deployed.png`에 있다. 운영 서버·도메인·실제 원격 백업/스케줄 인수는 계속 M12 후속 범위다.
