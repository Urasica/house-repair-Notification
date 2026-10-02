# 백엔드 역할 설계 — FastAPI

상위 문서: [전체 안내](README.md) · 연계: [DB](04-database.md), [RAG](05-ai-rag.md), [운영](06-qa-operations.md)

## 1. 책임과 구조

FastAPI 한 앱이 계정·익명 세션·권한, 설문, 결과 저장·이력, 장기 질문 기록, 내부 RAG와 OpenAI 호출을 제어한다. PostgreSQL + pgvector 한 DB에 업무 데이터와 안내 지식을 함께 저장한다. 마이크로서비스·별도 작업 큐·캐시는 초기 구성에 없다.

SQLAlchemy 2·Psycopg 3·Alembic과 pgvector 연동을 사용하며 연결 풀·마이그레이션 이력은 각 하나다. 요청마다 독립 AsyncSession을 사용하고 create_async_engine으로 Psycopg 비동기 연결을 구성한다. 초기 API는 1개 워커이며 상담별 변경 잠금은 프로세스 메모리에 둔다. OpenAI HTTP 호출 중 DB 트랜잭션·행 잠금을 유지하지 않는다. [SQLAlchemy Psycopg 연동](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)

```text
backend/app/
  api/v1/                    # auth, catalog, sessions, guidance, chat, history
  auth/                      # 계정 쿠키·익명 토큰·소유권·CSRF
  schemas/                   # Pydantic·OpenAPI
  services/                  # 상담 처리·질문 기록·이력
  domain/                    # 범위·안전·필수 정보 판단
  db/                        # 단일 DB 모델·연결·마이그레이션
  rag/                       # 검색·주장·인용 검증
  integrations/openai/       # Responses·Embeddings
  commands/                  # 검토 완료 자료 반입·임베딩·게시·정리
```

자료 반입·임베딩·게시와 사용자 응답은 별도 흐름이다. 관리 명령은 API와 같은 이미지에서 일회성으로 실행하며 상시 워커를 두지 않는다. 원문 추출은 사용자가 지시할 때 컴퓨터 유즈로 수행한다. 서비스가 답변용 외부 검색을 실행하지 않는다.

## 2. 인증·권한

계정은 이메일·비밀번호로 가입·로그인하며 비밀번호는 Argon2id 해시만 저장한다. 로그인 시 충분한 난수의 계정 인증 토큰을 HttpOnly·Secure·SameSite=Lax 쿠키로 발급하고 DB에는 해시만 저장한다. 계정 인증은 기본 24시간이며 만료 후 재로그인한다. 비밀번호·쿠키 토큰은 응답 JSON·로그에 포함하지 않는다.

비회원 설문은 별도 256비트 이상 익명 Bearer 토큰을 발급한다. 토큰은 해당 세션의 설문·현재 결과만 허용하며 계정 인증이 아니다. 서버는 다음을 확인한다.

| 기능 | 인증 조건 |
| --- | --- |
| 설문·맥락·현재 결과 | 유효한 익명 토큰 또는 세션 소유 계정 쿠키 |
| 챗봇·대화·챗봇 요청 상태 | 로그인 계정 + 회원 소유 세션 |
| 이전 결과 목록·상세·삭제 | 로그인 계정 + 결과 owner_user_id 일치 |

계정 쿠키를 사용하는 POST/PUT/DELETE는 X-CSRF-Token과 허용 Origin을 확인한다. 로그인·가입처럼 인증 쿠키를 만들기 전의 JSON 요청도 허용 Origin·Content-Type을 확인한다. 웹·API는 같은 사이트의 프록시 경로로 제공한다. CORS는 설정한 웹 origin만 허용한다.

계정 인증 없음·만료는 401 AUTH_REQUIRED/AUTH_EXPIRED다. 익명 토큰 없음·만료는 401 UNAUTHORIZED/SESSION_EXPIRED다. 유효한 인증으로 다른 사용자의 자원에 접근하면 404다. 본인 익명 세션을 조회할 수 있어도 챗봇 권한은 부여되지 않는다.

## 3. API 목록

경로는 /api/v1 기준이며 health는 최상위 경로다. JSON은 camelCase, 시간은 UTC RFC 3339다. 사용자 응답에는 Cache-Control: no-store를 적용한다.

