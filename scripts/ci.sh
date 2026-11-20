#!/usr/bin/env bash
set -euo pipefail

workspace=$(git rev-parse --show-toplevel)
workspace=${workspace%$'\r'}
cd "$workspace"
project_hash=$(printf '%s\n' "${BUILD_TAG:-local}" "$workspace" | sha256sum | cut -c1-16)
project="repair-guide-ci-$project_hash"
python_bin=${PYTHON_BIN:-python3}
ops_image="$project-ops"

# Shell variables take precedence over Compose env files. Use the checked-in test values.
while IFS='=' read -r key _; do
    if [[ $key =~ ^[A-Z][A-Z0-9_]*$ ]]; then
        unset "$key"
    fi
done < <(cat .env.example .env.test.example)
unset REPAIR_CI_ORIGIN_PORT E2E_ALLOW_SELF_SIGNED

compose=(
    docker compose -p "$project" --env-file .env.example --env-file .env.test.example
    -f compose.yaml -f compose.test.yaml -f compose.ci.yaml
)

dc() { "${compose[@]}" "$@"; }
admin() { dc -f compose.admin.yaml run --rm --no-deps api "$@"; }

web_port() {
    local binding
    binding=$(dc port web 80)
    binding=${binding%$'\r'}
    if [[ ! $binding =~ ^127\.0\.0\.1:([0-9]+)$ ]]; then
        echo "Expected a loopback port for the isolated web service." >&2
        return 1
    fi
    printf '%s\n' "${BASH_REMATCH[1]}"
}

monitoring_image() {
    MONITORING_GRAFANA_PASSWORD=ci-unused docker compose -p "$project" \
        --env-file .env.example -f compose.monitoring.yaml config --images "$1"
}

case "${1:-}" in
    prepare)
        docker compose version
        engine=$(docker info --format '{{.OSType}}')
        [[ ${engine%$'\r'} == linux ]]
        node -e 'const [major, minor, patch] = process.versions.node.split(".").map(Number); if (major !== 22 || minor < 22 || (minor === 22 && patch < 2)) throw Error("Node 22.22.2+ is required");'
        "$python_bin" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
        mkdir -p artifacts/junit artifacts/m11 artifacts/ci
        ;;
    frontend)
        cd frontend
        npm ci
        npm run typecheck
        npm run lint
        npm test -- --reporter=default --reporter=junit --outputFile.junit=../artifacts/junit/frontend.xml
        npm run build
        npm run types
        git diff --exit-code -- src/api/generated/schema.ts
        npx playwright install chromium
        ;;
    backend)
        dc build api web
        dc up -d --wait db
        admin python -m alembic upgrade head
        dc run --rm --no-deps api python -m ruff check --no-cache app tests
        dc run --rm --no-deps --user "$(id -u):$(id -g)" \
            -v "$workspace/artifacts/junit:/reports" api \
            python -m pytest -q -p no:cacheprovider --junitxml=/reports/backend.xml
        dc run --rm --no-deps api python -m scripts.export_openapi --check
        admin python -m alembic check
        ;;
    monitoring)
        prom_image=$(monitoring_image prometheus)
        alert_image=$(monitoring_image alertmanager)
        blackbox_image=$(monitoring_image blackbox)
        monitor="$workspace/docker/monitoring"
        docker run --rm --entrypoint /bin/promtool -v "$monitor:/etc/prometheus:ro" \
            "$prom_image" check config /etc/prometheus/prometheus.yml
        docker run --rm --entrypoint /bin/promtool -v "$monitor:/etc/prometheus:ro" \
            "$prom_image" test rules /etc/prometheus/tests/rules.yml
        docker run --rm --entrypoint /bin/amtool -v "$monitor/alertmanager:/etc/alertmanager:ro" \
            "$alert_image" check-config /etc/alertmanager/alertmanager.yml /etc/alertmanager/webhook.example.yml
        docker run --rm -v "$monitor/blackbox.yml:/etc/blackbox/blackbox.yml:ro" \
            "$blackbox_image" --config.file=/etc/blackbox/blackbox.yml --config.check
        ;;
    restore)
        docker build -f backend/Dockerfile.ops -t "$ops_image" backend
        docker run --rm --network "${project}_default" --user "$(id -u):$(id -g)" \
            --env-file .env.test.example --env PYTHONPATH=/app \
            -v "$workspace/scripts:/app/drills:ro" -v "$workspace/artifacts/m11:/drill" \
            --entrypoint /bin/sh "$ops_image" -ec \
            'export DATABASE_URL="$MIGRATION_DATABASE_URL"; exec python /app/drills/drill_backup.py'
        ;;
    browser)
        dc run --rm --no-deps api python -m app.commands.catalog publish /data/catalog/m08a-20261004/catalog.json
        dc up -d --no-deps --no-build web
        REPAIR_CI_ORIGIN_PORT=$(web_port)
        export REPAIR_CI_ORIGIN_PORT
        dc up -d --no-build --wait api web
        E2E_BASE_URL="http://localhost:$REPAIR_CI_ORIGIN_PORT" \
            PLAYWRIGHT_JUNIT_OUTPUT_FILE="$workspace/artifacts/junit/browser.xml" \
            npm --prefix frontend run test:e2e -- --reporter=list,junit
        ;;
    resilience)
        port=$(web_port)
        "$python_bin" -m venv .cache/ci-python
        ci_python=.cache/ci-python/bin/python
        if [[ ! -x $ci_python ]]; then
            ci_python=.cache/ci-python/Scripts/python.exe
        fi
        "$ci_python" -m pip install httpx==0.28.1
        "$ci_python" scripts/load_api.py --port "$port"
        "$ci_python" scripts/drill_outage.py --ci-project "$project" --port "$port"
        ;;
    diagnostics)
        mkdir -p artifacts/ci
        dc logs --no-color --tail 200 > artifacts/ci/compose.log 2>&1
        ;;
    cleanup)
        dc down --volumes --rmi local
        if docker image inspect "$ops_image" >/dev/null 2>&1; then
            docker image rm "$ops_image"
        fi
        ;;
    *)
        echo "Usage: bash scripts/ci.sh {prepare|frontend|backend|monitoring|restore|browser|resilience|diagnostics|cleanup}" >&2
        exit 2
        ;;
esac
