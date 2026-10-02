# 프론트엔드 역할 설계 — TypeScript

상위 문서: [전체 안내](README.md) · 정책: [기획·UX](01-product-ux.md) · 계약: [API](03-backend.md)

## 1. 역할과 구성

React + TypeScript + Vite, React Router, TanStack Query, React Hook Form을 사용한다. 기본 5개 상담 화면에 로그인·가입과 이전 결과 화면을 추가한다. 입력 길이·필수 값은 폼 규칙으로 검사하고 서버의 Pydantic 검증을 기준으로 한다. 초기에는 Zod·전역 상태 라이브러리·SSR 서버를 추가하지 않는다. RAG 검색·판단·모델 호출·권한 검증은 서버 책임이다.

```text
frontend/src/
  app/                        # Router, QueryClient, 인증 초기화
  pages/                      # Home, Select, Survey, Chat, Result, Login, History
  features/auth/              # 로그인·가입·로그아웃·CSRF
  features/consultation/      # 세션·맥락·설문 저장
  features/chat/              # 회원 대화·요청 복구
  features/history/           # 본인 결과 목록·상세·삭제
  components/                 # Field, Alert, SourceGroups, ContactDraft
  api/generated/              # OpenAPI 타입; 직접 수정 금지
  styles/                     # 디자인 토큰·반응형
  test/                       # 테스트 전용 합성 데이터
```

## 2. 인증과 권한

로그인 계정은 서버의 HttpOnly·Secure·SameSite=Lax 쿠키를 사용한다. 브라우저 저장소에 계정 토큰·비밀번호를 저장하지 않는다. 앱 초기화 시 GET /auth/me로 로그인 상태와 CSRF 토큰을 조회한다. 계정 쿠키를 사용하는 변경 요청에 X-CSRF-Token을 보낸다. 자세한 예외·Origin 정책은 03을 따른다.

비로그인 설문 세션만 sessionStorage에 세션 ID·익명 Bearer 토큰·만료 시각을 보관한다. 토큰·입력은 URL에 넣지 않는다. 회원 상담은 세션 ID만 보관하고 계정 쿠키로 소유권을 확인한다. 쿠키 인증과 익명 토큰을 같은 것으로 취급하지 않는다.

| 경로 | 조건 | 행동 |
| --- | --- | --- |
| `/`, `/login` | 공개 | 소개·로그인·가입 |
| `/select`, `/survey` | 유효한 본인 상담 세션 | 비회원·회원 모두 사용 |
| `/result/:resultId` | 현재 본인 세션 또는 결과 소유 계정 | 현재 결과 조회 |
| `/chat` | 로그인 | 미로그인 시 로그인 안내, 전송 불가 |
| `/history`, `/history/:resultId` | 로그인 | 본인 결과만 목록·상세 조회 |

계정 인증이 만료되면 챗봇·이력 캐시를 제거하고 로그인으로 안내한다. 비회원은 새 익명 설문을 시작할 수 있다. 로그아웃 때 모든 사용자별 Query 캐시·계정 상담 ID를 지운다. 공유 기기에서 이전 계정 결과를 재사용하지 않는다.

## 3. 화면과 카탈로그

| 화면 | 주요 구성 | API |
| --- | --- | --- |
| 홈 | 서비스 설명, 설문, 로그인, 회원 챗봇·이력 | GET /catalog, POST /sessions |
| 선택 | 게시된 주택·공간·시설물·증상, 요약 | PUT .../context |
| 설문 | 서버 singleChoice 질문, 진행·모름·오류 | GET .../questions, PUT .../context, POST .../evaluations |
| 챗봇 | 회원 대화·입력·근거·맥락 확인 | GET/POST .../chat/messages |
| 현재 결과 | 상태·안내·출처·문의 문구·저장 여부 | GET .../results/{resultId} |
| 로그인·가입 | 이메일·비밀번호, 복귀 경로 | POST /auth/register, /auth/login |
| 이력 | 날짜·요약·상태, 상세·삭제 | GET /me/results, GET/DELETE /me/results/{resultId} |

경로는 /api/v1을 생략했다. 질문·증상은 완성 목록을 게시한 카탈로그에서만 받는다. 기존 예시 항목·임의 증상·임시 ID를 제품 화면에 넣지 않는다. CATALOG_NOT_READY면 준비 중 표시와 홈 복귀를 제공한다. 테스트 합성 목록은 화면 데이터의 대체재가 아니다.

질문은 questionId·label·required·options·interruptValues로 렌더링한다. 위험 확인 선택처럼 interruptValues에 해당하면 맥락 저장 후 서버 평가를 호출한다. 프론트가 표현·보수 기준을 분석해 위험이나 교체 가능성을 판정하지 않는다.

## 4. 상태·저장·충돌

| 상태 | 위치 |
| --- | --- |
| 인증·세션·카탈로그·질문·결과·이력·대화 | TanStack Query |
| 아직 저장하지 않은 답·메시지 | 폼·컴포넌트 상태 |
| 계정 CSRF 토큰 | 앱 메모리; 필요 시 /auth/me 재조회 |
| 익명 복구 정보·처리 중 requestId | sessionStorage |

맥락은 context 전체와 expectedRevision으로 저장하고 응답의 정규화된 값으로 갱신한다. 부모 선택이 바뀌면 무효 하위 항목·숨겨진 답을 제거한다. 409 CONTEXT_CONFLICT는 최신 맥락을 조회해 변경을 확인하며 자동 덮어쓰지 않는다.

