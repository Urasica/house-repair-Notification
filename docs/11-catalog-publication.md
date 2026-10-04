# 카탈로그 작성·검증·게시 안내

작성: 2026-10-03 · 갱신: 2026-10-04 · M05 및 M08A 완료

사용자 지시에 따라 실제 M08 원문으로 작성한 목록을 검토한 뒤 게시한다. [m08a-20261004-v2](../data/catalog/m08a-20261004/README.md)은 COMPLETE_VERIFIED이며 로컬 개발 DB에 게시했다. 시험 fixture는 전용 시험 DB에서만 사용하고 공개 개발 DB에는 넣지 않는다. 원문 추출·청킹·임베딩은 이 명령의 기능에 포함되지 않는다.

## 1. 작성 형식과 검토

입력은 UTF-8 JSON이며 BOM을 허용한다. 최대 파일 크기는 5 MiB다. [JSON Schema](../schemas/catalog.schema.json)와 `CatalogDefinition`의 연결 검증을 함께 따른다. JSON Schema만으로 모든 연결·분기 검증을 끝낼 수 없으므로 아래 명령도 실행한다.

| 필드 | 내용 |
| --- | --- |
| version | 1~80자 안정적인 버전 ID; 영문·숫자로 시작하고 영문·숫자·밑줄·하이픈·점을 사용 |
| review | DRAFT 또는 COMPLETE_VERIFIED; 완료 검토는 reviewer와 시간대가 포함된 reviewedAt 필요 |
| housingTypes | 고정된 5개 주택 유형·표시 라벨·supported |
| rooms | 공간의 id·label·선택적 aliases |
| facilities | 시설물의 id·label·aliases·roomIds |
| symptoms | 증상의 id·label·aliases·facilityIds |
| questions | questionId·singleChoice·label·required·options·interruptValues·symptomIds·order·conditions |

항목/질문 ID와 옵션 값은 1~80자로, 영문·숫자로 시작하고 영문·숫자·밑줄·하이픈을 사용한다. 라벨·검토자·동의어는 공백만 있는 값을 허용하지 않는다. 동의어는 항목당 최대 20개다. ID·옵션 값·연결 ID·항목 내 동의어의 중복과 존재하지 않는 연결을 거부한다. 동의어가 여러 항목에 겹치면 실제 의미를 사람이 검토하며 자동으로 하나의 항목에 연결하지 않는다.

COMPLETE_VERIFIED에는 비어 있지 않은 각 목록과 `LH_CONSTRUCTION_RENTAL`, `LH_RENTAL_BEFORE_SALE`, `SOLD_OR_PRIVATE`, `OTHER`, `UNKNOWN` 5개 주택 유형이 모두 필요하다. supported=true는 앞의 두 유형에만 적용한다. 검토자는 시설물·증상 연결, 용어/동의어, 필수 여부, 모름 선택, 위험 확인 문구/값, 질문 분기의 실제 의미를 확인한다. 형식 검증 성공만으로 검토 완료로 변경하지 않는다. 검토 시각은 미래일 수 없다.

## 2. 질문과 선택 정리

질문 순서는 `(order, questionId)` 오름차순이다. options에는 최소 두 개의 고유한 값과 표시 라벨을 둔다. “모름”을 제공하려면 실제 options에 그 선택 값을 넣는다. 이 값도 유효한 답으로 취급하며 필수 답 누락으로 처리하지 않는다.

conditions는 모두 만족해야 질문을 표시한다. 허용 경로는 housingType·roomId·facilityId·symptomId·answers.질문ID이고 연산은 equals 또는 in이다. equals에는 문자열, in에는 비어 있지 않은 고유한 문자열 목록을 사용한다. 비교 값은 해당 목록 ID 또는 앞선 질문의 실제 옵션 값이어야 한다. answers 조건은 앞선 질문만 참조하며 참조 질문은 현재 질문의 모든 증상에 연결돼 있어야 한다. 자기 참조·순환·뒤 질문 참조는 거부한다. 임의 식·스크립트는 실행하지 않는다.

서버 정책은 알 수 없는 ID/옵션을 422로 거부한다. 기존 맥락에서 공간이 바뀌면 연결이 무효인 시설물·증상을, 시설물이 바뀌면 연결이 무효인 증상을 제거한다. 상위 선택이 바뀌지 않은 모순된 조합은 422다. 새 맥락에서 보이지 않는 질문의 답과 그 답에 의존하는 후속 답은 제거한다. 유효한 하위 선택·공통 질문의 답은 유지한다.

