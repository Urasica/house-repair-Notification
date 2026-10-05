# M11 보존·삭제·백업과 통합 검증

구현/시험: 2026-10-05~06 · 로컬 적용: 2026-10-06(KST) · 스키마: 0005_m10

## 완료 범위

기한 정리·정제 질문 GROUP BY·명시 삭제 직후 별도 암호화 삭제 파일·실패 후 재실행·pg_dump 및 검토 파일 암호화 백업·두 저장 경로 검증·14일 정리·빈 DB 복원과 삭제 재적용을 구현했다. 복원 시 결과 FK를 먼저 조회해 요청 DELETED/null을 적용하며, 원본 삭제 마커도 복원 DB에 남겨 다음 내보내기에서 잊히지 않게 한다. 인증은 모두 취소하고 게시 지식은 WITHDRAWN으로 격리한다.

GitHub Actions에 실제 PostgreSQL/pgvector·API·계약·프론트·Playwright·복원·부하·장애 검증을 연결했다. remote가 없어 GitHub 호스팅 실행은 미실행이며 대응 명령을 로컬에서 검증했다. [실행 안내](../docs/14-retention-backup.md)를 따른다.

## 실행 결과

| 검증 | 결과 |
| --- | --- |
| 백엔드 | 최종 전체 237건 통과(실제 PostgreSQL 82건·독립 시험 155건); 챗봇 집계 회귀 포함 |
| 프론트 | Vitest 40건, 타입·린트·빌드, 생성 타입 일치 통과 |
| 계약/정적 검사 | OpenAPI snapshot 일치, Ruff/format, Alembic check 차이 없음 |
| 실제 브라우저 | Playwright Chromium 360×800의 회원/비회원 핵심 흐름 2건 통과; 검사 화면 axe WCAG A/AA 위반 0, 가로 넘침 없음, Tab 확인 |
| 백업/복원 | 실제 pg_dump→암호화→별도 DB 복원, 삭제 결과·질문 제거, 요청 DELETED/null·410, 검토 파일 바이트 일치, 게시 지식 격리 통과 |
| 장애 | 테스트 DB 중단 시 live=200·ready/catalog=503; DB 정상 뒤 준비 상태 복구 약 2.082초. 단일 API 재시작 명령 반환 후 약 2.066초 |
| 로컬 반영 | API/web/ops 이미지 반영, catalogReady=true·ragReady=true. 실제 삭제 즉시 내보내기·익명 토큰 401 차단 확인 |
| 실제 자료 백업 | 개발 DB와 M08 파일 29개, 암호화 결과 3,002,680 bytes, 약 0.746초. Git 제외 경로에 보관 |
| 실제 정리 | 만료 상담 5개·비회원 결과 1개 정리, 기한 내 회원 이력/정제 질문 유지. 변경 전 암호화 백업 확보 |

실행 증거: [복원](../data/operations/m11-20261006/backup-restore.json), [부하](../data/operations/m11-20261006/load.json), [장애](../data/operations/m11-20261006/outage.json), [로컬 삭제/준비 상태](../data/operations/m11-20261006/local-runtime.json). 날짜 필드는 UTC이며 원본 측정 시각을 유지한다. 암호화 백업·삭제 파일·키는 공개 증거에 포함하지 않는다.

20개 독립 상담의 동시 요청(하나의 시험 계정, OpenAI OFF)에서 카탈로그/상담/질문/회원 이력 각각 100회 p95가 176.95/145.99/200.05/168.72ms로 1.5초 목표를 통과했다. 설문 20회 p95 401.83ms, 챗봇 20회 406.74ms는 정보 부족/기본 응답 경로다. 실제 모델 지연을 이 값으로 주장하지 않는다. 10초/25초 전체 deadline과 제공자 실패는 기존 모의 실패 시험으로 검증했다.

작은 합성 자료의 백업 0.206초·복원/정리 0.143초, 복원 시 스냅샷 나이 0.240초를 측정했다. 임시 DB 생성·인프라/역할 준비·원격 다운로드·수동 검토·트래픽 전환을 포함한 운영 RTO가 아니다. RPO 24시간/RTO 4시간은 M12 실제 저장소/서버에서 다시 입증할 목표다.

## F01~F27 검증 대응

아래는 새 시험과 기존 회귀 시험의 대응이다. 실제 법령/모델 평가의 원본 결과는 M09/M10 증거를 유지한다. 이번 단계는 프롬프트·모델·자료를 변경하지 않아 실제 OpenAI 추가 호출은 0회다.

