#!/usr/bin/env bash
# Local equivalent of CI for Slice 0. GitHub Actions CI is deferred.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

make freeze-cognee-contract
/home/david/.venvs/archie-1.0/bin/pytest --require-fixtures -x -q
# Slice 1+: behavioral tests against the docker FalkorDB fixture.
