# 보존·삭제·백업 실행 안내

[챗봇 초기화](../product/chat.md)는 해당 CHAT 상담의 원본 대화·맥락·요청/응답을 종료·삭제하고 새 세션을 만드는 동작이다. 설문 상담·회원 결과·장기 정제 질문·chat_usage는 유지하며 상담 삭제 로그·백업 복원 후 재삭제를 적용한다. 초기화를 질문 분석 기록 전체 삭제로 안내하지 않는다.

## 1. 보존과 집계

`python -m app.commands.maintenance`는 API 시작 복구를 호출하지 않는 일회성 관리 명령이다. 정리 작업 때문에 진행 중인 요청을 FAILED로 바꾸지 않는다.

| 명령 | 동작 |
| --- | --- |
| `cleanup` | 만료 인증 세션·상담·비회원 결과·요청/대화 원본, 기한이 지난 회원 결과/정제 질문, 2일 지난 사용량을 정리하고 삭제 파일 갱신 |
| `statistics --since 2026-01-01T00:00:00+00:00` | 기한 내 question_records를 종류·카탈로그·시설·증상으로 GROUP BY. 계정 ID·원문 미출력 |
| `export-deletions` | DB 삭제 로그를 별도 암호화 파일로 내보내고 기한 지난 삭제 로그 정리; 실패 후 동일 명령 재실행 |
| `backup` | pg_dump custom 형식과 지정 검토 폴더의 파일/manifest를 암호화해 두 저장 경로에 기록·해시 검증 |
| `restore` | 빈 별도 DB에 복원한 뒤 최신 삭제·기한 적용, 인증 취소, 게시 지식 격리 |

인증/상담 접근은 기존 24시간 만료 검사를 따른다. 정리 명령은 만료한 상담을 다음 실행 때 바로 지운다. 일일 실행하면 만료 후 7일이라는 최대 보관 기간보다 짧게 정리된다. RAW_RECORD_GRACE_DAYS가 만료 자료를 반드시 그 기간 동안 남기라는 의미는 아니다. 실행 실패를 방치하면 상한을 지킬 수 없으므로 호스트 스케줄·실패 알림은 출시 조건이다.

회원 결과와 정제 질문은 별도의 retained_until을 따른다. 3~5년, 기본 5년이며 윤년 2월 29일은 해당 연도 2월 말일로 처리한다. 회원 결과의 입력·답변·출처 스냅샷은 장기 이력에 포함된다. 상담 FK가 SET NULL이 되어도 회원 이력과 정제 질문은 유지된다. 질문 보존 만료만으로 아직 유효한 결과를 지우지는 않는다. 명시적 결과 삭제는 연결 질문도 삭제하고 해당 요청을 DELETED/response_json=null로 바꾼다. 재생은 정제 질문을 다시 만들지 않으며 집계는 삭제 직후 제외한다.

## 2. 비밀과 저장 경로

`.env.ops.example`을 Git에서 제외된 `.env.ops`로 복사하고 별도 Fernet 키를 설정한다. OpenAI 키를 암호화 키로 재사용하지 않는다. 키는 백업과 다른 보호 위치에도 보관한다. 키 분실 시 복호화할 수 없으며 키 교체 전에 기존 14일 백업과 삭제 파일을 처리할 계획이 필요하다. 현재 도구는 단일 키를 사용한다.

API는 `compose.deletions.yaml`을 함께 사용해야 삭제 직후 내보내기가 활성화된다. API UID 10001이 DELETION_EXPORT_DIR에 쓸 수 있어야 한다. 폴더/키 접근은 운영 계정으로 제한한다. `.env`, `.env.ops`, `data/private/operations`는 Git 제외 대상이다.

| 설정 | 운영 조건 |
| --- | --- |
| BACKUP_KEY | `cryptography.fernet.Fernet.generate_key()`로 생성한 키; 출력/버전 관리 금지 |
| BACKUP_SCOPE | 환경별 고유 식별자. API·백업·복원·삭제 파일에서 같은 값 사용 |
| DELETION_EXPORT_DIR | 일일 DB 백업과 분리한 **최신 삭제 파일** 위치. 운영에서는 서버 손실에도 살아남는 별도 원격 마운트 필요 |
| BACKUP_LOCAL_DIR | 일일 암호화 백업의 로컬 위치 |
| BACKUP_REMOTE_DIR | 운영 서버 밖의 이미 마운트된 저장소. 두 번째 로컬 폴더를 원격 백업으로 간주하지 않음 |
| REVIEWED_FILES_DIR | 검토 원문·별표·manifest 폴더. DB에도 카탈로그/게시 manifest를 보존하며 코드와 공개 검토 자료는 대응 Git 버전으로 확보 |
| RESTORE_FILES_DIR | 복원 검토 파일을 쓸 보호 폴더; 명령에는 그 아래 새 하위 폴더 지정 |