| 메서드·경로 | 인증·입력 | 응답 |
| --- | --- | --- |
| GET /catalog?version=... | 공개, 게시 버전 선택 | 200 Catalog; 미완성 시 503 CATALOG_NOT_READY |
| POST /auth/register | 공개, email·password | 201 User; 가입 뒤 로그인은 별도 |
| POST /auth/login | 공개, email·password | 200 AuthState + 쿠키 |
| GET /auth/me | 선택적 쿠키 | 200 AuthState; 비로그인은 user·csrfToken=null |
| POST /auth/logout | 계정·CSRF | 204, 쿠키·인증 세션 폐기 |
| POST /sessions | 선택적 계정, catalogVersion | 201 {session, sessionToken}; 회원 token=null |
| GET /sessions/{id} | 세션 소유권 | 200 Session |
| PUT /sessions/{id}/context | 세션 소유권, expectedRevision·context | 200 Session |
| GET /sessions/{id}/questions | 세션 소유권 | 200 {catalogVersion, revision, questions} |
| POST /sessions/{id}/evaluations | 세션 소유권, requestId·expectedRevision | 201 GuidanceResult; 완료 재생은 200 |
| GET /sessions/{id}/results/{resultId} | 세션 소유권 | 200 GuidanceResult |
| GET/POST /sessions/{id}/chat/messages | 회원 소유권; POST requestId·expectedRevision·content | 200 메시지 목록 또는 ChatResponse |
| GET /sessions/{id}/requests/{requestId} | 평가: 세션 소유권; 채팅: 회원 | 200 RequestState |
| DELETE /sessions/{id} | 세션 소유권 | 204 상담 종료; 장기 기록 일괄 삭제와 구분 |
| GET /me/results?cursor=...&limit=... | 계정 | 200 {items, nextCursor} |
| GET/DELETE /me/results/{resultId} | 결과 소유 계정 | 200 GuidanceResult 또는 204 삭제 |
| DELETE /me/question-records | 계정·CSRF | 204 본인 장기 질문 기록 삭제 |
| GET /health/live | 공개 | 200 {status: "ok"} |
| GET /health/ready | 공개 | DB·필수 설정 점검; catalogReady·ragReady 별도 상태 |

목록 limit는 기본 20·최대 50이며 cursor는 서버가 만든 불투명한 위치값이다. 가입 email은 정규화·중복 검사하고 password는 12~128자로 제한한다. User는 {id, email, createdAt}, AuthState는 {user: User 또는 null, csrfToken: string 또는 null}이다. 가입·로그인은 시도 제한과 일반화된 인증 실패 응답을 사용한다.

세션 생성은 최신 완성 카탈로그만 허용한다. 이전 버전 요청은 409 CATALOG_UPDATED다. 기존 세션 복구를 위해 게시된 과거 카탈로그 조회는 허용한다. 목록이 없으면 예시 카탈로그를 seed해 공개하지 않는다.

## 4. 공통 모델

Catalog는 version·publishedAt·housingTypes·rooms·facilities·symptoms를 갖는다. 항목에는 ID·label·연결 ID·aliases를 둔다. 원본 질문·조건은 catalogs.payload_json에 저장하고 표시 질문은 questions API로 계산한다. 기존 예시 증상 ID는 실제 카탈로그에 넣지 않는다.

```typescript
type Context = {
  housingType: "LH_CONSTRUCTION_RENTAL" | "LH_RENTAL_BEFORE_SALE"
    | "SOLD_OR_PRIVATE" | "OTHER" | "UNKNOWN" | null;
  roomId: string | null;
  facilityId: string | null;
  symptomId: string | null;
  description: string; // 0~1,000자
  answers: Record<string, string>;
};

type Session = {
  id: string;
  accessMode: "GUEST" | "MEMBER";
  catalogVersion: string;
  knowledgeReleaseId: string | null;
  revision: number;
  context: Context;
  currentResultId: string | null;
  createdAt: string;
  expiresAt: string;
};

type Question = {
  questionId: string;
  type: "singleChoice";
  label: string;
  required: boolean;
  options: {value: string; label: string}[];
  interruptValues: string[];
};
```

