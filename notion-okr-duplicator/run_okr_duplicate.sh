#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_file="${NOTION_OKR_CONFIG:-$script_dir/.env.local}"

env_notion_token="${NOTION_TOKEN-__UNSET__}"
env_notion_base_url="${NOTION_BASE_URL-__UNSET__}"
env_notion_page_id="${NOTION_PAGE_ID-__UNSET__}"
env_notion_database_id="${NOTION_DATABASE_ID-__UNSET__}"
env_notion_data_source_id="${NOTION_DATA_SOURCE_ID-__UNSET__}"
env_notion_child_database_title="${NOTION_CHILD_DATABASE_TITLE-__UNSET__}"
env_notion_data_source_name="${NOTION_DATA_SOURCE_NAME-__UNSET__}"
env_notion_period_property="${NOTION_PERIOD_PROPERTY-__UNSET__}"
env_notion_object_property="${NOTION_OBJECT_PROPERTY-__UNSET__}"
env_notion_key_property="${NOTION_KEY_PROPERTY-__UNSET__}"
env_notion_timeout_seconds="${NOTION_TIMEOUT_SECONDS-__UNSET__}"
env_notion_limit="${NOTION_LIMIT-__UNSET__}"
env_notion_execute="${NOTION_EXECUTE-__UNSET__}"

if [[ -f "$config_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$config_file"
  set +a
fi

if [[ "$env_notion_token" != "__UNSET__" ]]; then NOTION_TOKEN="$env_notion_token"; fi
if [[ "$env_notion_base_url" != "__UNSET__" ]]; then NOTION_BASE_URL="$env_notion_base_url"; fi
if [[ "$env_notion_page_id" != "__UNSET__" ]]; then NOTION_PAGE_ID="$env_notion_page_id"; fi
if [[ "$env_notion_database_id" != "__UNSET__" ]]; then NOTION_DATABASE_ID="$env_notion_database_id"; fi
if [[ "$env_notion_data_source_id" != "__UNSET__" ]]; then NOTION_DATA_SOURCE_ID="$env_notion_data_source_id"; fi
if [[ "$env_notion_child_database_title" != "__UNSET__" ]]; then NOTION_CHILD_DATABASE_TITLE="$env_notion_child_database_title"; fi
if [[ "$env_notion_data_source_name" != "__UNSET__" ]]; then NOTION_DATA_SOURCE_NAME="$env_notion_data_source_name"; fi
if [[ "$env_notion_period_property" != "__UNSET__" ]]; then NOTION_PERIOD_PROPERTY="$env_notion_period_property"; fi
if [[ "$env_notion_object_property" != "__UNSET__" ]]; then NOTION_OBJECT_PROPERTY="$env_notion_object_property"; fi
if [[ "$env_notion_key_property" != "__UNSET__" ]]; then NOTION_KEY_PROPERTY="$env_notion_key_property"; fi
if [[ "$env_notion_timeout_seconds" != "__UNSET__" ]]; then NOTION_TIMEOUT_SECONDS="$env_notion_timeout_seconds"; fi
if [[ "$env_notion_limit" != "__UNSET__" ]]; then NOTION_LIMIT="$env_notion_limit"; fi
if [[ "$env_notion_execute" != "__UNSET__" ]]; then NOTION_EXECUTE="$env_notion_execute"; fi

args=()

if [[ -n "${NOTION_TOKEN:-}" ]]; then
  args+=(--notion-token "$NOTION_TOKEN")
fi

if [[ -n "${NOTION_BASE_URL:-}" ]]; then
  args+=(--notion-base-url "$NOTION_BASE_URL")
fi

if [[ -n "${NOTION_PAGE_ID:-}" ]]; then
  args+=(--page-id "$NOTION_PAGE_ID")
fi

if [[ -n "${NOTION_DATABASE_ID:-}" ]]; then
  args+=(--database-id "$NOTION_DATABASE_ID")
fi

if [[ -n "${NOTION_DATA_SOURCE_ID:-}" ]]; then
  args+=(--data-source-id "$NOTION_DATA_SOURCE_ID")
fi

if [[ -n "${NOTION_CHILD_DATABASE_TITLE:-}" ]]; then
  args+=(--child-database-title "$NOTION_CHILD_DATABASE_TITLE")
fi

if [[ -n "${NOTION_DATA_SOURCE_NAME:-}" ]]; then
  args+=(--data-source-name "$NOTION_DATA_SOURCE_NAME")
fi

if [[ -n "${NOTION_PERIOD_PROPERTY:-}" ]]; then
  args+=(--period-property "$NOTION_PERIOD_PROPERTY")
fi

if [[ -n "${NOTION_OBJECT_PROPERTY:-}" ]]; then
  args+=(--object-property "$NOTION_OBJECT_PROPERTY")
fi

if [[ -n "${NOTION_KEY_PROPERTY:-}" ]]; then
  args+=(--key-property "$NOTION_KEY_PROPERTY")
fi

if [[ -n "${NOTION_TIMEOUT_SECONDS:-}" ]]; then
  args+=(--timeout-seconds "$NOTION_TIMEOUT_SECONDS")
fi

if [[ -n "${NOTION_LIMIT:-}" ]]; then
  args+=(--limit "$NOTION_LIMIT")
fi

if [[ "${NOTION_EXECUTE:-false}" == "true" ]]; then
  args+=(--execute)
fi

command=(/usr/bin/env python3 "$script_dir/okr_duplicate.py")

if (( ${#args[@]} > 0 )); then
  command+=("${args[@]}")
fi

if (( $# > 0 )); then
  command+=("$@")
fi

exec "${command[@]}"
