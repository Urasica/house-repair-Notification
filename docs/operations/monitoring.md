# Prometheus와 Grafana 모니터링

Prometheus는 접속, API와 운영 작업 지표를 수집한다. Grafana는 대시보드를 제공하고 Alertmanager는 Prometheus 경보를 전달한다. 기존 배포에 선택적으로 추가한다.

## Windows 테스트 실행

`test-deploy.bat -Monitoring`으로 테스트 서버와 모니터링을 시작한다. `-OpenTunnel`을 함께 사용하면 서비스 포트 8080에 터널이 연결된다. Grafana는 로컬 주소로 접속한다.

배치는 `.env.monitoring`이 있으면 그 파일의 Grafana 설정을 사용한다. 없으면 프로젝트별 임의 관리자 비밀번호를 `.cache/<프로젝트명>-monitoring.env`에 생성하고 다음 실행에서 재사용한다. 사용자 이름은 `admin`이다. Grafana 포트가 이미 사용 중이면 `.env.monitoring`의 `MONITORING_GRAFANA_PORT`를 지정한다. 관리자 비밀번호 설정은 새 Grafana 데이터 볼륨에 처음 적용된다.

`stop-test-deploy.bat`는 옵션 없이 전체 테스트 구성을 종료하고 볼륨을 보존한다. 다음 시작에서 `-Monitoring`을 생략하면 이전 모니터링 컨테이너를 중지하고 테스트 서버를 시작한다. OpenAI 비용 수집은 별도 설정으로 실행한다.

## 1. 시작과 접속·운영 작업 경보