revision은 생성 시 0이다. 맥락 전체를 expectedRevision과 저장하고 실제 변경 시 1 증가한다. 부모 변경으로 무효가 된 하위 선택·숨겨진 답은 정리한다. 알 수 없는 ID·옵션·입력 필드는 422다. 모름은 정상 선택이다.

knowledgeReleaseId는 DB의 knowledge_sets.id에 대응하며 세션 카탈로그와 호환되는 최신 PUBLISHED 지식 묶음을 고정한다. 카탈로그 버전은 FK와 게시 검증으로 확인한다. 게시 지식이 없으면 null로 시작하고 기본 안내를 제공한다. DB에 접근할 수 없으면 세션 저장도 불가능하므로 503으로 실패한다.

```typescript
type GuidanceStatus = "SAFETY_PRIORITY" | "OUT_OF_SCOPE" | "NEED_MORE_INFO"
  | "NEED_CONFIRMATION" | "GUIDANCE_AVAILABLE";

type Citation = {
  chunkId: string;
  documentVersionId: string;
  kind: "LAW_CRITERIA" | "LH_OPERATION" | "SAFETY_SOURCE";
  use: "RELATED" | "APPLICABLE";
  title: string;
  locator: string;
  url: string;
  effectiveDate: string | null;
  reviewedAt: string;
  reviewUntil: string;
};

type GuidanceResult = {
  id: string;
  sessionId: string | null; // 단기 세션 정리 후 null
  savedToHistory: boolean;
  catalogVersion: string;
  knowledgeReleaseId: string | null;
  contextRevision: number;
  status: GuidanceStatus;
  reasonCodes: string[];
  summary: {housingLabel: string; roomLabel: string; facilityLabel: string;
    symptomLabel: string; description: string; answerLabels: string[]};
  guidance: string[];
  checks: string[];
  followUpQuestions: string[];
  contactDraft: string;
  citations: Citation[];
  disclaimer: string;
  engineVersion: string;
  generatedAt: string;
  retainedUntil: string;
  isCurrent: boolean;
};
```

reasonCodes는 HAZARD_SIGNAL, HOUSING_OUT_OF_SCOPE, MISSING_INPUT, NO_APPLICABLE_SOURCE, SOURCE_CONFLICT, SOURCE_UNAVAILABLE, MATCHED_OPERATION_RULE이다. 회원 이력 목록은 id·generatedAt·status·summary·retainedUntil의 축약형을 반환한다.

결과·입력·인용은 생성 시 스냅샷으로 저장한다. isCurrent는 현재 유효한 세션 revision·정책과 근거 적격 상태를 조회해 계산한다. 만료 세션의 회원 이력은 조회할 수 있지만 현재 상담 결과로 표시하지 않는다. 단일 DB 장애 시 서버 이력 조회도 503으로 실패한다.

```typescript
type ChatMessage = {id: string; requestId: string; role: "USER" | "ASSISTANT";
  content: string; citations: Citation[]; createdAt: string; isCurrent: boolean};

type ChatResponse = {requestId: string; contextRevision: number;
  answerMode: "GROUNDED" | "CLARIFY" | "TEMPLATE"; status: GuidanceStatus;
  userMessage: ChatMessage; assistantMessage: ChatMessage;
  followUpQuestions: string[]; disclaimer: string; isCurrent: boolean};

type RequestState = {requestId: string; kind: "SURVEY" | "CHAT";
  state: "PROCESSING" | "COMPLETED" | "FAILED";
  retryAfterMs: number | null; response: GuidanceResult | ChatResponse | null};
```

회원 채팅은 1~2,000자이며 공백만 있으면 거부한다. 실패한 처리 중 입력은 완료 대화 목록에 넣지 않는다. 원본 대화의 단기 저장과 장기 질문 기록은 분리한다.

## 5. 설문·RAG·OpenAI 처리

처리 순서는 검토된 위험 신호 → 범위 → 필수 정보 → 내부 RAG 적격 근거·충돌 → 안내다. 지원 범위·정보 부족·직접 문의의 기본 정책은 자료가 없어도 실행한다.

설문은 완성 목록의 선택·답을 검색 질문으로 만들고 PostgreSQL + pgvector에서 근거를 찾는다. 필요하면 OpenAI Embeddings를 호출하지만 OpenAI 답변 생성은 사용하지 않는다. 적격 안내 템플릿·규칙이 없으면 NEED_CONFIRMATION과 연락처 없는 직접 문의 문구를 만든다. 법령 자료만으로 LH 운영 결론을 확정하지 않는다.

