# 회원 챗봇 생성·저장·한도

이 문서는 챗봇의 검색 이후 생성·검증·저장과 사용량을 정의한다. 이용·초기화·추가 확인은 [챗봇 정책](../product/chat.md), HTTP 계약은 [API](../backend/api.md)를 따른다.

## 대화 처리와 저장

로그인 후 별도 CHAT 세션에서 질문한다. 설문 선택·답변·결과를 요구하거나 복사하지 않는다. 회원 소유 상담만 대화 조회·전송·요청 상태를 이용할 수 있다. 원문 질문은 1~2,000자이며 화면에는 일반 텍스트로 표시한다. 입력에서 링크를 발견해도 방문하지 않는다.

GET `/sessions/{id}/chat/messages`는 COMPLETED CHAT 요청의 질문·답변 쌍을 created_at·id 오름차순으로 반환한다. 기본 20쌍·최대 50쌍이며 nextCursor로 이어서 조회한다. answerMode·status·followUpQuestions·disclaimer를 함께 복원한다. 조회·같은 requestId 재생은 추가 생성이나 질문 저장을 하지 않는다. 현재 revision·정책 버전·생성 모델·필수 근거 적격성을 다시 검사해 isCurrent를 계산한다.

POST는 기존 상담 잠금과 요청 저장소를 재사용한다. 예약 후 DB 트랜잭션을 닫고 검색·생성하며, 최종 트랜잭션에서 회원 인증·revision·근거 철회·PROCESSING을 재검사한다. 두 메시지·정제 질문·완료 응답은 함께 저장한다. 취소·예상하지 못한 실패는 FAILED이며 늦은 응답이 기록을 만들지 못한다. PostgreSQL 실패는 503이다.

브라우저는 처리 중 requestId·expectedRevision만 sessionStorage에 보관한다. 질문은 메모리에만 있고 새로고침 뒤에는 완료 상태를 먼저 확인한다. 원문이 사라진 미접수 요청은 사용자가 다시 입력한다. 자동 새 ID 재시도·자동 polling은 없다. 로그아웃·계정 변경·상담 만료 때 대화 캐시와 처리 중 ID를 제거하고 늦은 응답을 무시한다.

원본 대화는 단기 상담에 연결되며 상담 종료 시 삭제된다. 장기 질문에는 목적/명시적 조문 번호와 선택 코드만 남기며 자유 입력을 복사하지 않는다. 질문 기록 삭제 후 같은 완료 요청을 재생해도 질문이 복원되지 않는다. 기간별 정리·백업 복원은 [운영 절차](../operations/retention-backup.md)를 따른다.

## 생성·검증 범위

`gpt-5.4-mini` Responses API에 tools=[], store=false, reasoning.effort=none, 엄격한 JSON Schema를 사용한다. HTTP 클라이언트는 자동 재시도·리디렉션·환경 프록시를 사용하지 않으며 목적지는 api.openai.com/v1/responses로 고정한다. [모델](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)를 참고한다.

서버는 위험·범위·필수 정보 → 내부 검색/적격성 → 생성을 적용한다. 명시적 위험 표현은 일반 안내를 중단하고 기본 안전 확인 문구로 처리한다. 법령 설명만 APPLICABLE 법령으로 생성하며 LH 운영·혼합·불명확 문의는 적격 운영 근거가 없으면 TEMPLATE다. 제35조 등 미검증 외부 규정에 의존하는 조문과 별표 4는 설명 게이트를 열지 않는다.

생성 계약은 **검토된 조문 전체 또는 승인 운영 문구를 선택해 제시하는 방식**이다. 자유로운 재서술의 의미 정확성을 자동으로 보장한다고 주장하지 않는다. 모델 문자열과 인용 ID가 승인된 전체 문구에 정확히 대응해야 하며 필요한 조문·조건이 모두 포함되어야 한다. 숫자만 맞거나 실제 ID를 붙인 임의 주장, 단서 생략, 새 질문, 연락처, URL은 통과하지 못한다. 연결 별표는 서버가 모든 열·행·비고를 원문 데이터에서 조립한다. 출처 제목·위치·URL·날짜는 DB 값만 사용한다. 별표/총칙/부칙도 검색 묶음에 포함하고 최종 유효성을 검사한다.

