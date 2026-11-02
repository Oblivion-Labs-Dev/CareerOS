#!/usr/bin/env bash
# Mirrors .github/workflows/ci.yml — all four jobs must pass.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
WEB_DIR="$ROOT/apps/web"
cd "$ROOT"

step() {
  printf '\n\033[36m==> %s\033[0m\n' "$1"
}

fail() {
  printf '\033[31m  FAIL  %s\033[0m\n' "$1" >&2
  exit 1
}

resolve_python() {
  if [[ -x "$API_DIR/.venv/bin/python" ]]; then
    echo "$API_DIR/.venv/bin/python"
  elif [[ -f "$API_DIR/.venv/Scripts/python.exe" ]]; then
    echo "$API_DIR/.venv/Scripts/python.exe"
  elif command -v python3 >/dev/null 2>&1; then
    echo "python3"
  elif command -v python >/dev/null 2>&1; then
    echo "python"
  else
    fail "Python not found. Run scripts/setup.sh first."
  fi
}

PYTHON="$(resolve_python)"

step "CI / typecheck"
pnpm --filter @career-os/core build
pnpm typecheck

step "CI / extension-unit"
pnpm --filter @career-os/extension test

step "CI / api"
(
  cd "$API_DIR"
  "$PYTHON" -m pip install -q -r requirements.txt pytest httpx
  "$PYTHON" -m compileall app
  "$PYTHON" -m pytest tests -q
)

step "CI / web-e2e (build)"
pnpm --filter @career-os/core build
pnpm --filter @career-os/web build

step "CI / web-e2e (playwright install)"
pnpm --filter @career-os/web exec playwright install chromium
if [[ "$(uname -s)" != "MINGW"* && "$(uname -s)" != "MSYS"* && "$(uname -s)" != "CYGWIN"* ]]; then
  pnpm --filter @career-os/web exec playwright install-deps chromium 2>/dev/null \
    || pnpm --filter @career-os/web exec playwright install chromium --with-deps
fi

step "CI / web-e2e (servers + tests)"
(
  cd "$API_DIR"
  "$PYTHON" -m pip install -q -r requirements.txt
  "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
  API_PID=$!
  cd "$WEB_DIR"
  pnpm start --port 3000 &
  WEB_PID=$!
  cleanup() {
    kill "$API_PID" "$WEB_PID" 2>/dev/null || true
    wait "$API_PID" "$WEB_PID" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM
  npx --yes wait-on "http://127.0.0.1:8000/health" "http://127.0.0.1:3000" -t 120000
  cd "$ROOT"
  CI=1 pnpm --filter @career-os/web exec playwright test
)

printf '\n\033[32mAll CI checks passed (typecheck, extension-unit, api, web-e2e).\033[0m\n'