회원 챗봇은 같은 판단·검색을 거친 뒤 OpenAI Responses API를 호출한다. tools=[]로 웹 검색·브라우징·MCP·임의 URL 요청을 제공하지 않는다. 적격 근거가 없으면 생성 호출 없이 직접 문의 템플릿을 반환한다. 근거가 있더라도 모델 사전 지식의 기간·비용·보수 조건을 추가하지 못하게 검증한다. 구체 계약·모델 설정은 05를 따른다.

사용자의 질문 통계는 자료 개선용이며 RAG 지식으로 자동 복사하지 않는다. 서버는 입력·대화·근거 중 식별정보를 제거한 최소 내용만 OpenAI에 전달한다. 결과 문구·안전 안내·문의 문구에서 전화번호·이메일·연락처 패턴이 검출되면 제거 또는 템플릿 대체한다. 출처 URL은 검토된 원문 확인용만 허용한다.

## 6. 단일 프로세스 동시성·중복 방지

설문 평가와 채팅 모두 request_runs의 (consultation_id, request_id) UNIQUE로 중복을 구분한다. 요청 ID·입력 해시·PROCESSING/COMPLETED/FAILED·완료 응답만 저장한다. 영속 큐·lease·attempt·자동 재처리는 없다. 평가 예산은 임베딩·검색 포함 10초, 채팅은 포함 25초다.

1. 인증·기능 권한을 검사한다. 같은 ID의 kind·본문·expectedRevision이 다르면 409 IDEMPOTENCY_CONFLICT다. COMPLETED는 추가 검색·모델 호출 없이 응답을 재생하고 isCurrent를 다시 계산한다. PROCESSING은 409 REQUEST_IN_PROGRESS, FAILED는 409 REQUEST_FAILED다.
2. 상담별 메모리 잠금을 즉시 획득한다. 다른 변경이 실행 중이면 409 SESSION_BUSY다. 맥락 저장·평가·채팅·상담 삭제·연결된 결과 삭제에도 같은 잠금을 적용하며 읽기는 허용한다. 계정 질문 일괄 삭제도 연결된 상담의 동일 잠금을 확인·획득해 실행 중인 요청과 겹치지 않는다. 서로 다른 상담은 비동기로 함께 처리한다.
3. 짧은 DB 트랜잭션에서 소유권·revision·한도를 확인하고 PROCESSING을 기록한다. 트랜잭션을 닫고 내부 검색·OpenAI·출력 검증을 수행한다.
4. 마지막 짧은 **단일 DB 트랜잭션**에서 요청이 여전히 PROCESSING인지, 세션·계정 인증·revision·근거가 유효한지 확인한다. 필요한 지식 묶음·원문 행을 잠그고 결과 또는 메시지, 정제 질문, 요청 완료를 함께 커밋한다. 저장 실패는 503이며 성공으로 표시하지 않는다.
5. OpenAI 장애·자료 부족은 DB가 정상인 경우 연락처 없는 TEMPLATE/CLARIFY로 완료한다. 예상하지 못한 실패·취소는 가능한 짧은 정리 트랜잭션으로 FAILED를 기록하고 잠금을 해제한다. 실패 또는 취소가 확정된 작업의 늦은 응답은 완료 조건을 통과하지 못하며 저장하지 않는다.

GET .../requests/{requestId}는 상태를 조회한다. 실패한 ID를 다시 실행하지 않으며, 사용자가 실패를 확인하고 재시도할 때 새 ID를 발급한다. 응답 유실은 먼저 같은 ID로 확인하므로 완료 기록·질문 통계·메시지가 늘지 않는다.

프로세스 재시작은 이전 프로세스가 완전히 종료된 후 수행한다. 새 프로세스가 요청을 받기 전에 남은 PROCESSING을 FAILED로 바꾼다. 실행 중 DB 장애로 실패 정리도 불가능했다면 새 변경을 막고 활성 변경 요청을 취소·종료한 뒤, DB 복구 후 남은 PROCESSING을 FAILED로 정리한다. 그동안 readiness는 실패다. 외부 호출 이후 중단·명시적 재시도에 따른 추가 API 과금까지 한 번으로 보장하지 않는다.

