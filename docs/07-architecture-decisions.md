# 설계 결정과 단순화 기록

작성: 2026-10-03 · 상태: M01~M03 기반 구현 완료·후속 기능 설계

상위 문서: [전체 안내](README.md) · 연계: [DB 설계](04-database.md), [운영 설계](06-qa-operations.md), [확장 기준과 구현 순서](08-scaling-roadmap.md)

이 문서는 초기 규모에 맞춘 DB 선택·단순화 판단과 기술 선택 근거를 기록한다. 현재 기본 구성은 전체 안내를, 역할별 구현 기준은 각 설계 문서를 따른다.

## 1. 초기 설계 점검

**초기에는 PostgreSQL + pgvector 하나에 업무 데이터와 RAG를 함께 저장한다.** 앞서 제안한 MySQL + PostgreSQL 구성은 기능상 가능하지만, 적은 사용자와 소규모 자료에서는 두 연결·마이그레이션·백업과 DB 간 정합성을 운영할 이점이 부족하다. pgvector는 PostgreSQL의 일반 데이터와 벡터를 함께 저장할 수 있어 단일 DB로 요구를 충족한다. 이는 공식 기능을 근거로 한 프로젝트 판단이다. [pgvector 공식 문서](https://github.com/pgvector/pgvector)

이전의 업무 데이터 MySQL 지정은 설계 점검에서 **PostgreSQL 통합 기본안으로 변경**했다. MySQL을 반드시 사용해야 하는 외부 제약이 생기면 두 저장소 방안을 재검토한다. M01~M03에서 PostgreSQL 기반을 구현·검증했으며 MySQL에서 이전할 실제 서비스 데이터는 없다. 회원·설문·RAG·운영 배포는 후속 단계다.

| 점검 대상 | 초기 결정 | 이유 |
| --- | --- | --- |
| MySQL + PostgreSQL 두 DB | PostgreSQL + pgvector 한 DB | 운영·FK·트랜잭션·복구 경로 통합 |
| 별도 서비스·워커·큐·캐시 | FastAPI 한 앱, API 1개 워커 | 현재 요청과 자료 작업은 분리된 대규모 시스템이 필요하지 않음 |
| DB 간 공유 잠금·동기화 | 같은 DB의 짧은 완료 트랜잭션 | 외부 모델 호출 중 트랜잭션은 열지 않음 |
| lease·attempt 기반 재처리 | 요청 ID·완료 응답 저장·명시적 실패·본문 없는 삭제 상태 | 자동 작업 재시도 제외; 삭제된 요청 재실행 차단 |
| 사전 집계 통계 테이블 | 정제 질문 기록을 SQL GROUP BY로 조회 | 집계 중복·삭제 보정 제거 |
| 자료별 staging·검토·프로필 테이블 | 정리 파일·검토표 + 지식 묶음·문서·청크 | 검토 게이트는 유지하고 일반화된 관리 구조는 축소 |
| 청크·임베딩 별도 테이블 | 청크 행에 임베딩 포함 | 초기에는 한 모델·차원만 운영 |
| HNSW·재순위 모델·복합 검색 프레임워크 | pgvector 정확 검색 + 적용 조건 | 품질·지연을 측정한 뒤 추가 |
| 익명 결과의 계정 이전 | 후속 기능 | 초기 회원 이력은 로그인 상태에서 생성한 결과로 제한 |
| 여러 폼 검증 라이브러리 | React Hook Form·간단한 UI 검사 | 서버 Pydantic 검증 유지, Zod는 복잡한 폼이 필요할 때 |

권한·CSRF·결과 저장·중복 저장 방지·근거 검증·삭제·백업은 현재 요구에 필요하므로 유지한다. 확장성은 별도 시스템을 미리 운영하는 대신 기능 경계·안정적인 ID·마이그레이션으로 확보한다.

## 2. 프레임워크 선택

프론트 TypeScript와 백엔드 FastAPI는 유지한다. 현재 화면은 정적 웹과 API로 제공할 수 있어 Vite 빌드가 맞고, SSR을 위한 별도 웹 서버를 추가할 근거가 없다. FastAPI는 API와 Python 기반 RAG 처리의 경계를 한 앱에서 유지하기에 적합하다. 이번 규모에서는 프레임워크 교체보다 DB·운영 구성을 줄이는 효과가 크다고 판단한다. [Vite 정적 배포](https://vite.dev/guide/static-deploy.html), [FastAPI Docker 배포](https://fastapi.tiangolo.com/deployment/docker/)

## 3. 배포 선택과 운영 한계

한 서버의 Docker Compose에서 web·api·db 3개 상시 서비스를 운영한다. web에 React 정적 파일·Caddy HTTPS·API 프록시를 함께 두고 API는 초기 1개 워커로 실행한다. 자료 반입·임베딩·게시·정리는 API 이미지의 일회성 관리 명령으로 처리한다. [Caddy HTTPS](https://caddyserver.com/docs/automatic-https), [Docker Compose 운영 문서](https://docs.docker.com/compose/how-tos/production/)

단일 서버·단일 DB 구성은 운영 절차를 줄이지만 무중단·고가용성을 보장하지 않는다. DB 장애 시 결과 저장·이력 조회도 중단된다. 여러 API 워커를 추가하기 전에는 현재의 메모리 상담 잠금을 DB 기반 실행 제어로 바꿔야 한다. 배포·백업·복구 절차는 운영 설계를, 구조 변경 조건은 확장 기준 문서를 따른다.