설문 평가·채팅마다 UUID requestId를 발급한다. 시간 초과·응답 유실이면 GET .../requests/{requestId} 또는 같은 ID 재전송으로 상태·완료 응답을 확인한다. PROCESSING이면 기다리고 COMPLETED이면 저장된 응답을 표시한다. FAILED는 실패를 설명한 뒤 사용자가 재시도할 때만 새 ID로 실행한다. 새 ID 자동 재전송은 없다. 요청 대기 중 맥락 저장·새 전송을 막는다. 서버 SESSION_BUSY·REQUEST_IN_PROGRESS의 대기 시간을 따른다.

결과 저장은 서버의 평가 완료 트랜잭션에서 자동 수행한다. 저장 실패를 화면에서 성공으로 표시하지 않는다. 회원 생성 결과는 계정 이력, 비회원 결과는 현재 익명 세션에 연결됐다는 표시를 제공한다.

비회원 상담 중 로그인하면 새 회원 상담을 시작한다. 회원 이력은 로그인한 상태에서 생성한 결과만 보여준다. 익명 결과를 계정에 옮기는 버튼·API는 초기 범위에서 제외한다. 기존 익명 결과는 유효한 현재 익명 토큰으로만 조회할 수 있다.

## 5. 결과·이력·대화 표시

결과 상태는 SAFETY_PRIORITY, OUT_OF_SCOPE, NEED_MORE_INFO, NEED_CONFIRMATION, GUIDANCE_AVAILABLE이다. 서버 문구를 승인·비용 확정 표현으로 바꾸지 않는다. LAW_CRITERIA와 LH_OPERATION을 분리하고 Citation.use=RELATED는 참고 자료로 표시한다.

정보가 부족하면 안내 불가·직접 문의 문구를 표시한다. 기관 이름은 표시할 수 있지만 연락처·전화번호·이메일·전화 링크를 답변·문의 문구에 넣지 않는다. “대신 웹에서 찾아볼게요” 동작은 없다. 출처 원문 링크는 검토된 근거 확인용이며 임의 검색 기능이 아니다.

회원 이력은 만료한 상담 세션과 독립적으로 /me/results에서 조회한다. 과거 결과의 isCurrent=false는 현재 상담·기준과 같지 않다는 의미다. 본문과 생성 당시 출처는 기록으로 보여주고 새 상담을 제공한다. 이력 삭제 성공 시 목록·상세 캐시를 제거한다.

회원 대화는 answerMode와 인용을 표시한다. TEMPLATE·CLARIFY는 정상적인 대체·추가 확인 응답이다. followUpQuestions는 확인 질문으로 표시하고 사용자가 기존 카탈로그에서 다시 선택하면 맥락을 저장한다. 모델 답변에서 ID를 추출해 자동 변경하지 않는다. 메시지 목록·재생 답변의 isCurrent=false는 과거 기록으로 표시한다. MVP는 완성 JSON 응답을 사용한다.

## 6. 오류·네트워크

| 코드 | 처리 |
| --- | --- |
| AUTH_REQUIRED·AUTH_EXPIRED | 회원 기능 캐시 제거·로그인 안내 |
| UNAUTHORIZED·SESSION_EXPIRED | 익명 복구 정보 제거·새 설문 |
| CATALOG_NOT_READY | 준비 중; 임의 목록 사용 금지 |
| CATALOG_UPDATED | 최신 완성 카탈로그 조회·선택 재확인 |
| CONTEXT_CONFLICT | 최신 입력과 미저장 입력 비교 |
| SESSION_BUSY·REQUEST_IN_PROGRESS | 대기·동일 requestId 상태 조회 |
| REQUEST_FAILED | 실패 설명; 사용자가 재시도할 때 새 requestId 생성 |
| IDEMPOTENCY_CONFLICT | 같은 ID의 입력이 달라 실행되지 않았음을 설명 |
| INVALID_SELECTION·INVALID_ANSWER·VALIDATION_ERROR | 필드 오류 |
| NOT_FOUND | 자원 없음 또는 소유권 없음 안내 |
| RATE_LIMITED | 입력 유지·Retry-After 후 시도 |
| SERVICE_UNAVAILABLE | 저장 실패 설명·수동 재시도 |

증상 보충 설명은 최대 1,000자, 회원 채팅은 최대 2,000자다. 서버가 같은 제한을 적용한다. 사용자 응답은 no-store로 처리하고 공유·오프라인 캐시를 쓰지 않는다. 채팅 서버 예산 25초·클라이언트 35초, 설문 평가 서버 10초·클라이언트 15초를 초깃값으로 한다.

## 7. 접근성·보안과 인수 조건

라디오 질문은 fieldset/legend, 오류는 aria-describedby, 대화 갱신은 aria-live를 사용한다. 360px·확대·키보드·스크린리더에서 로그인·이력·삭제까지 검증한다. 사용자·AI 텍스트는 HTML로 실행하지 않는다. 토큰·원문 입력·대화·비밀번호를 콘솔·분석 이벤트에 남기지 않는다. 출처는 검토된 HTTPS 링크만 표시한다.

- 비회원이 챗봇·이력 경로로 직접 접근해도 사용·조회가 차단된다.
- 회원 결과는 세션 만료 뒤에도 본인 계정 이력에서 조회된다.
- 익명 결과 저장과 로그인 후 새 회원 상담이 구분되며 과거 익명 결과는 자동 연결되지 않는다.
- 목록 미완성 상태에서 기존 예시 증상이 노출되지 않는다.
- 재시도에서 결과·질문 통계·메시지가 중복되지 않는다.
- 연락처 없는 직접 문의 정책이 결과·채팅·문의 문구에 일치한다.
