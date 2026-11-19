# 2026-11-19 출시 전 점검

점검 기준은 `09ef361`이다. 8080 통합 배포에는 기존 `.env`와 개발 DB를 사용한다. 사용자는 Cloudflare 터널의 `context canceled` 경고 당시 결과 화면이 정상이라고 확인했다. 해당 시각 서버 로그에는 설문 평가 `201`과 결과 조회 `200`이 기록됐다. 결과 화면 전환 때 상담 조회가 취소된 것으로 추정한다. [결과 화면 전환 코드](../../frontend/src/features/survey/useEvaluation.ts#L28) · [cloudflared 요청 처리](https://github.com/cloudflare/cloudflared/blob/master/proxy/proxy.go)

## 출시 전 조치

| 우선순위 | 항목 | 증거와 완료 조건 |
| --- | --- | --- |
| 높음 | 챗봇의 안전 분기 | 가상 문장 ‘현관문이 경첩에서 빠져서 곧 떨어질 것 같아요’는 추가 질문으로 진행했고, ‘천장에서 물이 떨어지고 있어요’는 안전 우선으로 분류됐다. ‘콘센트에서 연기가 나요’는 안전 우선으로 분류됐다. 시설물 낙하 위험과 일상적인 물방울 표현을 구분하고, 실제 코드 경로의 회귀 테스트로 확인한다. [챗봇 코드](../../backend/app/services/chat.py#L103) |
| 높음 | 공개 환경의 요청량과 요청 크기 | 비회원 설문 평가에도 OpenAI 임베딩을 호출하는 경로가 있고, 채팅 사용량 제한은 설문에 적용되지 않는다. 공개 접근 시 비용과 서버 부하를 제한할 정책이 필요하다. 70KB 합성 입력은 개발 프록시를 지나 API에서 `422`로 거부됐고, 운영 HTTPS 구성에서는 프록시가 `413`으로 차단했다. 8080 터널을 공개할 때 적용되는 요청 크기와 평가 호출 제한을 별도로 검증한다. [설문 평가](../../backend/app/services/guidance.py#L130) · [운영 프록시](../../frontend/Caddyfile.prod#L9) |
| 높음 | Python 의존성 | `pip-audit`에서 중복을 제외한 보안 공지 5개와 영향 패키지 3개를 확인했다. 수정 버전 기준은 `certifi` 2026.10.18, `dnspython` 2.9.2, `opentelemetry-api` 1.45.2다. 서비스의 공격 도달 여부는 시험 범위 밖이다. 운영 이미지 갱신 뒤 재검색과 회귀 검증이 필요하다. [certifi](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) · [dnspython](https://github.com/rthalley/dnspython/security/advisories/GHSA-vvf4-9x63-8xvv) · [OpenTelemetry](https://www.cve.org/CVERecord?id=CVE-2026-126360) |
| 일정 | 검색 자료 검토 만료 | 게시 대상 법령 묶음의 검토 기한은 2027-01-02다. 만료되면 해당 자료가 새 안내에서 제외되므로 원문 재검토와 게시 일정을 확정한다. [자료 검토 기록](../../data/knowledge/m09-20261004/review.json) · [검색 적격성](../../backend/app/services/retrieval.py#L104) |

## 검증 결과

- 새 PostgreSQL·pgvector 볼륨에서 초기 마이그레이션과 Alembic 일치 검사를 통과했다. 백엔드 277개, 프런트엔드 69개, 린트·빌드·OpenAPI 계약을 확인했다.
- PC·모바일 Chromium에서 설문, 챗봇 이력, 초기화, 권한, 삭제, 키보드와 자동 접근성을 검사했다. HTTP 브라우저 테스트는 첫 실행 17개 통과 후 네트워크 오류로 중단된 1개도 단독 재실행에서 통과했다. 별도 로컬 HTTPS 운영 이미지에서는 Secure 쿠키, CSRF, 요청 크기 제한 테스트 2개가 통과했다.
- OpenAI를 끈 격리 서버에서 20개 동시 흐름을 실행했다. 기본 API의 p95는 182~352ms였다. DB 중단 중 live `200`, ready·catalog `503`을 확인했고 DB 및 API 재시작 뒤 ready가 약 2초에 복구됐다.
- 합성 데이터 암호화 백업을 로컬에서 복원했다. 삭제 결과가 되살아나지 않았고 기존 완료 요청은 `410`으로 처리됐으며 검토 파일 바이트가 일치했다. 프런트 운영 의존성의 `npm audit --omit=dev` 결과는 공지 0개였다.

이번 점검은 로컬·격리 서버 기준이다. 실제 운영 도메인, 서버 밖 백업 복원과 운영 경보, 공개 사용량 정책의 검증은 출시 인수에서 확인한다. [출시 절차](../operations/deployment.md)
