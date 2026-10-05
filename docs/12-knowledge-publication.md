# M09 원문 반입·임베딩·검색·게시

작성: 2026-10-05 · [실제 검토/평가 산출물](../data/knowledge/m09-20261004/README.md) · [완료 기록](../progress/04-m09-knowledge-review.md)

## 설정과 준비

실제 서버 설정은 Git/Docker 빌드에서 제외된 `.env`에 둔다. 키를 명령 인자·브라우저·기록 파일·로그로 출력하지 않는다. 생성 모델은 사용자 지정 `gpt-5.4-mini`, 임베딩은 `text-embedding-3-large`·1536차원이다. 생성 모델 호출은 [M10](13-member-chat.md)에서 연결했다. 예시 환경은 OPENAI_ENABLED=false를 유지하며 현재 검증한 로컬 `.env`는 true다.

large의 기본 3072차원을 그대로 쓰지 않고 요청에 dimensions=1536을 명시한다. 문서·질문 모델과 차원이 같아야 한다. 변경된 본문은 새 임베딩, 변경된 검토/연결은 새 릴리스로 처리한다. 동일 본문 해시·본문·모델·차원의 벡터는 재사용한다. 사용자의 요청에 따라 총비용 상한은 없으며 한 요청 최대 32개 입력, 입력별 UTF-8 8191바이트의 보수적 한도, 문서 30초·질문 5초 timeout, HTTP 자동 재시도 없음은 유지한다. 큰 조문은 자르지 않고 별도 분할 검토를 요구한다.