1. `.env.monitoring.example`을 Git에서 제외된 `.env.monitoring`으로 복사해 Grafana 관리자 비밀번호를 설정한다. 이 값은 새 Grafana 데이터 볼륨을 초기화할 때 사용한다.
2. 기존 Compose 프로젝트명·설정 파일·비밀 파일 순서를 유지한다. `config`, `up`, `run` 같은 하위 명령 앞에 `--env-file .env.monitoring -f compose.monitoring.yaml`을 추가한다. `config --quiet`으로 설정을 검증한 뒤 같은 옵션으로 `up -d --build api prometheus blackbox pushgateway alertmanager grafana`를 실행한다. 이미 서버를 운영 중이면 API가 재생성되는 시각을 정한다.
3. 같은 호스트에서 [Grafana](http://localhost:3000/)에 `admin`으로 로그인하고 **우리집 보수 길잡이 → 운영 모니터링**을 연다. 원격 운영 호스트에서는 SSH 포트 포워딩으로 접속한다. 호스트에는 Grafana만 루프백에 바인딩되고 Prometheus, Blackbox Exporter, Pushgateway, Alertmanager, API 지표 포트는 Compose 네트워크 안에 있다.

기본 검사 대상은 Compose 내부의 `http://web/`과 준비 상태 API다. 운영 HTTPS나 서버 밖 검사는 `docker/monitoring/targets`를 환경별 디렉터리에 복사하고 `MONITORING_TARGETS_DIR`로 지정한다. `http.yml`의 `targets`를 고정 운영 URL로 바꾸고 `homepage`는 홈, `readiness`·`catalog`는 `/health/ready`로 지정한다. 검색 자료가 준비돼 있어야 하는 환경은 같은 URL에 `module: rag`, `check: rag`를 추가한다. 내부 검사는 호스트 자체가 멈추면 함께 중단된다. 서버 전체 중단도 알리려면 별도 호스트에서 `compose.monitoring.yaml`만 실행하고 그 호스트의 `api.yml`과 `jobs.yml`은 각각 `[]`로 설정한다. 외부 검사에는 고정 공개 URL을 사용한다. [Blackbox Exporter 설정](https://github.com/prometheus/blackbox_exporter/blob/master/CONFIGURATION.md)

호스트가 예약 실행하는 기존 [삭제 내보내기·백업·정리 명령](retention-backup.md#3-실행-예)에 `--env-file .env.monitoring`을 추가한다. 각 명령의 종료 결과가 Pushgateway에 기록되고 실패 뒤에도 마지막 성공 시각은 유지된다. 일일 성공 누락 감시는 `jobs.yml`의 `maintenance_expected`를 `"true"`로 바꾸면 활성화된다. 운영 스케줄에서 [법령 검토 기한 점검](../ai/knowledge-publication.md#검토-기한-점검과-갱신)도 하루 한 번 실행하고 `knowledge_expected`를 `"true"`로 바꾼다. 작업 결과와 지표 전송 오류는 각 명령의 출력으로 확인할 수 있다.

기본 Alertmanager 수신기는 외부 전송 없이 활성 경보를 유지한다. 실제 알림은 보호된 별도 디렉터리에 `webhook.example.yml`을 `alertmanager.yml`로 복사하고 승인된 수신기의 URL을 `webhook-url`에 저장한 뒤 `MONITORING_ALERTMANAGER_DIR`를 설정한다. 수신기는 Alertmanager webhook 페이로드를 처리할 수 있어야 한다. 설정을 적용한 뒤 해당 수신기에서 시험 경보와 복구 안내를 확인한다. [Alertmanager webhook 설정](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)

## 2. 답변 상태와 지연

`MONITORING_ENABLED=true`일 때 내부 `/internal/metrics`에서 Prometheus가 집계값을 읽는다. 결과 수는 DB에 새로 저장된 설문·챗봇 결과를 센다. 별도 카운터는 공급자 오류, 공급자 비활성화, 사용할 자료 없음으로 기본 안내가 선택된 횟수를 센다. 일반적인 추가 질문과 담당 기관 확인은 별도 결과 상태로 보인다. HTTP 429는 요청 한도에 도달한 횟수를 보여 준다.

초기 경보는 연속 접속 실패 약 3회, API 서버 오류 15분 내 5건 이상이면서 5% 이상, 공급자 오류 또는 자료 사용 불가 15분 내 흐름별 3회, 설문·챗봇의 429가 15분 내 경로별 10회를 기준으로 한다. 지연은 15분간 20건 이상인 경로에서 p95가 5분 동안 일반 API 1초, 설문 평가 8초, 챗봇 전송 20초를 초과하면 알린다. 실제 사용량과 배포 시간을 관찰해 조정한다.

지표 라벨은 경로 템플릿, HTTP 상태, 처리 흐름과 결과 분류 같은 고정 값만 사용한다. 요청의 세부 진단은 기존 구조화 로그의 traceId로 확인한다. 지표는 단일 API 워커를 기준으로 하며 Prometheus 저장소는 14일·1GB로 제한한다.

## 3. OpenAI 월 비용 경보

`.env.monitoring-cost.example`을 `.env.monitoring-cost`로 복사하고 조회할 OpenAI 프로젝트 ID, 월 예산(USD), 별도 관리자 키 파일 경로를 지정한다. 키 파일을 Git 저장소 밖에 두고 수집 컨테이너의 UID 10001이 읽을 수 있도록 접근을 제한한다. 키는 일회성 수집 컨테이너에만 읽기 전용으로 마운트된다. [OpenAI Costs API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)

모니터링을 실행한 Compose 프로젝트의 기존 옵션에 `--env-file .env.monitoring-cost -f compose.monitoring-cost.yaml`을 추가한다. 처음에는 `build monitoring-cost`로 이미지를 만들고, 같은 옵션으로 `run --rm --no-deps monitoring-cost`를 실행한다. 호스트 스케줄러에서 이 일회성 명령을 매시간 실행하고 겹치지 않게 설정한다. 첫 성공 후 `jobs.yml`의 `cost_expected`를 `"true"`로 바꾸면 3시간 이상 갱신되지 않을 때 알린다.

Grafana에는 UTC 기준 이번 달의 누적 금액과 예산 사용률, 마지막 수집 시각이 표시된다. 수집에 실패하면 직전 성공값이 남고, 오래된 값이나 이전 달 값으로 예산 경보를 내지 않는다. 경보는 예산의 80%와 100%에서 발생한다. 비용 반영에 지연이 있으므로 이 경보는 통지용이다. [OpenAI 프로젝트 지출 알림](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform)

## 설정 검증

Prometheus 이미지의 `promtool check config`로 설정을 검사하고 `promtool test rules /etc/prometheus/tests/rules.yml`을 실행한다. 두 명령에는 `docker/monitoring` 디렉터리를 `/etc/prometheus`에 읽기 전용으로 마운트한다. 운영에서는 홈·준비 상태 대상, 백업 및 삭제 성공 시각, Alertmanager 수신·복구 안내, 비용 수집 권한을 확인한다.
