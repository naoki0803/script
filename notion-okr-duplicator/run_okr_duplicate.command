#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
exec "$script_dir/run_okr_duplicate.sh" --execute