`remoteVerified`는 지정 경로로 기록한 바이트의 해시가 일치한다는 뜻이다. 네트워크 저장소인지나 서버 손실에 대한 내구성을 검증하는 값은 아니다. 운영 호스트는 실행 전 원격 마운트 상태·원격 위치를 확인하고 해제 시 로컬 디렉터리로 조용히 쓰지 않도록 스케줄러에서 차단해야 한다.

## 3. 실행 예

저장소 루트에서 다음 Compose 구성을 사용한다. Windows Docker Desktop 연결이 필요한 환경은 `docker` 뒤에 `--config .cache/docker -H npipe:////./pipe/dockerDesktopLinuxEngine`을 추가한다. 비밀이 포함되는 `compose config` 전체 출력은 남기지 않는다.

```powershell
docker compose --env-file .env --env-file .env.ops -f compose.yaml -f compose.ops.yaml build ops
docker compose --env-file .env --env-file .env.ops -f compose.yaml -f compose.ops.yaml run --rm --no-deps ops export-deletions
docker compose --env-file .env --env-file .env.ops -f compose.yaml -f compose.ops.yaml run --rm --no-deps ops backup --reviewed /reviewed --local /backups --remote /remote
docker compose --env-file .env --env-file .env.ops -f compose.yaml -f compose.ops.yaml run --rm --no-deps ops cleanup
docker compose --env-file .env --env-file .env.ops -f compose.yaml -f compose.ops.yaml run --rm --no-deps ops statistics
```

API의 로컬 실행에는 `--env-file .env --env-file .env.ops -f compose.yaml -f compose.deletions.yaml`을 사용한다. ops는 profiles: ops의 일회성 컨테이너이며 상시 서비스는 web/api/db 3개를 유지한다. PostgreSQL 18 클라이언트를 포함한 별도 Dockerfile.ops를 사용한다. API에는 DB 관리자 권한을 부여하지 않는다. 정리/내보내기 명령은 API 이미지로도 실행할 수 있다.

정리/백업은 최소 일 1회, 삭제 파일 내보내기 재시도는 더 짧은 간격으로 호스트에서 실행한다. 명령 종료 코드와 성공 시각을 관측한다. API 삭제 트랜잭션은 먼저 커밋한다. 파일 쓰기 실패는 이미 수행한 삭제를 되돌리지 않으며 `DELETION_EXPORT_FAILED`를 남긴다. 호스트가 이를 경보하고 export-deletions를 재실행해야 한다. 실패가 해결되지 않은 상태에서는 복원본을 공개하지 않는다.

## 4. 백업 형식과 한계

pg_dump custom archive, 검토 파일별 SHA-256, 스키마 버전·환경 구분·백업 시각을 하나의 인증된 Fernet 파일에 담는다. 암호화되지 않은 DB dump를 디스크에 쓰지 않는다. 임시 파일 flush/fsync 후 원자 교체하며 exporter는 PostgreSQL advisory lock으로 순서를 보장한다. 최신 삭제 파일에는 식별자·종류·삭제/만료 시각만 담는다.

백업 양쪽 경로에서 이 도구가 생성한 같은 scope의 인증 가능한 파일만 14일 기준으로 정리한다. 파일 mtime을 신뢰하지 않는다. 손상 파일은 임의 삭제하지 않고 실패 처리한다. 삭제 로그는 기본 15일이고 내보내기 성공 뒤 만료분을 제거한다. 복원은 14일 지난 백업을 거절한다. 보존 주기 실패·시계 오류도 운영 관측 대상이다.

현재 작은 MVP를 위한 메모리 기반 암호화다. dump와 검토 파일 각각 128 MiB, 최종 암호문 256 MiB를 초과하면 실패한다. subprocess 출력 크기는 수신 후 검사하므로 메모리 사용의 강제 상한은 아니다. 자료가 커지기 전에 스트리밍 인증 암호화/관리형 백업으로 전환하고 복구 시간을 재측정한다.