이 방식은 **API 1개 워커·겹치지 않는 배포** 조건에 한정한다. 여러 워커·여러 서버를 도입할 때 상담 실행 제어·중단 복구·사용량 제한을 DB 기반 공유 방식으로 바꾸고 검증한다. Redis·큐를 미리 도입하지 않는다.

## 7. 저장·이력·장기 질문

모든 설문 평가 결과를 PostgreSQL에 저장한다. 회원은 owner_user_id를 지정하고 세션 만료와 독립적으로 기본 5년 보관한다. 비회원은 owner_user_id=null이며 expires_at+7일 이내 원본 결과를 삭제한다. 비회원의 현재 조회 권한은 세션 24시간으로 제한한다.

회원 이력에는 로그인 상태에서 생성한 결과만 연결한다. 비회원에서 로그인하면 새 회원 상담을 시작한다. 익명 결과의 계정 이전은 초기 범위에서 제외한다. 로그아웃·세션 종료는 계정 이력을 삭제하지 않는다. DELETE /me/results/{id}는 본인 결과·연결된 질문 기록·재생 캐시를 삭제하고 복구용 삭제 기록을 남긴다.

장기 question_records에는 설문 질문·답 코드·당시 라벨, 정제된 질문 내용, 카탈로그 버전, SURVEY/CHAT 구분, 상태, 검색 청크 ID·점수 등의 제한된 메타데이터를 저장한다. origin_key UNIQUE로 요청당 한 번만 기록한다. 비회원·회원 모두 적용하며 기본 5년·허용 범위 3~5년이다. 주요 질문은 GROUP BY로 집계하고 미리 계산한 통계 테이블은 두지 않는다. 원본 비밀번호·토큰·IP·연락처는 포함하지 않는다.

세션 DELETE는 상담 종료다. 원본 세션·대화·요청은 정리하고 장기 정제 질문·회원 이력은 정해진 기간에 유지한다. 현재 익명 세션의 장기 질문까지 삭제하려면 DELETE /sessions/{id}?eraseRecords=true를 사용한다. 회원은 결과별 또는 /me/question-records로 명시적으로 삭제할 수 있다. 명시적 삭제가 장기 보존보다 우선한다.

## 8. 오류·운영과 인수 조건

```json
{"error":{"code":"AUTH_REQUIRED","message":"로그인 후 이용해 주세요.","details":{},"traceId":"public-correlation-id"}}
```

401 인증·만료, 404 타인·없는 자원, 409 카탈로그·맥락·요청 충돌, 422 입력 오류, 429 RATE_LIMITED, 503 SERVICE_UNAVAILABLE/CATALOG_NOT_READY로 통일한다. 부족한 정보·범위 밖·자료 없음은 정상 2xx 안내 결과다. 내부 SQL·모델 원문·비밀은 오류 details에 넣지 않는다.

ready는 DB·필수 설정·중단 요청 정리 여부를 확인한다. catalogReady=false여도 준비 중 화면을 제공할 수 있으나 상담 시작은 CATALOG_NOT_READY다. 지식 미게시·OpenAI 비활성은 ragReady=false로 표시하며 DB가 정상이면 기본 안내·회원 이력을 유지한다. DB 장애는 ready와 저장·이력 조회를 503으로 실패시킨다. 마이그레이션·자료 반입·만료 정리는 같은 이미지의 일회성 관리 명령이다.

- 비회원 채팅과 계정 이력 접근을 서버에서 차단한다.
- 양쪽 설문 결과 저장·회원 과거 조회·로그인 후 새 상담이 검증된다.
- 단기 세션 삭제가 회원 이력·정제 질문을 CASCADE로 지우지 않는다.
- 근거가 없으면 외부 검색·모델 추측 없이 연락처 없는 직접 문의를 반환한다.
- 재시도에서 결과·질문 통계·대화가 중복되지 않는다.
- 자료 철회·OpenAI 장애가 안내 정책을 우회하지 않으며 단일 DB 실패는 503이다.
- 초기 Compose의 API가 1개 워커로 실행되고 재시작 시 중단 요청이 정리된다.
