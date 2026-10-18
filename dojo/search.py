"""DeepSeek Search API adapter for externally sourced discussion material."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

SEARCH_ENDPOINT = "https://api.deepseek.com/v1/tools/search"
REQUEST_TIMEOUT_SECONDS = 20
DEFAULT_COUNT = 8


class SearchError(Exception):
    """A classified search failure with a Chinese message safe to show the model."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.user_message = message


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _bad_response() -> SearchError:
    return SearchError("bad_response", "搜索服务返回了无法识别的响应；请说明暂时无法核实外部信息。")


def _normalize_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise _bad_response()
    normalized = []
    for result in value["results"]:
        if not isinstance(result, dict):
            raise _bad_response()
        title, url = result.get("title"), result.get("url")
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str) or not url.strip():
            raise _bad_response()
        item: dict[str, Any] = {"title": title, "url": url}
        for field in ("snippet", "summary", "content"):
            text = result.get(field, "")
            if not isinstance(text, str):
                raise _bad_response()
            item[field] = text
        score = result.get("rerank_score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
            raise _bad_response()
        item["rerank_score"] = score
        normalized.append(item)
    return normalized


def search(
    query: str,
    count: int = DEFAULT_COUNT,
    need_content: bool = False,
    *,
    environ: Mapping[str, str] | None = None,
    opener: Any | None = None,
) -> list[dict[str, Any]]:
    """Search without rewriting the query; the opener is injectable for tests."""
    if not isinstance(query, str) or not 1 <= len(query) <= 128 or not query.strip():
        raise SearchError("bad_response", "搜索词必须为 1 至 128 个字符，且不能全为空白。")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
        raise SearchError("bad_response", "搜索结果数量必须是 1 至 50 的整数。")
    if not isinstance(need_content, bool):
        raise SearchError("bad_response", "搜索正文选项必须是布尔值。")
    values = os.environ if environ is None else environ
    api_key = values.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SearchError("no_key", "搜索不可用：未配置 DEEPSEEK_API_KEY。")
    payload = json.dumps(
        {"query": query, "count": count, "need_content": need_content},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        SEARCH_ENDPOINT,
        data=payload,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    active_opener = opener if opener is not None else urllib.request.build_opener(_RejectRedirects())
    try:
        with active_opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise SearchError(f"http_{status}", f"搜索服务返回 HTTP {status}；暂时无法核实外部信息。") from None
    except (TimeoutError, socket.timeout):
        raise SearchError("timeout", "搜索请求超时；暂时无法核实外部信息。") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise SearchError("timeout", "搜索请求超时；暂时无法核实外部信息。") from None
        raise SearchError("connect", "无法连接搜索服务；暂时无法核实外部信息。") from None
    except OSError:
        raise SearchError("connect", "无法连接搜索服务；暂时无法核实外部信息。") from None
    except Exception:
        raise SearchError("connect", "无法连接搜索服务；暂时无法核实外部信息。") from None
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _bad_response() from None
    return _normalize_results(decoded)
