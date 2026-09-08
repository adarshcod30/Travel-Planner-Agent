#!/usr/bin/env bash
# Remove everything this project generates but does not need kept.
#
# Nothing here is source and nothing here is tracked — every path is either a
# tool cache or a run artifact, and all of them are rebuilt on demand. The one
# worth knowing about is `.playwright-mcp/`: Playwright MCP writes a console log
# and a full page dump for every browser action, and it reached 2,714 files and
# 224 MB in this repository before anyone looked. Neither `--output-dir` nor the
# subprocess working directory moves it (measured on 0.0.80), so clearing it
# periodically is the available answer.
#
#   ./scripts/clean.sh          # caches and browser debris
#   ./scripts/clean.sh --all    # the above, plus .venv and node_modules
set -euo pipefail
cd "$(dirname "$0")/.."

human() { du -sh "$1" 2>/dev/null | cut -f1; }

drop() {
  [[ -e "$1" ]] || return 0
  echo "  $(printf '%-28s' "$1") $(human "$1")"
  rm -rf "$1"
}

echo "== Tool caches"
drop .mypy_cache
drop .pytest_cache
drop .ruff_cache

echo "== Browser and run artifacts"
drop .playwright-mcp
# Per-run screenshots. `storage._purge_artifacts` clears these when a trip is
# archived; what is left belongs to runs nobody finished.
if [[ -d data/runs ]]; then
  echo "  $(printf '%-28s' 'data/runs/*') $(human data/runs)"
  rm -rf data/runs/*
fi

if [[ "${1:-}" == "--all" ]]; then
  echo "== Dependencies"
  echo "   rebuild: uv sync --extra dev --extra server --extra mcp && npm --prefix frontend ci"
  drop .venv
  drop frontend/node_modules
  drop frontend/.next
fi

echo "== Done. Project is now $(human .)"