공식 계약: [Embeddings](https://developers.openai.com/api/docs/guides/embeddings), [API](https://developers.openai.com/api/reference/resources/embeddings/methods/create), [large 모델](https://developers.openai.com/api/docs/models/text-embedding-3-large). gpt-5.4-mini의 데이터 공유 무료 사용량은 조직의 혜택 자격·공유 설정·한도에 따라 적용된다. 임베딩 무료 사용량으로 간주하지 않는다. 계정의 공유 설정을 이 작업에서 변경하거나 검증하지 않았다. [공식 무료 사용량 조건](https://help.openai.com/en/articles/10306912-sharing-feedback-evaluation-and-fine-tuning-data-and-api-inputs-and-outputs-with-openai)

## 관리 명령

현재 MIGRATION_HEAD `0005_m10`을 먼저 적용한다. 지식 불변성은 `0004_m09`에서 추가했다. 기존 데이터가 있는 DB에 downgrade를 하지 않는다. 앱 이미지에 원문/키/벡터를 넣지 않으며 필요할 때만 원문을 읽기 전용 마운트한다. 아래 경로는 현재 Windows 체크아웃 기준으로 다른 환경에서는 변경한다.

```sh
docker compose --env-file .env -f compose.yaml -f compose.admin.yaml run --rm --no-deps api python -m alembic upgrade head
docker compose --env-file .env run --rm --no-deps --volume C:/Users/dlqnf/Desktop/teamproject/data:/data:ro api python -m app.commands.knowledge validate --source /data/private/m08/2026-10-04 --manifest-sha256 e8d39ff480b738cd2da15cc248fb37796ba7fca81a7228b7acf6c0dde53304a4
docker compose --env-file .env run --rm --no-deps --volume C:/Users/dlqnf/Desktop/teamproject/data:/data:ro api python -m app.commands.knowledge import --source /data/private/m08/2026-10-04 --manifest-sha256 e8d39ff480b738cd2da15cc248fb37796ba7fca81a7228b7acf6c0dde53304a4 --catalog /data/catalog/m08a-20261004/catalog.json --catalog-review /data/catalog/m08a-20261004/review.json --review /data/knowledge/m09-20261004/review.json
```

반입은 카탈로그 파일/게시 DB 일치, 독립적으로 고정한 manifest SHA256, COMPLETE_VERIFIED, 40개 조문·3개 별표 coverage, 파일 크기·경로·해시, 문단/정리본 일치와 총칙·부칙을 검사한다. 누락·검토 미완료·외부 경로·중복 파일은 거부한다. 원문 manifest의 NOT_APPROVED를 자동 승격하지 않으며 별도의 용도 제한 검토를 요구한다. M09 검토자는 Codex이며 법률·LH 운영 승인을 대신하지 않는다.

import가 반환한 BUILDING releaseId로 다음 명령을 실행한다. 아래 RELEASE_ID는 그 값으로 바꾼다. **이미 게시된 최종 릴리스를 다시 embed/evaluate/publish하지 않는다.**

```sh
docker compose --env-file .env run --rm --no-deps api python -m app.commands.knowledge embed --release-id RELEASE_ID
docker compose --env-file .env run --rm --no-deps --volume C:/Users/dlqnf/Desktop/teamproject/data/knowledge/m09-20261004:/review api python -m app.commands.knowledge evaluate --release-id RELEASE_ID --cases /review/evaluation-cases.json --output /review/evaluation-report.json
docker compose --env-file .env run --rm --no-deps api python -m app.commands.knowledge publish --release-id RELEASE_ID
```

실패한 BUILDING은 명시적으로 embed를 다시 실행하면 성공한 청크를 건너뛴다. 호출 동안 DB 트랜잭션·행 잠금을 유지하지 않고 성공 배치별로 저장한다. 임베딩 오류는 공급자 본문·키를 출력하지 않는다. 평가 결과는 벡터·본문·관계·검토 범위 지문과 함께 DB에 기록하며 게시 명령은 현재 지문 및 평가 기준(recall@5≥90%, 상태 정확도≥95%, 운영 오적용 0건)을 검사한다. 파일의 수치만 변경해서 게시하지 않는다.

## 런타임 검색과 철회

새 상담은 현재 카탈로그에 맞는 게시 지식 버전을 고정한다. 이전 상담은 자동으로 새 지식으로 옮기지 않는다. 안전·지원 범위·필수 정보 확인 후, 설문은 검토된 선택/답 라벨만 임베딩한다. 자유 설명·이메일·주소는 전송하지 않고 질문 벡터는 요청 메모리에서만 사용한다. 생성 호출은 없다.

pgvector cosine 정확 검색은 PUBLISHED·APPROVED·검토 기한·주택·모델·차원을 제한한다. 명시적 조문 번호 또는 실제 증상 태그로 관련 후보를 좁히고 최대 20개 후보에서 최대 5개 근거 묶음을 구성한다. 각 묶음에 실제 별표/상위 조문과 총칙·부칙을 포함한다. 평가 결과는 이 검색 계약에 한정하며 자유 질문 의미 검색의 일반 성능으로 보고하지 않는다.

운영 템플릿에는 승인된 LH_OPERATION, 확인된 답 조건, 충돌 식별자와 연락처 없는 문구가 필요하다. 같은 조건의 템플릿 충돌은 SOURCE_CONFLICT로 직접 문의한다. 현재 확보 자료에는 운영 템플릿이 없으므로 일반 설문은 RELATED 인용과 NEED_CONFIRMATION이다. 명시적 설명과 혼합/불명확 목적의 구분 함수는 M10의 생성 전 게이트에서 재사용한다.

결과 저장 직전에 지식 묶음·원문·필수 연결을 잠깐 잠그고 재확인한다. 철회·기한 만료 등은 SOURCE_UNAVAILABLE 기본 안내로 전환한다. 이력 조회에서도 필수 연결의 적격성을 검사해 isCurrent를 재계산한다. PostgreSQL 오류는 503이고 임베딩 실패는 DB가 정상일 때 기본 안내로 저장한다.

```sh
docker compose --env-file .env run --rm --no-deps api python -m app.commands.knowledge withdraw --source-key SOURCE_KEY --reason REVIEW_REASON
```

철회는 같은 source_key의 모든 묶음에 적용하며 같은 source_key 재반입도 차단한다. 반입/철회는 source_key 잠금으로 직렬화한다. 게시된 지식 묶음·원문·청크는 DB trigger로 수정/삭제를 막고 명시적 철회만 허용한다. 재승인은 기존 게시본 수정으로 처리하지 않는다.

현재 개발 서비스 확인:

```sh
backend/.venv/Scripts/python.exe scripts/smoke_api.py --catalog-version m08a-20261004-v2 --rag-ready
```

실제 API 키 없이 전체 회귀 시험은 [격리 시험 DB 절차](10-local-development.md#3-실제-db-시험)를 사용한다. M09는 컴퓨터 유즈 없이 CLI·공식 문서 조회·실제 DB/API로 검증했다.
