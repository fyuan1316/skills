#!/usr/bin/env python3
"""Render the strict post-AC Chinese plugin release email from JSON facts."""

from __future__ import annotations

import argparse
from html import escape
import json
import sys
from pathlib import Path
from typing import Any, TextIO


REQUIRED_STRINGS = (
    "product_name",
    "version",
    "product_positioning",
    "formal_validation_conclusion",
    "release_date",
    "maintenance_end_date",
    "docs_url",
    "baseline",
    "upgrade_path",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input JSON path or - for stdin")
    parser.add_argument("--output", required=True, help="Output Markdown path or - for stdout")
    parser.add_argument(
        "--html-output",
        help="Optional Outlook-compatible HTML output path or - for stdout",
    )
    return parser.parse_args()


def open_input(path: str) -> TextIO:
    if path == "-":
        return sys.stdin
    return Path(path).open(encoding="utf-8")


def require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def require_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{key} must contain only non-empty strings")
    return [item.strip() for item in value]


def render(data: dict[str, Any]) -> str:
    values = {key: require_string(data, key) for key in REQUIRED_STRINGS}
    capabilities = require_list(data, "capabilities")
    acp_versions = require_list(data, "acp_versions")
    architectures = require_list(data, "architectures")
    highlights_heading = data.get("highlights_heading", "本次交付的主要能力包括：")
    if not isinstance(highlights_heading, str) or not highlights_heading.strip():
        raise ValueError("highlights_heading must be a non-empty string when provided")
    errata = data.get("errata", "暂无")
    if not isinstance(errata, str) or not errata.strip():
        raise ValueError("errata must be a non-empty string when provided")

    product_version = f"{values['product_name']} {values['version']}"
    lines = [
        f"标题：{product_version} 版本发布",
        "",
        "大家好！",
        f"{product_version} 已上架到 Alauda Cloud，正式发布。",
        values["product_positioning"],
        highlights_heading.strip(),
        *capabilities,
        values["formal_validation_conclusion"],
        "以下是产品的关键信息供参考：",
        "",
        "| **分类** | **详细说明** |",
        "| --- | --- |",
        f"| **版本名称** | {product_version} |",
        f"| **版本发布时间** | {values['release_date']} |",
        f"| **适配 ACP 版本** | {'、'.join(acp_versions)} |",
        f"| **支持架构** | {'、'.join(architectures)} |",
        f"| **版本维护截止时间** | {values['maintenance_end_date']} |",
        "| **产品安装包** | 国内：[https://cloud.alauda.cn/apps](https://cloud.alauda.cn/apps)<br>国外：[https://cloud.alauda.io/apps](https://cloud.alauda.io/apps) |",
        f"| **产品交付文档** | [{values['docs_url']}]({values['docs_url']}) |",
        f"| **版本基线** | {values['baseline']} |",
        f"| **产品升级路径** | {values['upgrade_path']} |",
        f"| **产品 ERRATA** | {errata.strip()} |",
    ]
    return "\n".join(lines) + "\n"


def render_outlook_html(data: dict[str, Any]) -> str:
    """Render the user-facing Outlook-compatible HTML from the same facts."""
    values = {key: require_string(data, key) for key in REQUIRED_STRINGS}
    capabilities = require_list(data, "capabilities")
    acp_versions = require_list(data, "acp_versions")
    architectures = require_list(data, "architectures")
    highlights_heading = data.get("highlights_heading", "本次交付的主要能力包括：")
    if not isinstance(highlights_heading, str) or not highlights_heading.strip():
        raise ValueError("highlights_heading must be a non-empty string when provided")
    errata = data.get("errata", "暂无")
    if not isinstance(errata, str) or not errata.strip():
        raise ValueError("errata must be a non-empty string when provided")

    product_version = f"{values['product_name']} {values['version']}"
    escaped_product_version = escape(product_version)
    capability_rows = "\n".join(
        f"      <li>{escape(capability)}</li>" for capability in capabilities
    )
    lines = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        f"  <title>{escaped_product_version} 版本发布</title>",
        "</head>",
        '<body style="margin:0; padding:24px; color:#24292f; font-family:Arial, \'Microsoft YaHei\', sans-serif; font-size:14px; line-height:1.6;">',
        '  <div style="max-width:900px; margin:0 auto;">',
        f'    <p style="margin:0 0 16px;"><strong>标题：{escaped_product_version} 版本发布</strong></p>',
        "",
        '    <p style="margin:0 0 12px;">大家好！</p>',
        f'    <p style="margin:0 0 12px;">{escaped_product_version} 已上架到 Alauda Cloud，正式发布。</p>',
        f'    <p style="margin:0 0 12px;">{escape(values["product_positioning"])}</p>',
        f'    <p style="margin:0 0 6px;">{escape(highlights_heading.strip())}</p>',
        '    <ul style="margin:0 0 12px; padding-left:24px;">',
        capability_rows,
        "    </ul>",
        f'    <p style="margin:0 0 12px;">{escape(values["formal_validation_conclusion"])}</p>',
        '    <p style="margin:0 0 12px;">以下是产品的关键信息供参考：</p>',
        "",
        '    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%; border-collapse:collapse; table-layout:fixed;">',
        "      <tr>",
        '        <th style="width:24%; padding:8px 10px; border:1px solid #a8a8a8; background:#f2f2f2; text-align:left; vertical-align:top;">分类</th>',
        '        <th style="width:76%; padding:8px 10px; border:1px solid #a8a8a8; background:#f2f2f2; text-align:left; vertical-align:top;">详细说明</th>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>版本名称</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escaped_product_version}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>版本发布时间</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape(values["release_date"])}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>适配 ACP 版本</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape("、".join(acp_versions))}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>支持架构</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape("、".join(architectures))}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>版本维护截止时间</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape(values["maintenance_end_date"])}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>产品安装包</strong></td>',
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">',
        '          国内：<a href="https://cloud.alauda.cn/apps" style="color:#0969da;">https://cloud.alauda.cn/apps</a><br>',
        '          国外：<a href="https://cloud.alauda.io/apps" style="color:#0969da;">https://cloud.alauda.io/apps</a>',
        "        </td>",
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>产品交付文档</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><a href="{escape(values["docs_url"], quote=True)}" style="color:#0969da;">{escape(values["docs_url"])}</a></td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>版本基线</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape(values["baseline"])}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>产品升级路径</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape(values["upgrade_path"])}</td>',
        "      </tr>",
        "      <tr>",
        '        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;"><strong>产品 ERRATA</strong></td>',
        f'        <td style="padding:8px 10px; border:1px solid #a8a8a8; vertical-align:top;">{escape(errata.strip())}</td>',
        "      </tr>",
        "    </table>",
        "  </div>",
        "</body>",
        "</html>",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    try:
        with open_input(args.input) as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("input JSON must be an object")
        output = render(data)
        html_output = render_outlook_html(data) if args.html_output else None
        if args.output == "-" and args.html_output == "-":
            raise ValueError("--output and --html-output cannot both use stdout")
        if args.output == "-":
            sys.stdout.write(output)
        else:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
        if args.html_output:
            if args.html_output == "-":
                sys.stdout.write(html_output or "")
            else:
                html_output_path = Path(args.html_output)
                html_output_path.parent.mkdir(parents=True, exist_ok=True)
                html_output_path.write_text(html_output or "", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
