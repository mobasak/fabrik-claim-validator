#!/usr/bin/env bash
# fabrik-managed — regenerate via fabrik scaffold; keep in sync with .github/workflows/ci.yml.
# Local clean-room replica of CI: catches env drift (test-DB URL format, shared-DB test
# pollution, missing PG extension) that the static final_gate cannot. Run before pushing.
set -euo pipefail
cd "$(dirname "$0")/.."

PG_IMAGE="postgres:16"
command -v docker >/dev/null || { echo "[ci_local] docker is required" >&2; exit 1; }
echo "[ci_local] starting $PG_IMAGE"
CID=$(docker run -d --rm -e POSTGRES_PASSWORD=postgres -p 127.0.0.1::5432 "$PG_IMAGE")
trap 'docker stop "$CID" >/dev/null 2>&1 || true' EXIT
pg_ready=""
for _ in $(seq 1 60); do
  if docker exec "$CID" pg_isready -U postgres >/dev/null 2>&1; then pg_ready=1; break; fi
  sleep 1
done
[ -n "$pg_ready" ] || { echo "[ci_local] postgres not ready after 60s" >&2; exit 1; }
PGPORT=$(docker port "$CID" 5432/tcp | head -1 | sed "s/.*://")
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:$PGPORT/postgres"

VENV="$(mktemp -d)/venv"
python -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
if [ -f requirements.txt ]; then "$VENV/bin/pip" install --quiet -r requirements.txt; fi
if [ -f pyproject.toml ]; then "$VENV/bin/pip" install --quiet -e . || true; fi
"$VENV/bin/pip" install --quiet ruff==0.14.10 pytest pytest-asyncio
export PATH="$VENV/bin:$PATH"
n=$(ruff check . --exit-zero --output-format=json 2>/dev/null | python -c 'import sys,json;sys.stdout.write(str(len(json.load(sys.stdin))))' || echo 0)
b=$(python -c "import sys,json;sys.stdout.write(str(json.load(open('.fabrik/lint-baseline.json'))['ruff_errors']))" 2>/dev/null || echo "$n")
echo "[ci_local] ruff: $n errors (baseline $b)"
[ "$n" -le "$b" ] || { echo "[ci_local] ruff rose $b -> $n (new lint debt)" >&2; exit 1; }
python -m pytest -q || { c=$?; [ "$c" -eq 5 ] && echo "[ci_local] no tests collected" || exit "$c"; }
echo "[ci_local] OK — matches CI"
