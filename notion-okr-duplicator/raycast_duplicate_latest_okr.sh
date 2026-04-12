#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Duplicate Latest Notion OKR
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🔁
# @raycast.packageName Notion
# @raycast.argument1 { "type": "dropdown", "placeholder": "Mode", "data": [{"title": "Dry Run", "value": ""}, {"title": "Execute", "value": "--execute"}] }

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
exec "$script_dir/run_okr_duplicate.sh" ${1:-}
