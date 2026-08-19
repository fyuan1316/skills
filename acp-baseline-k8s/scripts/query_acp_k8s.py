#!/usr/bin/env python3
"""Query ACP baseline Confluence pages for supported Kubernetes versions."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://confluence.alauda.cn"
DEFAULT_ROOT_PAGE_ID = "75075758"
DEFAULT_ENV_FILE = Path("/Volumes/macOS-2/Users/yuan/Dev/tools/envs/env.confluence")


VERSION_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")
K8S_RE = re.compile(r"\b\d+\.\d+(?:\.\d+(?:-\d+)?)?(?:\.x)?\b")


@dataclass
class Page:
    id: str
    title: str
    url: str
    updated_at: str = ""


class TableParser(HTMLParser):
    """Small Confluence storage table parser using only stdlib."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._table: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []
        elif self._in_cell and tag in {"br", "p", "div", "li"}:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._in_cell and tag in {"td", "th"}:
            value = " ".join(self._cell)
            value = html.unescape(re.sub(r"\s+", " ", value)).strip()
            self._row.append(value)
            self._in_cell = False
            self._cell = []
        elif self._in_row and tag == "tr":
            if self._row:
                self._table.append(self._row)
            self._in_row = False
        elif self._in_table and tag == "table":
            self.tables.append(self._table)
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


