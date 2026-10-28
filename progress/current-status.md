# 현재 상태와 남은 작업

갱신: 2026-10-28 · 서비스 관측 기준: 2026-10-28 [R029](records/29-insufficient-information-examples.md)

현재 판단과 실행할 작업은 이 문서에서만 수정한다. 실시간 상태 화면은 아니며 관측 이후 실행 여부는 보장하지 않는다. 시험 수치·명령별 결과는 연결한 당시 기록에서 확인한다. [남은 작업](#남은-작업) · [증거 색인](records/README.md) · [갱신 방법](README.md)

## 단계별 판정

| 단계 | 판정과 범위 | 근거 |
| --- | --- | --- |
| M01~M04 | 계약·개발 환경·DB/API·인증 기반 완료 | [R001 당시 체크리스트와 인라인 완료 기록](records/01-mvp-tasks-snapshot.md) |
| M05~M07 | 카탈로그/설문·결과/이력 API·기본 화면 완료; 실제 목록 통합까지 확인 | [R001](records/01-mvp-tasks-snapshot.md), [R003](records/03-m08a-catalog-review.md) |
| M08 | 원문 전사·완전성 검토 완료; 법률/LH 운영 적용 승인은 별도 | [R002](records/02-m08-source-review.md) |
| M08A | 실제 목록 작성·검토·로컬 게시·실데이터 통합 완료 | [R003](records/03-m08a-catalog-review.md) |
| M09 | 지식 반입·실제 임베딩·검색 평가·로컬 게시/설문 연결 완료 | [R004](records/04-m09-knowledge-review.md) |
| M10 | 회원 챗봇·실제 생성 평가 완료; 당시 설문 공유 동작은 M13에서 개정 | [R005](records/05-m10-chat-review.md), [R009](records/09-m13-chat-review.md) |
| M11 | 보존·삭제·백업/복원·로컬 통합 검증 완료; 실제 운영 인수는 M12 | [R006](records/06-m11-operations-review.md) |
| M12 | 운영 이미지·격리 로컬 HTTPS 준비 완료; 실제 운영 출시 인수 대기 | [R007](records/07-m12-deployment-review.md), [남은 작업](#m12-docker-운영-배포와-mvp-출시-확인) |
| M13 | 독립 챗봇·대화 초기화·사이트 내 답변 구현/격리 검증 및 기존 로컬 서비스 재배포 완료 | [R009](records/09-m13-chat-review.md), [R010](records/10-local-redeploy-image-cleanup.md) |
| M14 | PC·모바일 시인성·화면 밀도·홈 말투 개선과 소스/모의 API 검증 및 개발 서비스 재배포 완료 | [R016](records/16-responsive-ui-visibility.md), [R017](records/17-mobile-density-plain-language.md), [R018](records/18-friendly-home-copy.md), [R019](records/19-local-deploy-persona-ux-review.md) |
| M15 | UX01~UX08 최소 수정·선택적 설문 불러오기·개별 커밋과 소스/격리 통합 검증 및 개발 8080 재배포·실제 브라우저/생성 응답 확인 완료 | [R027](records/27-ux08-focus-and-integration.md), [R028](records/28-ux15-local-redeployment.md), [UX06 경계](records/25-ux06-opt-in-survey-chat.md) |
| M16 | 정보 부족 설문/채팅의 가상 보수 검토 예시·과거 저장 호환·소스/실제 DB 검증 및 개발 8080 반영·PC/모바일 Browser Use 확인 완료 | [R029](records/29-insufficient-information-examples.md) |

## 환경별 적용과 검증

| 환경 | 마지막 근거·일자 | 확인 범위와 남은 제한 |
| --- | --- | --- |
| 격리 시험 `repair-guide-test` / `http://localhost:18081` | [R027](records/27-ux08-focus-and-integration.md) · 2026-10-22 | 최종 UX 소스/이미지·schema 0006_m13·실제 카탈로그/DB 브라우저 통합·접근성, 백엔드/프론트 회귀·계약 일치 확인. 별도 시험 볼륨, OpenAI OFF/mock. 이전 시험 볼륨 보존 |
| 개발 `repair-guide` / `http://localhost:8080` | [R029](records/29-insufficient-information-examples.md) · 2026-10-28 | UX01~UX08에 정보 부족 가상 보수 검토 예시 추가. schema `0006_m13`·기존 자료 유지. 실제 PC/모바일 UNKNOWN 설문·문의 복사 분리·채팅 예시/복원 확인. 전체 UX와 데이터 내용 지문·실제 생성 확인은 R028 당시 범위. 백업 사본 두 개는 같은 PC |
| 격리 HTTPS preview / `https://localhost:18880` | [R007](records/07-m12-deployment-review.md) · 2026-10-06 | 당시 schema `0005_m10`, OpenAI OFF의 배포/보안 검증. M13 반영·현재 실행 여부를 확인한 기록은 없음 |
| 실제 운영 서버·도메인 | [M12 작업](#m12-docker-운영-배포와-mvp-출시-확인) | 대상·담당/일정과 운영 설정·검증 증거 미확정. 운영 출시 완료로 판정하지 않음 |

실제 OpenAI의 임베딩/검색 평가와 생성 평가는 각각 [R004](records/04-m09-knowledge-review.md)·[R005](records/05-m10-chat-review.md)의 당시 범위다. M13 mock 회귀는 [R009 검증 결과](records/09-m13-chat-review.md#검증-결과)를 따른다. 추가로 [R019](records/19-local-deploy-persona-ux-review.md)·[R028](records/28-ux15-local-redeployment.md)에서 승인된 가상 누수와 조문 설명의 실제 제공자 응답을 확인했으며 전체 품질 재평가로 해석하지 않는다. 이전 UI 분류 기록은 [R008](records/08-local-ui-review.md)에 있다.

## 자료와 외부 입력

| 입력 ID | 확인 상태·적용 제한 | 후속 작업·기준 |
| --- | --- | --- |
| I-DATA-01 | 원문 추출 지시/전체 정리 완료. 실제 카탈로그 `m08a-20261004-v2`와 지식 게시 증거 확보. 합성 fixture는 공개 목록/RAG에 사용하지 않음 | [R002](records/02-m08-source-review.md), [R003](records/03-m08a-catalog-review.md), [R004](records/04-m09-knowledge-review.md) |
| I-LH-01 | LH_OPERATION 미확보. 법령 참고·명시적 법령 설명에 한정하며 보수/교체/비용은 확정하지 않음 | 자료 확보·검토·새 게시 전까지 직접 문의 유지; [지식 정책](../docs/ai/knowledge-publication.md) |
| I-OPS-01 | 운영 서버·도메인·담당/전환 일정·운영 비밀/백업 저장 설정 미확정 | T-M12-01~T-M12-08; [작업 문서](#m12-docker-운영-배포와-mvp-출시-확인) |
| I-AI-01 | 지정 생성/임베딩 모델의 실제 호출 증거는 확보. 데이터 공유 혜택의 계정 자격·설정은 미확인; 무료 사용 가능으로 계산하지 않음 | [R004](records/04-m09-knowledge-review.md), [R005](records/05-m10-chat-review.md), [모델/한도 계약](../docs/ai/chat-generation.md) |

과거 기록의 `다음 M10`, `ragReady=false`, 시험 건수는 그 시점의 관측이며 현재 환경에 자동 승계하지 않는다.


## 설계·구현 대조

책임별 설계 정리와 D01/D02 해결 완료(2026-10-18). 설문 캐시 식별은 코드를 보완하고 백엔드 디렉터리 구조는 문서를 실제 배치에 맞췄다. 당시 코드·문서·프론트 회귀 검증은 [R015](records/15-design-implementation-alignment.md), 이후 개발 서비스 재배포는 [R019](records/19-local-deploy-persona-ux-review.md)를 따른다.

PC·모바일 UI 이후 발견한 UX01~UX08은 [최종 구현/검증](records/27-ux08-focus-and-integration.md)에 따라 수정하고 [R028](records/28-ux15-local-redeployment.md)에서 개발 8080에 배포·확인했다. UX06은 사용자가 선택한 본인 설문 결과의 입력만 챗봇으로 복사한다. 실제 기기·스크린리더·실제 이용자 조사는 미수행이다.

## 남은 작업

- 작업 ID는 재사용하거나 번호를 다시 매기지 않는다. 새 요구는 새 단계/작업 ID와 요구사항 링크를 추가한다.
- 상태는 `대기 → 진행 → 검증 → 완료`로 바꾼다. 입력이 없으면 `입력 대기`와 필요한 입력을 적는다. 담당은 역할이며 실명·일정 미정은 추정하지 않는다.
- 완료 시 날짜와 정식 증거 기록 링크를 남긴다. 취소·분할·대체는 근거 기록에 후속 ID와 이유를 남긴다.
- 작업판에는 미완료 작업과 아직 선행 조건으로 참조되는 완료 작업만 유지한다. 완료·취소 작업의 ID·조건·결과가 기록에 보존되고 현재 작업판에서 참조하는 곳이 없어지면 해당 행을 제거한다. 끝난 단계는 위 단계별 판정 한 행과 증거 링크로 요약한다. 과거 작업 목록을 계속 늘리지 않는다.
- 구현·격리 시험·특정 환경 배포는 각각 확인한다. 로컬 검증만으로 운영 작업을 완료 처리하지 않는다.

## M12. Docker 운영 배포와 MVP 출시 확인

선행 조건: M01~M11 기반, M13 개정 요구·F28~F34 증거, 운영 서버·도메인·비밀/백업 설정. [배포 절차](../docs/operations/deployment.md)와 [QA 기준](../docs/quality/verification.md)을 따른다.

운영 이미지·BAT·격리 로컬 HTTPS 준비 증거는 [R007](records/07-m12-deployment-review.md)에 있다. 아래는 실제 운영 인수에 필요한 작업이며, R006/R007에 흩어져 있던 미완료 조건도 함께 이관했다. 담당자 실명·운영 일정은 아직 정해지지 않았다.

| 작업 ID | 상태 | 작업과 완료 증거 | 담당 역할 | 선행 조건 |
| --- | --- | --- | --- | --- |
| T-M12-01 | 입력 대기 | 운영 서버·도메인/DNS·공인 HTTPS·80/443·내부 API/DB 포트·DB/인증서 볼륨·제한 DB 계정·운영 담당/전환 일정 확정 및 실제 설정 기록 | QA·운영, 백엔드 | I-OPS-01 |
| T-M12-02 | 입력 대기 | 운영 비밀 주입, 서버 밖 암호화 백업·별도 키 보관·복원 역할, 일일 정리/백업 스케줄, 로그 14일/회전, 디스크·사용량·실패 경보 수신과 첫 실행 증거 | QA·운영, DB | T-M12-01 |
| T-M12-03 | 대기 | 카탈로그·지식 게시/검토 기한·모델/차원·전송/보존 안내·생성 한도/중단·LH 운영 근거 부족 고지를 출시 버전에서 확인 | AI·RAG, QA·운영 | T-M12-01 |
| T-M12-04 | 대기 | 배포 전 백업 → 이전 API 종료 → DB 준비 → migration 1회 → 새 API 중단 요청 정리 → 단일 API/web 확인; 이미지·schema·자료 버전과 실행 결과 기록 | 백엔드, QA·운영 | T-M12-02, T-M12-03 |
| T-M12-05 | 대기 | 실제 운영의 비회원 설문/저장·회원 이력/독립 챗봇/초기화·사이트 내 답변·직접 문의·삭제/재로그인·권한/비밀 비노출·상담 생성 남용/공개 IP 인증 제한 검증 | QA·운영, 프론트, 백엔드 | T-M12-04 |
| T-M12-06 | 대기 | 실제 서버 밖 백업 복원·최신 삭제 재적용·RPO 24시간/RTO 4시간 측정·장애 대응·schema 호환 이미지 되돌리기 검증 | QA·운영, DB | T-M12-04 |
| T-M12-07 | 대기 | 운영 화면의 스크린리더·확대 최종 수동 인수 및 접근성 회귀 증거 | QA·운영, 프론트 | T-M12-04 |
| T-M12-08 | 대기 | 배포 이미지·자료/카탈로그/모델·필수 시험·남은 제한·운영 담당·인수일을 출시 기록에 남기고 최신 상태의 운영 범위를 갱신 | QA·운영 | T-M12-05, T-M12-06, T-M12-07 |

**완료 조건:** 실제 운영 Compose의 web·api·db에서 개정 MVP 흐름이 확인되고 백업·정리·복구·비용/장애 관측과 담당자 인수가 입증돼야 한다. 기존 로컬 `8080` 재배포, `18880` preview, 두 로컬 백업 사본만으로 충족하지 않는다. 미충족 조건은 그대로 남긴다.

## M15. 서비스 흐름의 진행 장애와 이해 개선

사용자가 요청한 최소 수정·선택적 설문 불러오기·UX별 커밋과 개발 8080 재배포/검증을 완료했다. 기존 작업의 기준 커밋은 c46ea96이다. 구현 ID·커밋·회귀는 [R027](records/27-ux08-focus-and-integration.md), 배포·실제 응답·데이터 보존은 [R028](records/28-ux15-local-redeployment.md)에 보존한다. 이 단계의 구현 대기 행은 없으며 실제 운영 인수는 M12로 남는다. 법적 판단 범위, 검토된 자료와 ID, 계정 격리는 유지한다.
