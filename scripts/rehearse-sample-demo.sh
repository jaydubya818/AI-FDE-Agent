#!/usr/bin/env bash
set -euo pipefail

demo_project="ai-fde-demo-rehearsal"
demo_postgres_port="${AI_FDE_DEMO_POSTGRES_PORT:-55435}"
demo_minio_api_port="${AI_FDE_DEMO_MINIO_API_PORT:-59030}"
demo_minio_console_port="${AI_FDE_DEMO_MINIO_CONSOLE_PORT:-59031}"
demo_api_port="${AI_FDE_DEMO_API_PORT:-8101}"
demo_web_port="${AI_FDE_DEMO_WEB_PORT:-3101}"
demo_test_script="${AI_FDE_DEMO_TEST_SCRIPT:-test:e2e:golden}"
demo_evidence_name="${AI_FDE_DEMO_EVIDENCE_NAME:-demo}"
demo_log_directory="$(mktemp -d "${TMPDIR:-/tmp}/ai-fde-demo.XXXXXX")"
demo_standalone_directory="apps/web/.next/standalone/apps/web"
demo_api_pid=""
demo_worker_pid=""
demo_web_pid=""
demo_started_at="${SECONDS}"

case "${demo_test_script}" in
  test:e2e:golden | test:e2e:alpha) ;;
  *)
    echo "AI_FDE_DEMO_TEST_SCRIPT must be test:e2e:golden or test:e2e:alpha."
    exit 1
    ;;
esac

case "${demo_evidence_name}" in
  demo | internal-alpha) ;;
  *)
    echo "AI_FDE_DEMO_EVIDENCE_NAME must be demo or internal-alpha."
    exit 1
    ;;
esac