검토된 질문의 interruptValues에 해당하는 답만 위험 신호다. 정책 순서는 위험 → 알려진 범위 밖 주택 → 필수 입력 부족 → 근거 확인 필요다. 주택 UNKNOWN은 추가 확인이 필요하고 질문의 모름 답은 정상 답이다. 자유 입력에서 임의로 위험/보수 조건을 추측하지 않는다. 실제 안전 문구·근거 적용·결과 저장은 M06/M09에서 연결한다. M05 정책만으로 GUIDANCE_AVAILABLE을 만들지 않는다.

## 3. 검증 명령

backend 작업 디렉터리에서 실행한다. Python 실행 경로는 [로컬 개발 안내](10-local-development.md)를 따른다. 명령은 원본 본문·개인정보·접속 문자열을 출력하지 않고 버전·검토 상태·건수 또는 오류 필드만 출력한다.

```sh
python -m app.commands.catalog validate /absolute/path/catalog.json
```

DRAFT도 형식 검증할 수 있으며 reviewComplete=false로 표시한다. validate는 DB 연결이나 게시를 하지 않는다. 완료 상태라도 검토 시각·게시 환경·기존 버전 등은 publish가 다시 확인한다. 검증 오류/게시 거부는 종료 코드 1, 성공은 0이다.

## 4. 일회성 게시

먼저 현재 migration head `0003_m06`까지 적용한다. 게시본 불변성은 M05의 `0002_m05`에서 추가했다. migration은 기존 API 중단 후 관리자 연결로 실행하고, 게시 명령은 DML 앱 연결만 사용한다. [Docker 절차](10-local-development.md)를 따른다.

검토한 실제 파일을 읽기 전용으로 마운트해 같은 API 이미지에서 실행한다. 아래 예시의 `/absolute/path/catalog.json`을 실제 절대 경로로 바꾼다. Windows에서는 `C:/.../catalog.json` 형태로 지정할 수 있다.

```sh
docker compose --env-file .env run --rm --no-deps --volume /absolute/path/catalog.json:/input/catalog.json:ro api python -m app.commands.catalog validate /input/catalog.json
docker compose --env-file .env run --rm --no-deps --volume /absolute/path/catalog.json:/input/catalog.json:ro api python -m app.commands.catalog publish /input/catalog.json
```

publish는 완료 검토·현재 migration·파일 연결을 확인하고 한 트랜잭션에서 게시한다. API 시작 복구를 실행하지 않아 활성 PROCESSING 상담을 실패로 바꾸지 않는다. 게시 시각은 서버가 정한다. 같은 버전의 동일한 정규화 JSON 재전송은 기존 게시 시각을 유지한다. 같은 버전에 다른 내용은 409 CATALOG_UPDATED이며 새 버전을 사용해야 한다.

게시본은 DB trigger로 UPDATE/DELETE를 차단한다. 과거 게시본은 `/api/v1/catalog?version=...`에서 조회하며 최신 조회는 게시 시각·버전 순으로 정한다. 최신 버전 상담 시작 검사 함수는 예전 버전에 409 CATALOG_UPDATED와 최신 catalogVersion을 반환한다. 이 함수와 질문 응답 DTO는 M06 상담 API에 연결되어 있다.

`test-`/`test_`로 시작하는 버전·항목/질문 ID·검토자는 시험 전용으로 예약한다. 해당 자료는 APP_ENV=test이면서 DB 이름이 repair_guide_test인 경우에만 게시 함수를 사용할 수 있다. 시험은 트랜잭션을 되돌린다. 공개용으로 시험 ID를 바꾸는 작업은 실제 목록 검토를 대신하지 못한다.

## 5. 확인 기록과 남은 작업

자동 시험은 구조 오류·분기·답 정리·5개 주택 범위·모름·위험 우선순위·검토 미완료·시험 목록 게시 거부와 실제 PostgreSQL의 게시 재전송·새 버전·과거 조회·DB 불변성을 검증한다. M08A 완료 후 로컬 개발 DB는 catalogReady=true이며 m08a-20261004-v2을 반환한다. ragReady=false는 유지한다. 아직 목록을 게시하지 않은 새 환경에서는 catalogReady=false·CATALOG_NOT_READY다.

2026-10-04 M08A에서 실제 목록의 ID/연결/용어/모름/위험 정책을 검토하고 게시했으며 M06~M07 실데이터 통합 검증을 마쳤다. [완료 기록](../progress/03-m08a-catalog-review.md)에 출처/목록 해시·검토 범위·게시 시각·시험 결과를 기록했다. 원문/법률 적용 검토와 목록 완전성 검토는 구분하며 LH 운영 근거가 없으면 NEED_CONFIRMATION을 유지한다.