OpenAI에는 현재 질문의 목적·명시적 조문 번호, CHAT 대화에서 확인한 검토 카탈로그 라벨, 최근 최대 6개 메시지에서 같은 방식으로 추출한 분류/조문 번호, 적격 근거만 전달한다. 이름·주소를 정규식으로 완벽히 제거한다고 가정하지 않으며 자유 입력 전체를 전송 대상에서 제외한다. 원문 대화는 서버의 단기 이력에만 남는다. 이전 모델 답변은 근거가 아니다.

평가는 검토 원문 선택·인용 계약을 검증한다. 일반 자유 질문의 추론·자연스러운 의역·법률 정확도 전반이나 사람의 법률 검토를 대신하는 성능 평가로 해석하지 않는다. 자료 부족·모델 오류·refusal·형식/주장 검증 실패는 연락처 없는 TEMPLATE다.

## 한도와 실행

임베딩 모델은 text-embedding-3-large·1536차원이며 사용자 요청대로 총비용 상한은 없다. 채팅 전체 deadline은 25초, 외부 단계는 저장 여유 2초를 남기고 남은 예산을 공유한다. 질문 임베딩 최대 5초·생성 최대 20초, 입력 JSON 최대 60,000 UTF-8 바이트·출력 기본 4,096토큰이다. 과도한 자료는 잘라서 조건을 누락하지 않고 기본 안내로 전환한다.

CHAT_USER_WINDOW_LIMIT=20은 회원별 10분, CHAT_DAILY_LIMIT=100은 서비스 전체 UTC 하루의 새 채팅 예약 한도다. 모델 호출이 없는 템플릿·실패도 보수적으로 계수한다. 완료 재생은 계수하지 않는다. CHAT_MAX_OUTPUT_TOKENS로 출력 한도를 설정한다. 데이터 공유 무료 사용량의 실제 계정 자격은 별도이며 이 구현이 무료 과금을 보장하지 않는다.

chat_usage는 사용량 예약 기록이다. 질문·응답·요청 ID 없이 회원 ID와 예약 시각만 저장하므로 상담 삭제·재시작으로 한도가 초기화되지 않는다. 2일보다 오래된 사용량 행은 다음 예약 검사에서 제거한다. 한도 검사·예약은 단일 API 프로세스에서 짧게 직렬화한다. 다중 워커는 지원하지 않는다.

서비스 실행·migration은 [로컬 개발](../development/local.md)과 [배포](../operations/deployment.md)를 따른다.

다음 명령은 명시적으로 실행할 때 실제 OpenAI를 호출한다. REVIEW_DIR은 호스트의 평가 자료 절대 경로, RELEASE_ID는 평가할 게시 지식 ID, OUTPUT_PATH는 결과 저장 경로로 바꾼다. 평상시 회귀 시험은 격리 시험 DB·mock을 사용한다. API 키·계정 비밀·원문 대화는 출력하지 않는다.

```sh
docker compose --env-file .env run --rm --no-deps --volume REVIEW_DIR:/review api python -m app.commands.evaluate_chat --release-id RELEASE_ID --cases /review/evaluation-cases.json --output /review/evaluation-report.json
backend/.venv/Scripts/python.exe scripts/smoke_chat.py --allow-live-generation --output OUTPUT_PATH
```

관리 평가 명령은 20건 이하 합성 질문만 허용하며 런타임의 일일 예약 한도와 별개로 실행한다. API smoke는 합성 계정을 만들고 대화·질문을 삭제한 뒤 로그아웃한다. 합성 계정 자체는 보존된다. 계정 삭제 기능은 현재 범위에 없다.