근거: [PostgreSQL 18 pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html), [cryptography Fernet](https://cryptography.io/en/latest/fernet/).

## 5. 복원과 공개 전 확인

1. 유지보수 상태에서 기존 API 쓰기를 중지한다. 기존 DB를 덮어쓰지 않고 이름이 `_restore`로 끝나는 빈 DB를 관리자 계정으로 만든다. 새 DB는 API에 연결하지 않는다.
2. 일일 백업과 **별도로 보관한 최신 삭제 파일**을 확보한다. 살아 있는 원본 DB가 있으면 쓰기 종료 후 export-deletions를 실행한다. 서버를 잃었다면 마지막 삭제 내보내기 성공과 이후 실패/미반영 삭제가 없음을 확인한다. 파일의 시각만으로 최신성을 입증할 수는 없다.
3. 복원용 비밀 설정에서 MIGRATION_DATABASE_URL을 새 DB로 바꾸고, 같은 BACKUP_KEY/BACKUP_SCOPE를 사용한다. 원본 `.env`의 실제 서비스 연결을 수정하지 않는다.
4. 다음 명령을 실행한다. 출력 폴더는 새 경로여야 한다.

```powershell
docker compose --env-file .env.restore --env-file .env.ops -f compose.yaml -f compose.ops.yaml run --rm --no-deps ops restore --archive /remote/backup-대상.fernet --latest-deletions /deletions/latest.fernet --reviewed-output /restored/새복원폴더 --maintenance
```

암호문 인증·해시·scope·스키마·경로를 검사하고 24시간보다 오래됐거나 백업 이전인 삭제 파일을 거절한다. 이 검사는 잘못된 파일을 막는 보조 검사이며 2번의 최신성 확인을 대체하지 않는다. 최신성을 확인할 수 없으면 회원 결과·질문 복원본을 공개하지 않는다. 자동 cutover는 하지 않는다.

결과 삭제 마커를 적용할 때 결과 FK가 남아 있을 때 연결 요청을 찾아 DELETED와 null 응답을 먼저 적용한다. 상담/질문 삭제도 재적용하며 별도 삭제 파일의 마커를 복원 DB에도 보존해 다음 내보내기에서 사라지지 않게 한다. 만료 정리, PROCESSING→FAILED, 전체 인증 세션 삭제를 수행한다.

복원된 PUBLISHED 지식 묶음은 모두 WITHDRAWN으로 격리한다. 백업만으로 최신 철회 여부를 알 수 없기 때문이다. 원문/검토 상태를 확인한 새 묶음을 게시하기 전에는 RAG 안내를 재개하지 않는다. 기존 묶음의 불변성을 우회하지 않는다.

복원은 `--no-owner --no-acl`을 사용한다. 공개 전에 새 DB의 제한된 API 역할에 CONNECT/USAGE와 필요한 테이블 SELECT/INSERT/UPDATE/DELETE 및 향후 migration의 default privileges를 다시 부여한다. superuser를 API 계정으로 사용하지 않는다. 정확한 DB/역할은 운영 환경에서 확인한다. 파일·삭제·현재 유효성·권한 smoke와 읽기 확인을 마친 뒤 API 연결을 전환한다. 실패한 복원 DB는 비공개로 두고 새 빈 DB에서 다시 실행한다.

## 6. 재현 가능한 검증

`Jenkinsfile`은 실제 pgvector/PostgreSQL migration·전체 API 시험·계약·프론트 검증·Playwright·암호화 복원·20개 동시 상담·DB 장애와 재시작을 연결한다. OpenAI는 OFF/mock이며 비밀이 필요 없다. Jenkins에서 테스트 결과와 산출물을 확인한다. [Jenkins 자동 테스트](../development/local.md#6-jenkins-자동-테스트)

- `backend/tests/test_retention.py`, `test_backup.py`: 경계·윤년·재생/집계·명시 삭제·내보내기 실패/재시도·후속 복원 마커·위조/기한/경로/환경 거절.
- `scripts/drill_backup.py`: 테스트 DB에서만 임시 source/restore DB를 생성, 실제 pg_dump→암호화→복원→삭제/410/지식 격리 확인 후 임시 DB 제거.
- `frontend/e2e/core.spec.ts`: 실제 목록의 360px Chromium 설문/로그인/챗봇/새로고침/이력/삭제/로그아웃, Tab과 axe WCAG AA 검사.
- `scripts/load_api.py`: 테스트 포트 18080에서 같은 계정의 20개 독립 상담으로 동시 요청. 회원 20명 로그인 부하나 운영 서버 SLA를 검증하는 시험은 아니다.
- `scripts/drill_outage.py`: 테스트 프로젝트의 DB만 중단/복구하고 단일 API 재시작. 운영 프로젝트에는 실행하지 않는다.

전체 시험은 API 프로세스를 정지한 깨끗한 `repair_guide_test`에서 실행한다. E2E는 별도 단계로 실제 목록을 게시하므로 전체 DB 단위 시험보다 나중에 수행한다. 사용자 데이터가 있는 DB를 시험 초기화 대상으로 사용하지 않는다.