| QA | 검증 근거 |
| --- | --- |
| F01 | test_consultation_api 비회원 생성/평가/권한, Playwright 비회원 설문·복원·종료 |
| F02 | 회원 만료 이력 시험, test_retention 만료 상담 삭제 후 회원 결과 보존 |
| F03 | test_auth_api 소유권, test_chat 권한/타인 조회 |
| F04 | auth/flow DOM의 익명→회원 분리 및 저장소 초기화 |
| F05 | auth/chat DOM 캐시/늦은 응답 차단, Playwright 로그아웃 후 대화 미노출 |
| F06 | test_auth_api Origin/JSON/CSRF 및 쿠키 검증 |
| F07 | test_api_basics 빈 목록503, catalog publication gate |
| F08 | test_consultation_api revision/상위 선택 변경, flow DOM 충돌 복구 |
| F09 | catalog policy/guidance rules/test_m08a_catalog 실제 범위·모름·위험 |
| F10a | M09 평가셋의 **F10b**(운영 문의) 및 test_chat 목적/운영 gate |
| F10b | M09 평가셋의 **F10a**(명시 법령 설명) 및 M10 실제 생성 평가 |
| F10c | M09 F10c·불명확/혼합 질문, test_chat purpose |
| F11 | test_chat runtime 내부 검색→적격 확인→Responses 호출 |
| F12 | test_chat 무근거/외부 도구 차단·tools=[]·생성 생략 |
| F13 | test_knowledge 범위/해시/검토/별표 누락 반입 거절 |
| F14 | test_knowledge_runtime 반입/벡터 재사용/필수 문맥, M09 실제 49청크/53평가 |
| F15 | test_knowledge 승인/철회/기한/모델·차원 필터 |
| F16 | test_knowledge_runtime 설문 최종 철회, test_chat final withdrawal |
| F17 | test_chat Responses 오류/refusal/가짜 주장/조건/인용/시간 초과 |
| F18 | test_chat 생성 검증 및 guidance 안전/문의 연락처 차단 |
| F19 | test_consultation_api 최종 저장 실패, DB recovery 시험, 실제 outage drill |
| F20 | test_consultation_api 및 test_chat 재생/원자 저장, test_retention GROUP BY 중복 없음 |
| F21 | request repository/consultation/chat PROCESSING·FAILED·hash conflict |
| F22 | test_startup_recovery 실제 DB 중단 요청 FAILED, 취소/늦은 완료 차단, 실제 API restart |
| F23 | test_retention 기한 경계·2월29일·3/5년 설정·상담 정리·질문 독립 만료 |
| F24 | test_retention 집계/삭제/재시도/후속 마커, 실제 암호화 백업 복원 |
| F25 | catalog/chat prompt 공격·도구 차단, React 텍스트 렌더링/DOM 시험 |
| F26 | 결과 삭제 전 요청 FK 확인, 반복 삭제 적용·null/410 PostgreSQL 시험 및 pg_dump 복원 drill |
| F27 | chat API/DOM 표시 정보·isCurrent·재생 중복, Playwright 대화 새로고침 |

M09의 F10a/F10b 이름은 QA 표와 뒤바뀌어 있었다. 기존 평가 증거의 ID/내용을 소급 변경하지 않고 위 표로 대응을 명시했다. 기능 기대 결과는 일치한다. QA 문서의 오래된 'M01~03만 구현', 채팅 세션/IP 한도도 실제 M10 회원별 20회/10분·전체 100회/UTC일 기준으로 정정했다.

## 발견해서 수정한 문제

- 로그인 직후 인증 변경 효과가 새 홈의 공개 카탈로그 요청까지 취소/제거해 계속 대기했다. 계정 캐시 정리에서 공개 카탈로그를 제외하고 실제 브라우저로 재검증했다.
- 푸터의 명암 대비 4.32:1을 개선했다. 홈·설문·결과·대화의 자동 접근성 검사를 통과했다.
- 복원된 삭제 마커를 DB로 가져오지 않으면 다음 파일 내보내기에서 질문 단독 삭제를 잊을 수 있었다. 마커 재보존과 회귀 시험을 추가했다.
- 설문 질문 JSON은 selections 아래, 챗봇은 최상위에 시설·증상을 저장한다. GROUP BY에서 두 형태를 구분했다.

## M12로 이어지는 운영 조건

원격 저장소·호스트 스케줄러·실패 경보·로그 14일 보관·키 별도 보관·복원 역할 부여·유지보수/전환·실제 운영 RPO/RTO는 서버/도메인과 함께 M12에서 설정/검증해야 한다. M11의 remoteVerified는 **두 번째 로컬 대체 경로의 바이트 검증**이다. 실제 서버 밖 백업의 완료를 뜻하지 않는다.

자동 접근성 시험과 360px/Tab 검증은 완료했지만, 스크린리더·확대의 최종 수동 인수는 M12에 남아 있다. GH workflow 파일은 추가했지만 원격 CI 실행 성공으로 보고하지 않는다. 기존 LH 운영 근거 부족·법령 참고/설명 한정·자유 재서술 불허 정책은 유지한다. 이 조건을 충족하기 전에는 운영 출시 완료로 표시하지 않는다.
