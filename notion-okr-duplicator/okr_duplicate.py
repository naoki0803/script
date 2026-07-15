#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib import error, parse, request

DEFAULT_NOTION_API_BASE_URL = "https://api.notion.com"
NOTION_VERSION = "2026-03-11"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_WARNING_PREVIEW = 5

READ_ONLY_PROPERTY_TYPES = {
    "button",
    "created_by",
    "created_time",
    "formula",
    "last_edited_by",
    "last_edited_time",
    "rollup",
    "unique_id",
    "verification",
}


class NotionAutomationError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class YearMonth:
    year: int
    month: int

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class NotionClient:
    def __init__(self, token: str, timeout_seconds: float, base_url: str) -> None:
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url.rstrip("/")

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        if query:
            clean_query = {key: value for key, value in query.items() if value is not None}
            url = f"{url}?{parse.urlencode(clean_query, doseq=True)}"

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Accept": "application/json",
        }
        data: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")

        req = request.Request(url=url, method=method, data=data, headers=headers)
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                body = {"message": raw_body}

            message = localize_notion_api_error_message(
                status_code=exc.code,
                path=path,
                notion_error_code=body.get("code"),
            )
            raise NotionAutomationError(
                f"Notion API エラー (HTTP {exc.code}, {method} {path}): {message}"
            ) from exc
        except error.URLError as exc:
            raise NotionAutomationError(
                f"Notion API への接続に失敗しました: {exc.reason}"
            ) from exc

    def list_block_children(self, block_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_cursor: str | None = None

        while True:
            response = self.request_json(
                method="GET",
                path=f"/v1/blocks/{block_id}/children",
                query={"page_size": 100, "start_cursor": next_cursor},
            )
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")

    def query_all_pages(self, data_source_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_cursor: str | None = None

        while True:
            payload: dict[str, Any] = {
                "page_size": 100,
            }
            if next_cursor:
                payload["start_cursor"] = next_cursor

            response = self.request_json(
                method="POST",
                path=f"/v1/data_sources/{data_source_id}/query",
                payload=payload,
            )
            results.extend([item for item in response.get("results", []) if item.get("object") == "page"])
            if not response.get("has_more"):
                return results
            next_cursor = response.get("next_cursor")

    def get_page(self, page_id: str) -> dict[str, Any]:
        normalized_id = normalize_notion_id(page_id)
        return self.request_json("GET", f"/v1/pages/{normalized_id}")


def normalize_notion_id(raw_value: str) -> str:
    candidate = raw_value.strip()
    match = re.search(
        r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        candidate,
    )
    if not match:
        raise NotionAutomationError(
            f"Notion ID を抽出できませんでした: {raw_value}"
        )

    compact = match.group(1).replace("-", "").lower()
    return f"{compact[:8]}-{compact[8:12]}-{compact[12:16]}-{compact[16:20]}-{compact[20:]}"


def rich_text_to_plain_text(items: list[dict[str, Any]]) -> str:
    return "".join(item.get("plain_text", "") for item in items)


def property_to_plain_text(
    value: dict[str, Any],
    client: NotionClient | None = None,
    relation_title_cache: dict[str, str] | None = None,
) -> str:
    property_type = value.get("type")

    if property_type == "title":
        return rich_text_to_plain_text(value.get("title", []))
    if property_type == "rich_text":
        return rich_text_to_plain_text(value.get("rich_text", []))
    if property_type == "number":
        number = value.get("number")
        return "" if number is None else str(number)
    if property_type == "select":
        selected = value.get("select")
        return "" if not selected else selected.get("name", "")
    if property_type == "status":
        status = value.get("status")
        return "" if not status else status.get("name", "")
    if property_type == "date":
        date_value = value.get("date")
        return "" if not date_value else date_value.get("start", "")
    if property_type == "formula":
        formula = value.get("formula", {})
        formula_type = formula.get("type")
        if formula_type == "string":
            return formula.get("string") or ""
        if formula_type == "number":
            number = formula.get("number")
            return "" if number is None else str(number)
        if formula_type == "date":
            date_value = formula.get("date")
            return "" if not date_value else date_value.get("start", "")
        return ""
    if property_type == "checkbox":
        return "true" if value.get("checkbox") else "false"
    if property_type == "url":
        return value.get("url") or ""
    if property_type == "email":
        return value.get("email") or ""
    if property_type == "phone_number":
        return value.get("phone_number") or ""
    if property_type == "multi_select":
        return ",".join(item.get("name", "") for item in value.get("multi_select", []))
    if property_type == "people":
        return ",".join(person.get("name") or person.get("id", "") for person in value.get("people", []))
    if property_type == "relation":
        relation_items = value.get("relation", [])
        if relation_items and client and relation_title_cache is not None:
            return ",".join(
                resolve_relation_page_title(client, relation_title_cache, item.get("id", ""))
                for item in relation_items
            )
        return ",".join(item.get("id", "") for item in relation_items)
    if property_type == "unique_id":
        unique_id = value.get("unique_id")
        if not unique_id:
            return ""
        prefix = unique_id.get("prefix") or ""
        number = unique_id.get("number")
        return f"{prefix}{number}" if number is not None else prefix

    return ""


def parse_year_month(raw_value: str) -> YearMonth | None:
    value = raw_value.strip()
    if not value:
        return None

    iso_match = re.match(r"^(\d{4})-(\d{2})(?:-\d{2})?", value)
    if iso_match:
        return build_year_month(iso_match.group(1), iso_match.group(2))

    compact_match = re.match(r"^(\d{4})(\d{2})$", value)
    if compact_match:
        return build_year_month(compact_match.group(1), compact_match.group(2))

    generic_match = re.search(r"(\d{4})\D{0,3}(\d{1,2})", value)
    if generic_match:
        return build_year_month(generic_match.group(1), generic_match.group(2))

    return None


def build_year_month(year_text: str, month_text: str) -> YearMonth | None:
    year = int(year_text)
    month = int(month_text)
    if month < 1 or month > 12:
        return None
    return YearMonth(year=year, month=month)


def localize_notion_api_error_message(
    *,
    status_code: int,
    path: str,
    notion_error_code: str | None,
) -> str:
    if status_code == 400 and notion_error_code == "validation_error":
        return "Notion API に渡した値が不正です。設定内容やプロパティ名を確認してください。"
    if status_code == 401:
        return "認証に失敗しました。NOTION_TOKEN が正しいか確認してください。"
    if status_code == 403:
        return "権限が不足しています。integration の権限設定と接続先を確認してください。"
    if status_code == 404 and path.startswith("/v1/blocks/"):
        return (
            "指定したページまたはブロックが見つかりません。NOTION_PAGE_ID を使う場合は、"
            "そのページ自体を integration に共有してください。データベースだけ共有している場合は "
            "NOTION_DATABASE_ID または NOTION_DATA_SOURCE_ID を使ってください。"
        )
    if status_code == 404 and path.startswith("/v1/databases/"):
        return (
            "指定したデータベースが見つかりません。Notion で親ページまたは inline database を開き、"
            "••• → Add connections から integration を接続してください。"
            "すでに接続済みなら、対象ワークスペースと対象データベースが正しいか確認してください。"
        )
    if status_code == 404 and path.startswith("/v1/data_sources/"):
        return (
            "指定したデータソースが見つかりません。integration からまだそのデータソースが見えていません。"
            "Notion で親ページまたはデータベースを開き、••• → Add connections から再接続してください。"
        )
    if status_code == 429:
        return "Notion API の呼び出し回数制限に達しました。少し待ってから再実行してください。"
    return "Notion API でエラーが発生しました。設定値や接続状態を確認してください。"


def find_title_property_name(properties: dict[str, Any]) -> str | None:
    for name, definition in properties.items():
        if definition.get("type") == "title":
            return name
    return None


def find_created_time_property_name(properties: dict[str, Any]) -> str | None:
    for name, definition in properties.items():
        if definition.get("type") == "created_time":
            return name
    return None


def get_page_title(page: dict[str, Any]) -> str:
    properties = page.get("properties", {})
    for property_name, value in properties.items():
        if value.get("type") == "title":
            title = property_to_plain_text(value).strip()
            if title:
                return title
    return page.get("id", "")


def resolve_relation_page_title(
    client: NotionClient,
    relation_title_cache: dict[str, str],
    page_id: str,
) -> str:
    normalized_page_id = normalize_notion_id(page_id)
    if normalized_page_id in relation_title_cache:
        return relation_title_cache[normalized_page_id]

    page = client.get_page(normalized_page_id)
    title = get_page_title(page)
    relation_title_cache[normalized_page_id] = title
    return title


def get_page_created_timestamp(
    page: dict[str, Any],
    created_time_property_name: str | None,
) -> str:
    if created_time_property_name:
        property_value = page.get("properties", {}).get(created_time_property_name, {})
        created_time = property_value.get("created_time")
        if created_time:
            return created_time
    return page.get("created_time", "")


def get_local_date_string_from_timestamp(timestamp: str) -> str:
    if not timestamp:
        return ""

    try:
        return (
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            .astimezone()
            .date()
            .isoformat()
        )
    except ValueError:
        return ""


def is_blank_result_page(
    page: dict[str, Any],
    title_property_name: str | None,
) -> bool:
    if not title_property_name:
        return False

    title_property = page.get("properties", {}).get(title_property_name, {})
    return property_to_plain_text(title_property).strip() == ""


def get_result_text(
    page: dict[str, Any],
    title_property_name: str | None,
) -> str:
    if not title_property_name:
        return ""

    title_property = page.get("properties", {}).get(title_property_name, {})
    return property_to_plain_text(title_property).strip()


def resolve_data_source_id(
    client: NotionClient,
    *,
    data_source_id: str | None,
    database_id: str | None,
    page_id: str | None,
    child_database_title: str | None,
    data_source_name: str | None,
) -> tuple[str, str]:
    if data_source_id:
        normalized_id = normalize_notion_id(data_source_id)
        data_source = client.request_json("GET", f"/v1/data_sources/{normalized_id}")
        return normalized_id, rich_text_to_plain_text(data_source.get("title", [])) or normalized_id

    if database_id:
        return resolve_data_source_id_from_database(
            client,
            database_id=normalize_notion_id(database_id),
            data_source_name=data_source_name,
        )

    if page_id:
        return resolve_data_source_id_from_page(
            client,
            page_id=normalize_notion_id(page_id),
            child_database_title=child_database_title,
            data_source_name=data_source_name,
        )

    raise NotionAutomationError(
        "ページ ID、データベース ID、またはデータソース ID のいずれかが必要です。"
        "NOTION_PAGE_ID、NOTION_DATABASE_ID、NOTION_DATA_SOURCE_ID のいずれかを設定してください。"
    )


def resolve_data_source_id_from_page(
    client: NotionClient,
    *,
    page_id: str,
    child_database_title: str | None,
    data_source_name: str | None,
) -> tuple[str, str]:
    children = client.list_block_children(page_id)
    child_databases = [block for block in children if block.get("type") == "child_database"]
    if not child_databases:
        raise NotionAutomationError(
            "指定したページ内に child database ブロックが見つかりませんでした。"
            "NOTION_DATABASE_ID または NOTION_DATA_SOURCE_ID を直接指定してください。"
        )

    if child_database_title:
        matching = [
            block
            for block in child_databases
            if block.get("child_database", {}).get("title") == child_database_title
        ]
        if not matching:
            available = [block.get("child_database", {}).get("title", "(無題)") for block in child_databases]
            raise NotionAutomationError(
                f"タイトルが '{child_database_title}' の子データベースが見つかりませんでした。"
                f"利用可能な子データベース: {', '.join(available)}"
            )
        chosen_database = matching[0]
    elif len(child_databases) == 1:
        chosen_database = child_databases[0]
    else:
        available = [block.get("child_database", {}).get("title", "(無題)") for block in child_databases]
        raise NotionAutomationError(
            "指定したページには複数の子データベースがあります。"
            "どれを使うか NOTION_CHILD_DATABASE_TITLE で指定してください。"
            f"利用可能な子データベース: {', '.join(available)}"
        )

    return resolve_data_source_id_from_database(
        client,
        database_id=normalize_notion_id(chosen_database["id"]),
        data_source_name=data_source_name,
    )


def resolve_data_source_id_from_database(
    client: NotionClient,
    *,
    database_id: str,
    data_source_name: str | None,
) -> tuple[str, str]:
    database = client.request_json("GET", f"/v1/databases/{database_id}")
    data_sources = database.get("data_sources", [])
    if not data_sources:
        raise NotionAutomationError(
            "データベースは見えていますが、integration からアクセス可能なデータソースがありません。"
            "対象データベースを Notion の integration に共有してから再実行してください。"
        )

    if data_source_name:
        matching = [item for item in data_sources if item.get("name") == data_source_name]
        if not matching:
            available = [item.get("name", "(無題)") for item in data_sources]
            raise NotionAutomationError(
                f"名前が '{data_source_name}' のデータソースが見つかりませんでした。"
                f"利用可能なデータソース: {', '.join(available)}"
            )
        chosen = matching[0]
    elif len(data_sources) == 1:
        chosen = data_sources[0]
    else:
        available = [item.get("name", "(無題)") for item in data_sources]
        raise NotionAutomationError(
            "指定したデータベースには複数のデータソースがあります。"
            "どれを使うか NOTION_DATA_SOURCE_NAME で指定してください。"
            f"利用可能なデータソース: {', '.join(available)}"
        )

    return normalize_notion_id(chosen["id"]), chosen.get("name") or database_id


# ---------------------------------------------------------------------------
# Keys-driven flow
# ---------------------------------------------------------------------------

def extract_key_groups_for_latest_period(
    *,
    client: NotionClient,
    key_pages: list[dict[str, Any]],
    keys_period_property_name: str,
    keys_object_property_name: str,
    relation_title_cache: dict[str, str],
) -> tuple[YearMonth, list[dict[str, Any]], list[str]]:
    """
    Keys テーブルを走査して最新の対象期間を持つ Key グループを返す。
    各グループは key_page / key_page_id / key_name / object_page_ids /
    object_name / period_page_ids / previous_result_text を持つ dict。
    """
    parsed: list[tuple[YearMonth, dict[str, Any]]] = []
    warnings: list[str] = []

    for key_page in key_pages:
        properties = key_page.get("properties", {})
        period_prop = properties.get(keys_period_property_name)
        if period_prop is None:
            warnings.append(
                f"Key '{get_page_title(key_page)}': プロパティ '{keys_period_property_name}' が見つかりません"
            )
            continue

        raw_period = property_to_plain_text(
            period_prop, client=client, relation_title_cache=relation_title_cache
        )
        parsed_period = parse_year_month(raw_period)
        if not parsed_period:
            warnings.append(
                f"Key '{get_page_title(key_page)}': '{keys_period_property_name}' を年月として解釈できませんでした: {raw_period or '(空)'}"
            )
            continue

        parsed.append((parsed_period, key_page))

    if not parsed:
        raise NotionAutomationError(
            f"'{keys_period_property_name}' を年月として解釈できるキーが見つかりませんでした。"
        )

    latest_period = max(p for p, _ in parsed)

    groups: list[dict[str, Any]] = []
    for period, key_page in parsed:
        if period != latest_period:
            continue

        key_page_id = normalize_notion_id(key_page.get("id", ""))
        key_props = key_page.get("properties", {})

        period_page_ids = [
            item.get("id", "")
            for item in key_props.get(keys_period_property_name, {}).get("relation", [])
        ]
        object_page_ids = [
            item.get("id", "")
            for item in key_props.get(keys_object_property_name, {}).get("relation", [])
        ]
        object_name = property_to_plain_text(
            key_props.get(keys_object_property_name, {}),
            client=client,
            relation_title_cache=relation_title_cache,
        ).strip()
        key_name = get_page_title(key_page)

        groups.append({
            "key_page": key_page,
            "key_page_id": key_page_id,
            "key_name": key_name,
            "object_page_ids": object_page_ids,
            "object_name": object_name,
            "period_page_ids": period_page_ids,
            "previous_result_text": "",
        })

    return latest_period, groups, warnings


def enrich_key_groups_with_previous_results(
    *,
    key_groups: list[dict[str, Any]],
    result_pages: list[dict[str, Any]],
    title_property_name: str | None,
    created_time_property_name: str | None,
    results_key_property_name: str,
) -> None:
    """Results テーブルから各 Key の直近の実施結果テキストを key_group に付与する。"""
    if not title_property_name:
        return

    # key_page_id → [(created_timestamp, result_text)]
    key_result_history: dict[str, list[tuple[str, str]]] = {}
    for result_page in result_pages:
        result_text = get_result_text(result_page, title_property_name)
        if not result_text:
            continue

        created_timestamp = get_page_created_timestamp(result_page, created_time_property_name)
        key_relations = (
            result_page.get("properties", {})
            .get(results_key_property_name, {})
            .get("relation", [])
        )
        for key_item in key_relations:
            key_id = normalize_notion_id(key_item.get("id", ""))
            key_result_history.setdefault(key_id, []).append((created_timestamp, result_text))

    for group in key_groups:
        history = key_result_history.get(group["key_page_id"], [])
        if history:
            group["previous_result_text"] = max(history, key=lambda x: x[0])[1]


def filter_key_groups_already_today(
    *,
    key_groups: list[dict[str, Any]],
    result_pages: list[dict[str, Any]],
    title_property_name: str | None,
    created_time_property_name: str | None,
    results_key_property_name: str,
) -> tuple[list[dict[str, Any]], int, str]:
    """本日すでに空の Results 行が作成済みの Key グループを除外する。"""
    today_local_date = datetime.now().astimezone().date().isoformat()
    keys_with_blank_result_today: set[str] = set()

    for result_page in result_pages:
        if not is_blank_result_page(result_page, title_property_name):
            continue

        created_timestamp = get_page_created_timestamp(result_page, created_time_property_name)
        if get_local_date_string_from_timestamp(created_timestamp) != today_local_date:
            continue

        key_relations = (
            result_page.get("properties", {})
            .get(results_key_property_name, {})
            .get("relation", [])
        )
        for key_item in key_relations:
            keys_with_blank_result_today.add(normalize_notion_id(key_item.get("id", "")))

    filtered: list[dict[str, Any]] = []
    skipped = 0
    for group in key_groups:
        if group["key_page_id"] in keys_with_blank_result_today:
            skipped += 1
        else:
            filtered.append(group)

    return filtered, skipped, today_local_date


def build_results_create_properties_from_key(
    *,
    results_schema_properties: dict[str, Any],
    key_page: dict[str, Any],
    key_page_id: str,
    results_key_property_name: str,
    results_period_property_name: str,
    results_object_property_name: str,
    keys_period_property_name: str,
    keys_object_property_name: str,
) -> tuple[dict[str, Any], set[str]]:
    """Key ページを元に、新しい Results 行の properties dict を構築する。"""
    create_properties: dict[str, Any] = {}
    skipped_properties: set[str] = set()
    key_props = key_page.get("properties", {})

    for property_name, definition in results_schema_properties.items():
        property_type = definition.get("type")

        if property_type == "title":
            # 実施結果は空欄にする
            create_properties[property_name] = {"title": []}

        elif property_name == results_key_property_name and property_type == "relation":
            # Keys relation に今回の Key をセット
            create_properties[property_name] = {"relation": [{"id": key_page_id}]}

        elif property_name == results_period_property_name and property_type == "relation":
            # Key の対象期間 relation をそのままコピー
            period_items = key_props.get(keys_period_property_name, {}).get("relation", [])
            if period_items:
                create_properties[property_name] = {
                    "relation": [{"id": item["id"]} for item in period_items]
                }

        elif property_name == results_object_property_name and property_type == "relation":
            # Key の Object relation をそのままコピー
            object_items = key_props.get(keys_object_property_name, {}).get("relation", [])
            if object_items:
                create_properties[property_name] = {
                    "relation": [{"id": item["id"]} for item in object_items]
                }

        elif property_type in READ_ONLY_PROPERTY_TYPES:
            skipped_properties.add(f"{property_name} ({property_type})")

        # その他のプロパティ(date, rich_text, select 等)は空のまま作成するためスキップ

    return create_properties, skipped_properties


def print_result_box(lines: list[str]) -> None:
    print("┌─ 実行結果 ───────────────────────────")
    for line in lines:
        print(f"│ {line}")
    print("└──────────────────────────────────────")


def print_key_groups(groups: list[dict[str, Any]], limit: int | None) -> None:
    groups_to_show = groups if limit is None else groups[:limit]
    if not groups_to_show:
        print("今回複製対象になるレコードはありません。")
        return

    for index, group in enumerate(groups_to_show, start=1):
        previous_result_text = group["previous_result_text"] or "(空欄)"
        print(f"[対象{index}] {group['object_name']}")
        print(f"  Keys          : {group['key_name']}")
        print(f"  前回実施結果 : {previous_result_text}")
        if index != len(groups_to_show):
            print("")

    if limit is not None and len(groups) > limit:
        print("")
        print(f"... ほか {len(groups) - limit} 件")


def create_results_for_key_groups(
    client: NotionClient,
    *,
    key_groups: list[dict[str, Any]],
    results_data_source_id: str,
    results_schema_properties: dict[str, Any],
    results_key_property_name: str,
    results_period_property_name: str,
    results_object_property_name: str,
    keys_period_property_name: str,
    keys_object_property_name: str,
    execute: bool,
    limit: int | None,
) -> tuple[int, set[str]]:
    groups_to_process = key_groups if limit is None else key_groups[:limit]
    skipped_properties: set[str] = set()

    if not execute:
        return len(groups_to_process), skipped_properties

    created_count = 0
    for group in groups_to_process:
        create_properties, page_skipped = build_results_create_properties_from_key(
            results_schema_properties=results_schema_properties,
            key_page=group["key_page"],
            key_page_id=group["key_page_id"],
            results_key_property_name=results_key_property_name,
            results_period_property_name=results_period_property_name,
            results_object_property_name=results_object_property_name,
            keys_period_property_name=keys_period_property_name,
            keys_object_property_name=keys_object_property_name,
        )
        skipped_properties.update(page_skipped)
        client.request_json(
            method="POST",
            path="/v1/pages",
            payload={
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": results_data_source_id,
                },
                "properties": create_properties,
            },
        )
        created_count += 1

    return created_count, skipped_properties


def print_warning(message: str) -> None:
    print(f"警告: {message}", file=sys.stderr)


def env_or_default(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Keys テーブルの最新対象期間を参照し、該当 Key ごとに Results テーブルへ空行を作成します。"
            "デフォルトは dry-run で、--execute を付けたときだけ実際に作成します。"
        )
    )
    parser.add_argument("--notion-token", default=env_or_default("NOTION_TOKEN"))
    parser.add_argument(
        "--notion-base-url",
        default=env_or_default("NOTION_BASE_URL", DEFAULT_NOTION_API_BASE_URL),
    )
    # Results データソース (書き込み先)
    parser.add_argument("--page-id", default=env_or_default("NOTION_PAGE_ID"))
    parser.add_argument("--database-id", default=env_or_default("NOTION_DATABASE_ID"))
    parser.add_argument("--data-source-id", default=env_or_default("NOTION_DATA_SOURCE_ID"))
    parser.add_argument("--child-database-title", default=env_or_default("NOTION_CHILD_DATABASE_TITLE"))
    parser.add_argument("--data-source-name", default=env_or_default("NOTION_DATA_SOURCE_NAME"))
    # Keys データソース (期間判定元)
    parser.add_argument(
        "--keys-data-source-id",
        default=env_or_default("NOTION_KEYS_DATA_SOURCE_ID"),
    )
    # Keys テーブル側のプロパティ名
    parser.add_argument(
        "--keys-period-property",
        default=env_or_default("NOTION_KEYS_PERIOD_PROPERTY", "対象期間"),
    )
    parser.add_argument(
        "--keys-object-property",
        default=env_or_default("NOTION_KEYS_OBJECT_PROPERTY", "Object"),
    )
    # Results テーブル側のプロパティ名
    parser.add_argument(
        "--results-key-property",
        default=env_or_default("NOTION_RESULTS_KEY_PROPERTY", "Keys"),
    )
    parser.add_argument(
        "--results-period-property",
        default=env_or_default("NOTION_RESULTS_PERIOD_PROPERTY", "対象期間"),
    )
    parser.add_argument(
        "--results-object-property",
        default=env_or_default("NOTION_RESULTS_OBJECT_PROPERTY", "Objects"),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(env_or_default("NOTION_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--execute", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.notion_token:
        raise NotionAutomationError("NOTION_TOKEN の設定が必要です。")

    if not any([args.page_id, args.database_id, args.data_source_id]):
        raise NotionAutomationError(
            "NOTION_PAGE_ID、NOTION_DATABASE_ID、NOTION_DATA_SOURCE_ID のいずれかを設定してください。"
        )

    if not args.keys_data_source_id:
        raise NotionAutomationError(
            "NOTION_KEYS_DATA_SOURCE_ID の設定が必要です。Keys データソースの ID を指定してください。"
        )

    client = NotionClient(
        token=args.notion_token,
        timeout_seconds=args.timeout_seconds,
        base_url=args.notion_base_url,
    )

    # Results データソース (書き込み先) を解決
    results_data_source_id, results_data_source_name = resolve_data_source_id(
        client,
        data_source_id=args.data_source_id,
        database_id=args.database_id,
        page_id=args.page_id,
        child_database_title=args.child_database_title,
        data_source_name=args.data_source_name,
    )

    # Results スキーマ取得
    results_ds = client.request_json("GET", f"/v1/data_sources/{results_data_source_id}")
    results_schema = results_ds.get("properties", {})
    results_title_property_name = find_title_property_name(results_schema)
    results_created_time_property_name = find_created_time_property_name(results_schema)

    keys_data_source_id = normalize_notion_id(args.keys_data_source_id)
    relation_title_cache: dict[str, str] = {}

    # Keys テーブルを取得して最新期間の Key グループを抽出
    key_pages = client.query_all_pages(keys_data_source_id)
    latest_period, key_groups, warnings = extract_key_groups_for_latest_period(
        client=client,
        key_pages=key_pages,
        keys_period_property_name=args.keys_period_property,
        keys_object_property_name=args.keys_object_property,
        relation_title_cache=relation_title_cache,
    )

    # Results テーブルを取得して前回結果表示 & 本日作成済みチェックに使う
    result_pages = client.query_all_pages(results_data_source_id)

    enrich_key_groups_with_previous_results(
        key_groups=key_groups,
        result_pages=result_pages,
        title_property_name=results_title_property_name,
        created_time_property_name=results_created_time_property_name,
        results_key_property_name=args.results_key_property,
    )

    groups_to_copy, skipped_existing_today, today_local_date = filter_key_groups_already_today(
        key_groups=key_groups,
        result_pages=result_pages,
        title_property_name=results_title_property_name,
        created_time_property_name=results_created_time_property_name,
        results_key_property_name=args.results_key_property,
    )

    mode_label = "本番実行" if args.execute else "ドライラン"
    planned_count = len(groups_to_copy if args.limit is None else groups_to_copy[: args.limit])
    summary_lines = [
        f"モード               : {mode_label}",
        f"データソース         : {results_data_source_name}",
        f"対象期間             : {latest_period}",
        f"対象Keyの件数        : {len(key_groups)}件",
        f"本日作成済みスキップ : {skipped_existing_today}件",
        f"対象期間解釈不可     : {len(warnings)}件",
        f"今回の複製予定       : {planned_count}件",
    ]
    if skipped_existing_today:
        summary_lines.append(f"スキップ対象日       : {today_local_date}")
    print_result_box(summary_lines)
    print("")
    print_key_groups(groups_to_copy, args.limit)
    print("")

    created_count, skipped_properties = create_results_for_key_groups(
        client,
        key_groups=groups_to_copy,
        results_data_source_id=results_data_source_id,
        results_schema_properties=results_schema,
        results_key_property_name=args.results_key_property,
        results_period_property_name=args.results_period_property,
        results_object_property_name=args.results_object_property,
        keys_period_property_name=args.keys_period_property,
        keys_object_property_name=args.keys_object_property,
        execute=args.execute,
        limit=args.limit,
    )

    if skipped_properties:
        for skipped_property in sorted(skipped_properties):
            print_warning(f"複製時にスキップしたプロパティ: {skipped_property}")

    if args.execute:
        print(f"実行完了: Notion に {created_count} 件の複製を作成しました。")
    else:
        print("Notion に実際に複製を作成するには、--execute を付けて再実行してください。")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NotionAutomationError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        raise SystemExit(1)