cleanup() {
  demo_status=$?
  trap - EXIT INT TERM
  set +e

  for demo_pid in "${demo_web_pid}" "${demo_worker_pid}" "${demo_api_pid}"; do
    if [[ -n "${demo_pid}" ]] && kill -0 "${demo_pid}" >/dev/null 2>&1; then
      kill "${demo_pid}" >/dev/null 2>&1
      wait "${demo_pid}" >/dev/null 2>&1
    fi
  done

  docker compose -p "${demo_project}" down --volumes --remove-orphans >/dev/null 2>&1 || true

  if [[ "${demo_status}" -eq 0 ]]; then
    rm -rf "${demo_log_directory}"
  else
    echo "Sample demo rehearsal failed. Bounded service logs remain at ${demo_log_directory}."
    for demo_log in "${demo_log_directory}"/*.log; do
      if [[ -f "${demo_log}" ]]; then
        echo "Last 40 lines of ${demo_log}:"
        tail -40 "${demo_log}"
      fi
    done
  fi

  exit "${demo_status}"
}
trap cleanup EXIT INT TERM

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command is missing: $1"
    exit 1
  fi
}

require_free_port() {
  if lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Demo port $1 is already in use. Override the corresponding AI_FDE_DEMO_*_PORT value."
    exit 1
  fi
}

wait_for_url() {
  demo_url="$1"
  demo_label="$2"
  demo_attempt=0
  until curl --fail --silent --show-error "${demo_url}" >/dev/null 2>&1; do
    demo_attempt=$((demo_attempt + 1))
    if [[ "${demo_attempt}" -ge 120 ]]; then
      echo "Timed out waiting for ${demo_label} at ${demo_url}."
      exit 1
    fi
    sleep 0.5
  done
}

for demo_command in docker uv pnpm curl lsof; do
  require_command "${demo_command}"
done

for demo_port in \
  "${demo_postgres_port}" \
  "${demo_minio_api_port}" \
  "${demo_minio_console_port}" \
  "${demo_api_port}" \
  "${demo_web_port}"; do
  require_free_port "${demo_port}"
done

export AI_FDE_POSTGRES_HOST_PORT="${demo_postgres_port}"
export AI_FDE_MINIO_API_HOST_PORT="${demo_minio_api_port}"
export AI_FDE_MINIO_CONSOLE_HOST_PORT="${demo_minio_console_port}"
export AI_FDE_ENV="development"
export AI_FDE_RUNTIME_ROLE="api"
export AI_FDE_AUTH_MODE="development"
export AI_FDE_DATABASE_URL="postgresql+psycopg://ai_fde_app:ai_fde_app@localhost:${demo_postgres_port}/ai_fde"
export AI_FDE_MIGRATION_DATABASE_URL="postgresql+psycopg://ai_fde_owner:ai_fde_owner@localhost:${demo_postgres_port}/ai_fde"
export AI_FDE_ALLOWED_ORIGINS="[\"http://localhost:${demo_web_port}\"]"
export AI_FDE_COCKPIT_URL="http://localhost:${demo_web_port}"
export AI_FDE_S3_ENDPOINT_URL="http://localhost:${demo_minio_api_port}"
export AI_FDE_S3_ACCESS_KEY="ai-fde-dev"
export AI_FDE_S3_SECRET_KEY="ai-fde-dev-secret"
export AI_FDE_S3_BUCKET="ai-fde-demo-rehearsal-evidence"
export AI_FDE_S3_REGION="us-east-1"
export AI_FDE_S3_USE_WORKLOAD_IDENTITY="false"
export AI_FDE_EXTRACTION_PROVIDER="deterministic"
export AI_FDE_SANITIZED_DATA_ENABLED="false"
export AI_FDE_WORKER_POLL_SECONDS="0.2"
export NEXT_PUBLIC_AI_FDE_API_URL="http://localhost:${demo_api_port}/api"

docker compose -p "${demo_project}" down --volumes --remove-orphans >/dev/null 2>&1 || true
docker compose -p "${demo_project}" up -d --wait postgres minio

AI_FDE_RUNTIME_ROLE=migration uv run alembic upgrade head
AI_FDE_RUNTIME_ROLE=migration uv run alembic check
PYTHONPATH=src uv run python -m ai_fde.seed

pnpm --dir apps/web build >"${demo_log_directory}/build.log" 2>&1

if [[ ! -f "${demo_standalone_directory}/server.js" ]]; then
  echo "Next.js standalone server was not generated at ${demo_standalone_directory}/server.js."
  exit 1
fi

mkdir -p "${demo_standalone_directory}/.next"
cp -R apps/web/.next/static "${demo_standalone_directory}/.next/"
if [[ -d apps/web/public ]]; then
  cp -R apps/web/public "${demo_standalone_directory}/"
fi

PYTHONPATH=src uv run uvicorn apps.api.main:app \
  --host 127.0.0.1 \
  --port "${demo_api_port}" \
  --no-access-log >"${demo_log_directory}/api.log" 2>&1 &
demo_api_pid=$!

AI_FDE_RUNTIME_ROLE=worker PYTHONPATH=src uv run python -m ai_fde.worker \
  >"${demo_log_directory}/worker.log" 2>&1 &
demo_worker_pid=$!

HOSTNAME=127.0.0.1 PORT="${demo_web_port}" node "${demo_standalone_directory}/server.js" \
  >"${demo_log_directory}/web.log" 2>&1 &
demo_web_pid=$!

wait_for_url "http://localhost:${demo_api_port}/api/health" "API"
wait_for_url "http://localhost:${demo_web_port}" "Operator Cockpit"

mkdir -p "output/playwright/${demo_evidence_name}"
AI_FDE_PLAYWRIGHT_BASE_URL="http://localhost:${demo_web_port}" \
AI_FDE_PLAYWRIGHT_EXTERNAL_SERVER="true" \
AI_FDE_DEMO_SCREENSHOT="$(pwd)/output/playwright/demo/demo-complete.png" \
pnpm --dir apps/web run "${demo_test_script}"

demo_duration=$((SECONDS - demo_started_at))
echo "Sample ${demo_evidence_name} rehearsal passed in ${demo_duration} seconds."
if [[ "${demo_test_script}" == "test:e2e:alpha" ]]; then
  echo "Final browser evidence: output/playwright/internal-alpha/internal-alpha-scorecard.png"
else
  echo "Final browser evidence: output/playwright/demo/demo-complete.png"
fi