class TextParser(HTMLParser):
    """Extract readable text from Confluence storage HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        value = html.unescape(" ".join(self.parts))
        return re.sub(r"\s+", " ", value).strip()


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def get_credentials(env_file: Path) -> tuple[str, str]:
    file_env = load_env_file(env_file)
    user = (
        os.environ.get("CONFLUENCE_USER")
        or os.environ.get("ALAUDA_CONFLUENCE_USER")
        or file_env.get("USER")
        or os.environ.get("USER")
    )
    password = (
        os.environ.get("CONFLUENCE_PASSWORD")
        or os.environ.get("ALAUDA_CONFLUENCE_PASSWORD")
        or file_env.get("PASSWORD")
        or os.environ.get("PASSWORD")
    )
    if not user or not password:
        raise SystemExit(
            "Missing Confluence credentials. Source env.confluence or keep "
            f"USER/PASSWORD in {env_file}."
        )
    return user, password


class ConfluenceClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        verify_tls: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "acp-baseline-k8s/1.0",
        }
        self.context = None if verify_tls else ssl._create_unverified_context()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise SystemExit(f"Confluence HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"Confluence request failed: {exc}") from exc

    def list_child_pages(self, page_id: str) -> list[Page]:
        pages: list[Page] = []
        start = 0
        limit = 100
        while True:
            data = self.get_json(
                f"/rest/api/content/{page_id}/child/page",
                {"limit": limit, "start": start, "expand": "version"},
            )
            for item in data.get("results", []):
                links = item.get("_links", {})
                pages.append(
                    Page(
                        id=str(item["id"]),
                        title=item.get("title", ""),
                        url=f"{self.base_url}{links.get('webui', '')}",
                        updated_at=item.get("version", {}).get("when", ""),
                    )
                )
            if not data.get("_links", {}).get("next"):
                break
            start += limit
        return pages

    def get_page_storage(self, page_id: str) -> tuple[Page, str]:
        data = self.get_json(
            f"/rest/api/content/{page_id}",
            {"expand": "body.storage,version"},
        )
        links = data.get("_links", {})
        page = Page(
            id=str(data["id"]),
            title=data.get("title", ""),
            url=f"{self.base_url}{links.get('webui', '')}",
            updated_at=data.get("version", {}).get("when", ""),
        )
        return page, data.get("body", {}).get("storage", {}).get("value", "")


def normalize_major_minor(value: str) -> tuple[int, int]:
    match = VERSION_RE.search(value)
    if not match or match.group(3) is not None:
        raise SystemExit("Version must be major.minor, for example 4.4")
    return int(match.group(1)), int(match.group(2))


def parse_patch_version(title: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.search(title)
    if not match or match.group(3) is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_patch_baseline_page(title: str) -> bool:
    return bool(re.fullmatch(r"\s*v?\d+\.\d+\.\d+\s+版本基线\s*", title))


def find_major_page(pages: list[Page], major: int, minor: int) -> Page:
    expected = re.compile(rf"\bv?{major}\.{minor}\.x\b.*版本基线")
    matches = [page for page in pages if expected.search(page.title)]
    if not matches:
        available = ", ".join(page.title for page in pages[:20])
        raise SystemExit(
            f"Cannot find v{major}.{minor}.x baseline page under root. "
            f"Available examples: {available}"
        )
    return matches[0]


def select_patch_page(
    pages: list[Page],
    major: int,
    minor: int,
    patch: str | None,
) -> Page:
    candidates: list[tuple[tuple[int, int, int], Page]] = []
    for page in pages:
        version = parse_patch_version(page.title)
        if (
            version
            and version[0] == major
            and version[1] == minor
            and is_patch_baseline_page(page.title)
        ):
            candidates.append((version, page))
    if not candidates:
        raise SystemExit(f"Cannot find patch baseline pages for v{major}.{minor}.x")

    if patch:
        wanted = parse_patch_version(patch)
        if not wanted:
            raise SystemExit("--patch must be a major.minor.patch version, for example 4.4.0")
        for version, page in candidates:
            if version == wanted:
                return page
        available = ", ".join(f"v{'.'.join(map(str, v))}" for v, _ in candidates)
        raise SystemExit(f"Cannot find requested patch {patch}. Available: {available}")

    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def extract_versions(text: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for match in K8S_RE.finditer(text):
        value = match.group(0)
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def classify_table(header: list[str]) -> str:
    normalized = [cell.lower().replace(" ", "") for cell in header]
    joined = "|".join(normalized)
    if not any("kubernetes" in cell or "k8s" in cell for cell in normalized):
        return ""
    if any("集群来源" in cell for cell in header):
        return "matrix"
    if "istio" in joined:
        return "attached"
    if any("运行时组件" in cell for cell in header):
        return "platform"
    return "matrix"


def k8s_column_indices(header: list[str]) -> list[int]:
    indices: list[int] = []
    for index, cell in enumerate(header):
        normalized = cell.lower().replace(" ", "")
        if "来源" in cell:
            continue
        if normalized in {"kubernetes", "k8s"}:
            indices.append(index)
        elif ("kubernetes" in normalized or "k8s" in normalized) and "版本" in cell:
            indices.append(index)
    return indices


def parse_k8s_tables(storage_html: str) -> list[dict[str, Any]]:
    parser = TableParser()
    parser.feed(storage_html)

    results: list[dict[str, Any]] = []
    for index, table in enumerate(parser.tables, 1):
        if not table:
            continue
        header = table[0]
        category = classify_table(header)
        if not category:
            continue
        k8s_columns = k8s_column_indices(header)
        if not k8s_columns:
            continue

        versions: list[str] = []
        rows: list[list[str]] = []
        for row in table[1:]:
            row_text = " ".join(
                row[index] for index in k8s_columns if index < len(row)
            )
            row_versions = extract_versions(row_text)
            if row_versions:
                rows.append(row)
            for value in row_versions:
                if value not in versions:
                    versions.append(value)

        if versions:
            results.append(
                {
                    "category": category,
                    "table_index": index,
                    "header": header,
                    "versions": versions,
                    "rows": rows,
                }
            )
    return results


def extract_text(storage_html: str) -> str:
    parser = TextParser()
    parser.feed(storage_html)
    return parser.text()


def snippet(text: str, start: int, end: int, width: int = 44) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    value = text[left:right]
    if left:
        value = "..." + value
    if right < len(text):
        value += "..."
    return value


def audit_release_consistency(
    storage_html: str,
    expected_version: tuple[int, int, int] | None,
) -> dict[str, Any]:
    if not expected_version:
        return {"status": "unknown", "warnings": [], "version_refs": []}

    expected_mm = expected_version[:2]
    text = extract_text(storage_html)
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    patterns = [
        # Product version mentions in prose: ACP 4.4 / ACP v4.4.0 / ACP 4.4.x
        re.compile(r"\bACP\s+v?(\d+)\.(\d+)(?:\.(\d+)|\.x)?\b", re.IGNORECASE),
        # Baseline or artifact refs with an explicit v prefix: v4.4.x / v4.4.0
        re.compile(r"\bv(\d+)\.(\d+)(?:\.(\d+)|\.x)\b", re.IGNORECASE),
        # Baseline title-like references without v: 4.4.x 版本基线
        re.compile(r"\b(\d+)\.(\d+)(?:\.(\d+)|\.x)?\s+版本基线\b"),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            key = (match.group(0), match.start())
            if key in seen:
                continue
            seen.add(key)
            major = int(match.group(1))
            minor = int(match.group(2))
            ref_snippet = snippet(text, match.start(), match.end(), width=80)
            strong = is_strong_product_version_context(ref_snippet)
            ref = {
                "text": match.group(0),
                "major_minor": f"{major}.{minor}",
                "matches_title_major_minor": (major, minor) == expected_mm,
                "strong_product_version_context": strong,
                "snippet": ref_snippet,
            }
            refs.append(ref)

    mismatches = [
        ref for ref in refs
        if not ref["matches_title_major_minor"]
        and ref.get("strong_product_version_context")
    ]
    warnings: list[str] = []
    status = "consistent"
    if mismatches:
        status = "suspect_unreleased"
        mismatch_values = sorted({ref["major_minor"] for ref in mismatches})
        expected = f"{expected_mm[0]}.{expected_mm[1]}"
        warnings.append(
            "未发版提示：页面标题版本与产品版本/基线标题/制品链接中的 ACP 版本线索不一致；"
            f"标题是 {expected}，但关键内容还出现 {', '.join(mismatch_values)}。"
            "这通常表示人工复制的基线页尚未完成发版维护，请打开 Confluence 原文确认。"
        )

    return {"status": status, "warnings": warnings, "version_refs": refs}


def is_strong_product_version_context(value: str) -> bool:
    """Return True when a product version ref looks like page identity, not upgrade history."""
    weak_context = [
        "直升",
        "升级",
        "低版本",
        "从 ACP",
        "从 v",
        "停留在",
        "支持周期",
        "晚于",
    ]
    if any(token in value for token in weak_context):
        return False

    strong_context = [
        "产品版本",
        "产品版本信息",
        "版本基线",
        "基线页",
        "基线文档",
        "发版原因",
        "发版时间",
        "代码冻结",
        "测试时间",
        "发布时间",
        "artifacts.yaml",
        "/blob/v",
        "version",
    ]
    return any(token in value for token in strong_context)


def summarize(results: list[dict[str, Any]]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {"platform": [], "attached": [], "matrix": []}
    for item in results:
        bucket = summary.setdefault(item["category"], [])
        for version in item["versions"]:
            if version not in bucket:
                bucket.append(version)
    return summary


def print_human(payload: dict[str, Any]) -> None:
    page = payload["page"]
    summary = payload["summary"]
    audit = payload.get("release_audit", {})
    print(f"ACP baseline: {payload['resolved_version']}")
    print(f"Source page:  {page['title']}")
    print(f"Updated at:   {page.get('updated_at') or 'unknown'}")
    print(f"URL:          {page['url']}")
    if audit.get("status") == "suspect_unreleased":
        print("Release note: 未发版 / 疑似复制残留，需人工确认")
        for warning in audit.get("warnings", []):
            print(f"Warning:      {warning}")
    print()

    labels = {
        "platform": "Platform/global Kubernetes",
        "attached": "Business/attached cluster Kubernetes",
        "matrix": "Additional support matrix",
    }
    for key in ["platform", "attached", "matrix"]:
        versions = summary.get(key) or []
        if versions:
            print(f"{labels[key]}: {', '.join(versions)}")

    if not any(summary.values()):
        print("No Kubernetes version tables were recognized on this page.")
        return

    print()
    print("Evidence tables:")
    for item in payload["tables"]:
        print(
            f"- table {item['table_index']} [{item['category']}]: "
            f"{' | '.join(item['header'])} -> {', '.join(item['versions'])}"
        )
    if audit.get("status") == "suspect_unreleased":
        mismatches = [
            ref for ref in audit.get("version_refs", [])
            if not ref.get("matches_title_major_minor")
            and ref.get("strong_product_version_context")
        ]
        if mismatches:
            print()
            print("Suspicious ACP version refs:")
            for ref in mismatches[:5]:
                print(f"- {ref['text']}: {ref['snippet']}")


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    major, minor = normalize_major_minor(args.version)
    user, password = get_credentials(Path(args.env_file))
    client = ConfluenceClient(args.base_url, user, password, verify_tls=args.verify_tls)

    root_children = client.list_child_pages(args.root_page_id)
    major_page = find_major_page(root_children, major, minor)
    patch_children = client.list_child_pages(major_page.id)
    patch_page = select_patch_page(patch_children, major, minor, args.patch)
    page, storage = client.get_page_storage(patch_page.id)
    tables = parse_k8s_tables(storage)
    summary = summarize(tables)
    resolved = parse_patch_version(page.title)
    release_audit = audit_release_consistency(storage, resolved)

    return {
        "requested_version": f"{major}.{minor}",
        "resolved_version": "v" + ".".join(map(str, resolved)) if resolved else page.title,
        "major_page": major_page.__dict__,
        "page": page.__dict__,
        "summary": summary,
        "tables": tables,
        "release_audit": release_audit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="ACP major.minor version, for example 4.4")
    parser.add_argument("--patch", help="Specific ACP patch version, for example 4.4.0")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--root-page-id", default=DEFAULT_ROOT_PAGE_ID)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--verify-tls", action="store_true", help="Verify Confluence TLS")
    args = parser.parse_args()

    payload = build_payload(args)
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(payload)


if __name__ == "__main__":
    main()
