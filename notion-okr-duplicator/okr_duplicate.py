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
                "in_trash": False,
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


def normalize_group_component(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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


def build_duplicate_group_key(
    *,
    page: dict[str, Any],
    client: NotionClient,
    period_property_name: str,
    object_property_name: str,
    key_property_name: str,
    relation_title_cache: dict[str, str],
) -> tuple[str, str, str]:
    properties = page.get("properties", {})
    return tuple(
        normalize_group_component(
            property_to_plain_text(
                properties.get(property_name, {}),
                client=client,
                relation_title_cache=relation_title_cache,
            )
        )
        for property_name in (period_property_name, object_property_name, key_property_name)
    )


def deduplicate_selected_pages(
    *,
    client: NotionClient,
    pages: list[dict[str, Any]],
    period_property_name: str,
    object_property_name: str,
    key_property_name: str,
    created_time_property_name: str | None,
    title_property_name: str | None,
    relation_title_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    group_states: dict[tuple[str, str, str], dict[str, Any]] = {}

    for index, page in enumerate(pages):
        group_key = build_duplicate_group_key(
            page=page,
            client=client,
            period_property_name=period_property_name,
            object_property_name=object_property_name,
            key_property_name=key_property_name,
            relation_title_cache=relation_title_cache,
        )

        current_created_time = get_page_created_timestamp(page, created_time_property_name)
        current_result_text = get_result_text(page, title_property_name)
        state = group_states.get(group_key)
        if state is None:
            group_states[group_key] = {
                "latest_page": page,
                "latest_created_time": current_created_time,
                "oldest_created_time": current_created_time,
                "oldest_index": index,
                "group_key": group_key,
                "previous_result_text": current_result_text,
                "previous_result_created_time": current_created_time if current_result_text else "",
            }
            continue

        if current_created_time > state["latest_created_time"]:
            state["latest_page"] = page
            state["latest_created_time"] = current_created_time

        if current_created_time < state["oldest_created_time"]:
            state["oldest_created_time"] = current_created_time
            state["oldest_index"] = index

        if current_result_text:
            previous_result_created_time = state["previous_result_created_time"]
            if not previous_result_created_time or current_created_time > previous_result_created_time:
                state["previous_result_text"] = current_result_text
                state["previous_result_created_time"] = current_created_time

    ordered_states = sorted(
        group_states.values(),
        key=lambda state: (state["oldest_created_time"], state["oldest_index"]),
    )
    dropped_duplicates = len(pages) - len(ordered_states)
    return ordered_states, dropped_duplicates


def filter_already_copied_today(
    *,
    client: NotionClient,
    candidate_groups: list[dict[str, Any]],
    all_pages: list[dict[str, Any]],
    period_property_name: str,
    object_property_name: str,
    key_property_name: str,
    created_time_property_name: str | None,
    title_property_name: str | None,
    relation_title_cache: dict[str, str],
) -> tuple[list[dict[str, Any]], int, str]:
    today_local_date = datetime.now().astimezone().date().isoformat()
    groups_with_copy_today: set[tuple[str, str, str]] = set()

    for page in all_pages:
        if not is_blank_result_page(page, title_property_name):
            continue

        created_timestamp = get_page_created_timestamp(page, created_time_property_name)
        created_local_date = get_local_date_string_from_timestamp(created_timestamp)
        if created_local_date != today_local_date:
            continue

        groups_with_copy_today.add(
            build_duplicate_group_key(
                page=page,
                client=client,
                period_property_name=period_property_name,
                object_property_name=object_property_name,
                key_property_name=key_property_name,
                relation_title_cache=relation_title_cache,
            )
        )

    filtered_groups: list[dict[str, Any]] = []
    skipped_count = 0
    for group in candidate_groups:
        group_key = group["group_key"]
        if group_key in groups_with_copy_today:
            skipped_count += 1
            continue
        filtered_groups.append(group)

    return filtered_groups, skipped_count, today_local_date


def describe_page(
    page: dict[str, Any],
    title_property_name: str | None,
    object_property_name: str,
    key_property_name: str,
    client: NotionClient | None = None,
    relation_title_cache: dict[str, str] | None = None,
) -> str:
    page_properties = page.get("properties", {})
    title = page.get("id", "")

    if title_property_name and title_property_name in page_properties:
        maybe_title = property_to_plain_text(
            page_properties[title_property_name],
            client=client,
            relation_title_cache=relation_title_cache,
        ).strip()
        if maybe_title:
            title = maybe_title

    details: list[str] = []
    for label, property_name in (("Objects", object_property_name), ("Keys", key_property_name)):
        if property_name in page_properties:
            plain_text = property_to_plain_text(
                page_properties[property_name],
                client=client,
                relation_title_cache=relation_title_cache,
            ).strip()
            if plain_text:
                details.append(f"{label}={plain_text}")

    if not details:
        return title
    return f"{title} ({', '.join(details)})"


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


def build_create_properties(
    schema_properties: dict[str, Any],
    page_properties: dict[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    create_properties: dict[str, Any] = {}
    skipped_properties: set[str] = set()

    for property_name, definition in schema_properties.items():
        property_type = definition.get("type")
        source_property = page_properties.get(property_name, {})

        if property_type == "title":
            create_properties[property_name] = {"title": []}
            continue

        if property_type == "rich_text":
            rich_text = source_property.get("rich_text", [])
            if rich_text:
                create_properties[property_name] = {"rich_text": rich_text}
            continue

        if property_type == "number":
            number = source_property.get("number")
            if number is not None:
                create_properties[property_name] = {"number": number}
            continue

        if property_type == "select":
            selected = source_property.get("select")
            if selected:
                create_properties[property_name] = {"select": {"name": selected["name"]}}
            continue

        if property_type == "status":
            status = source_property.get("status")
            if status:
                create_properties[property_name] = {"status": {"name": status["name"]}}
            continue

        if property_type == "multi_select":
            multi_select = source_property.get("multi_select", [])
            if multi_select:
                create_properties[property_name] = {
                    "multi_select": [{"name": option["name"]} for option in multi_select]
                }
            continue

        if property_type == "date":
            date_value = source_property.get("date")
            if date_value:
                create_properties[property_name] = {"date": date_value}
            continue

        if property_type == "checkbox":
            create_properties[property_name] = {"checkbox": bool(source_property.get("checkbox"))}
            continue

        if property_type == "url":
            url = source_property.get("url")
            if url:
                create_properties[property_name] = {"url": url}
            continue

        if property_type == "email":
            email_value = source_property.get("email")
            if email_value:
                create_properties[property_name] = {"email": email_value}
            continue

        if property_type == "phone_number":
            phone_number = source_property.get("phone_number")
            if phone_number:
                create_properties[property_name] = {"phone_number": phone_number}
            continue

        if property_type == "people":
            people = source_property.get("people", [])
            if people:
                create_properties[property_name] = {"people": [{"id": person["id"]} for person in people]}
            continue

        if property_type == "relation":
            relations = source_property.get("relation", [])
            if relations:
                create_properties[property_name] = {"relation": [{"id": relation["id"]} for relation in relations]}
            if source_property.get("has_more"):
                skipped_properties.add(f"{property_name} (relation values were truncated by Notion)")
            continue

        if property_type == "files":
            files = []
            skipped_internal_upload = False
            for file_object in source_property.get("files", []):
                if file_object.get("type") == "external" and file_object.get("external", {}).get("url"):
                    files.append(
                        {
                            "name": file_object.get("name", "External file"),
                            "type": "external",
                            "external": {"url": file_object["external"]["url"]},
                        }
                    )
                elif file_object.get("type") == "file":
                    skipped_internal_upload = True

            if files:
                create_properties[property_name] = {"files": files}
            if skipped_internal_upload:
                skipped_properties.add(f"{property_name} (Notion-hosted file uploads were skipped)")
            continue

        if property_type in READ_ONLY_PROPERTY_TYPES:
            skipped_properties.add(f"{property_name} ({property_type})")
            continue

        skipped_properties.add(f"{property_name} ({property_type or 'unknown'})")

    return create_properties, skipped_properties


def select_source_pages(
    *,
    client: NotionClient,
    pages: list[dict[str, Any]],
    period_property_name: str,
    title_property_name: str | None,
    object_property_name: str,
    key_property_name: str,
    relation_title_cache: dict[str, str],
) -> tuple[YearMonth, list[dict[str, Any]], list[str]]:
    latest_period: YearMonth | None = None
    candidates: list[tuple[YearMonth, dict[str, Any]]] = []
    warnings: list[str] = []

    for page in pages:
        properties = page.get("properties", {})
        period_property = properties.get(period_property_name)
        if period_property is None:
            raise NotionAutomationError(
                f"ページ {page.get('id')} にプロパティ '{period_property_name}' が見つかりませんでした。"
            )

        raw_period = property_to_plain_text(
            period_property,
            client=client,
            relation_title_cache=relation_title_cache,
        )
        parsed_period = parse_year_month(raw_period)
        if not parsed_period:
            warnings.append(
                f"ページ '{describe_page(page, title_property_name, object_property_name, key_property_name, client, relation_title_cache)}' は "
                f"'{period_property_name}' を年月として解釈できないためスキップしました: {raw_period or '(空)'}"
            )
            continue

        candidates.append((parsed_period, page))
        if latest_period is None or parsed_period > latest_period:
            latest_period = parsed_period

    if latest_period is None:
        raise NotionAutomationError(
            f"'{period_property_name}' を年月として解釈できる行が見つかりませんでした。"
        )

    selected_pages = [page for period, page in candidates if period == latest_period]
    return latest_period, selected_pages, warnings


def print_warning(message: str) -> None:
    print(f"警告: {message}", file=sys.stderr)


def duplicate_pages(
    client: NotionClient,
    *,
    data_source_id: str,
    data_source_name: str,
    schema_properties: dict[str, Any],
    selected_groups: list[dict[str, Any]],
    execute: bool,
    limit: int | None,
) -> tuple[int, set[str]]:
    groups_to_duplicate = selected_groups if limit is None else selected_groups[:limit]
    skipped_properties: set[str] = set()

    if not execute:
        return len(groups_to_duplicate), skipped_properties

    created_count = 0
    for group in groups_to_duplicate:
        page = group["latest_page"]
        create_properties, page_skipped_properties = build_create_properties(
            schema_properties=schema_properties,
            page_properties=page.get("properties", {}),
        )
        skipped_properties.update(page_skipped_properties)
        client.request_json(
            method="POST",
            path="/v1/pages",
            payload={
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": data_source_id,
                },
                "properties": create_properties,
            },
        )
        created_count += 1

    return created_count, skipped_properties


def print_result_box(lines: list[str]) -> None:
    print("┌─ 実行結果 ───────────────────────────")
    for line in lines:
        print(f"│ {line}")
    print("└──────────────────────────────────────")


def print_target_groups(groups: list[dict[str, Any]], limit: int | None) -> None:
    groups_to_show = groups if limit is None else groups[:limit]
    if not groups_to_show:
        print("今回複製対象になるレコードはありません。")
        return

    for index, group in enumerate(groups_to_show, start=1):
        _, object_name, key_name = group["group_key"]
        previous_result_text = group["previous_result_text"] or "(空欄)"
        print(f"[対象{index}] {object_name}")
        print(f"  Keys          : {key_name}")
        print(f"  前回実施結果 : {previous_result_text}")
        if index != len(groups_to_show):
            print("")

    if limit is not None and len(groups) > limit:
        print("")
        print(f"... ほか {len(groups) - limit} 件")


def env_or_default(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Notion のデータソースで、最新の 対象期間 にある行を複製します。"
            "デフォルトは dry-run で、--execute を付けたときだけ実際に複製を作成します。"
        )
    )
    parser.add_argument("--notion-token", default=env_or_default("NOTION_TOKEN"))
    parser.add_argument(
        "--notion-base-url",
        default=env_or_default("NOTION_BASE_URL", DEFAULT_NOTION_API_BASE_URL),
    )
    parser.add_argument("--page-id", default=env_or_default("NOTION_PAGE_ID"))
    parser.add_argument("--database-id", default=env_or_default("NOTION_DATABASE_ID"))
    parser.add_argument("--data-source-id", default=env_or_default("NOTION_DATA_SOURCE_ID"))
    parser.add_argument("--child-database-title", default=env_or_default("NOTION_CHILD_DATABASE_TITLE"))
    parser.add_argument("--data-source-name", default=env_or_default("NOTION_DATA_SOURCE_NAME"))
    parser.add_argument("--period-property", default=env_or_default("NOTION_PERIOD_PROPERTY", "対象期間"))
    parser.add_argument("--object-property", default=env_or_default("NOTION_OBJECT_PROPERTY", "Objects"))
    parser.add_argument("--key-property", default=env_or_default("NOTION_KEY_PROPERTY", "Keys"))
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

    client = NotionClient(
        token=args.notion_token,
        timeout_seconds=args.timeout_seconds,
        base_url=args.notion_base_url,
    )
    data_source_id, data_source_name = resolve_data_source_id(
        client,
        data_source_id=args.data_source_id,
        database_id=args.database_id,
        page_id=args.page_id,
        child_database_title=args.child_database_title,
        data_source_name=args.data_source_name,
    )

    data_source = client.request_json("GET", f"/v1/data_sources/{data_source_id}")
    schema_properties = data_source.get("properties", {})
    title_property_name = find_title_property_name(schema_properties)
    created_time_property_name = find_created_time_property_name(schema_properties)
    relation_title_cache: dict[str, str] = {}
    if args.period_property not in schema_properties:
        raise NotionAutomationError(
            f"データソース '{data_source_name}' にプロパティ '{args.period_property}' が存在しません。"
        )

    pages = client.query_all_pages(data_source_id)
    latest_period, selected_pages, warnings = select_source_pages(
        client=client,
        pages=pages,
        period_property_name=args.period_property,
        title_property_name=title_property_name,
        object_property_name=args.object_property,
        key_property_name=args.key_property,
        relation_title_cache=relation_title_cache,
    )

    deduplicated_groups, dropped_duplicates = deduplicate_selected_pages(
        client=client,
        pages=selected_pages,
        period_property_name=args.period_property,
        object_property_name=args.object_property,
        key_property_name=args.key_property,
        created_time_property_name=created_time_property_name,
        title_property_name=title_property_name,
        relation_title_cache=relation_title_cache,
    )
    groups_to_copy, skipped_existing_today, today_local_date = filter_already_copied_today(
        client=client,
        candidate_groups=deduplicated_groups,
        all_pages=pages,
        period_property_name=args.period_property,
        object_property_name=args.object_property,
        key_property_name=args.key_property,
        created_time_property_name=created_time_property_name,
        title_property_name=title_property_name,
        relation_title_cache=relation_title_cache,
    )

    mode_label = "本番実行" if args.execute else "ドライラン"
    planned_count = len(groups_to_copy if args.limit is None else groups_to_copy[: args.limit])
    summary_lines = [
        f"モード               : {mode_label}",
        f"データソース         : {data_source_name}",
        f"対象期間             : {latest_period}",
        f"最新期間の元行数     : {len(selected_pages)}件",
        f"重複解消後の対象     : {len(deduplicated_groups)}件",
        f"本日作成済みスキップ : {skipped_existing_today}件",
        f"対象期間解釈不可     : {len(warnings)}件",
        f"今回の複製予定       : {planned_count}件",
    ]
    if dropped_duplicates:
        summary_lines.append(f"重複除外             : {dropped_duplicates}件")
    if skipped_existing_today:
        summary_lines.append(f"スキップ対象日       : {today_local_date}")
    print_result_box(summary_lines)
    print("")
    print_target_groups(groups_to_copy, args.limit)
    print("")

    created_count, skipped_properties = duplicate_pages(
        client,
        data_source_id=data_source_id,
        data_source_name=data_source_name,
        schema_properties=schema_properties,
        selected_groups=groups_to_copy,
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
