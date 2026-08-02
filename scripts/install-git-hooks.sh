#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$ROOT/.githooks"

[[ -d "$HOOKS_DIR" ]] || { echo "Missing .githooks directory"; exit 1; }

cd "$ROOT"
git config core.hooksPath .githooks
chmod +x "$HOOKS_DIR"/pre-commit "$HOOKS_DIR"/pre-push "$ROOT/scripts/ci.sh" 2>/dev/null || true
echo "Git hooks path set to .githooks"
echo "  pre-commit and pre-push run: pnpm ci (all 4 GitHub Actions jobs)"
echo "  Skip once: SKIP_CI=1 git commit ...  or  git commit --no-verify"
