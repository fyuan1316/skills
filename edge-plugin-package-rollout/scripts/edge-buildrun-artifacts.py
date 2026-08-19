#!/usr/bin/env python3
"""Find package/bundle/image artifact clues in an Alauda Edge BuildRun."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


signal.signal(signal.SIGPIPE, signal.SIG_DFL)

DEFAULT_BASE_URL = "https://edge.alauda.cn"
DEFAULT_CLUSTER = "business-build"
DEFAULT_NAMESPACE = "aml-dev"
DEFAULT_ENV_FILE = Path("/Volumes/macOS-2/Users/yuan/Dev/tools/envs/env.edge")
DEFAULT_PATTERN = (
    r"s3|tgz|tar\.gz|package|bundle|chart|artifact|image|digest|"
    r"build-harbor|harbor|\.alauda\.cn|v\d+\.\d+\.\d+"
)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def get_token(env_file: Path) -> str:
    file_env = load_env(env_file)
    token = (
        os.environ.get("EDGE_PIPELINE_TOKEN")
        or os.environ.get("EDGE_TOKEN")
        or os.environ.get("TOKEN")
        or file_env.get("EDGE_PIPELINE_TOKEN")
        or file_env.get("EDGE_TOKEN")
        or file_env.get("TOKEN")
    )
    if not token:
        raise SystemExit(f"Missing Edge token. Expected TOKEN in {env_file}.")
    return token


class Client:
    def __init__(self, base_url: str, token: str, verify_tls: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.context = None if verify_tls else ssl._create_unverified_context()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "edge-buildrun-artifacts/1.0",
        }

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=40) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise SystemExit(f"HTTP {exc.code}: {detail}") from exc


def walk_scalars(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            found.extend(walk_scalars(value, child))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(walk_scalars(value, f"{prefix}.{index}"))
    elif obj is not None:
        found.append((prefix, str(obj)))
    return found


def add_matches(
    out: list[dict[str, str]],
    source: str,
    obj: Any,
    pattern: re.Pattern[str],
) -> None:
    seen = {(item["source"], item["path"], item["value"]) for item in out}
    for path, value in walk_scalars(obj):
        if pattern.search(path) or pattern.search(value):
            key = (source, path, value)
            if key not in seen:
                out.append({"source": source, "path": path, "value": value})
                seen.add(key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buildrun", required=True)
    parser.add_argument("--cluster", default=DEFAULT_CLUSTER)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--pattern", default=DEFAULT_PATTERN)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verify-tls", action="store_true")
    args = parser.parse_args()

    token = get_token(Path(args.env_file))
    client = Client(args.base_url, token, verify_tls=args.verify_tls)
    pattern = re.compile(args.pattern, re.IGNORECASE)

    results: list[dict[str, str]] = []
    paths = {
        "buildrun": (
            f"/kubernetes/{args.cluster}/apis/builds.katanomi.dev/v1alpha1/"
            f"namespaces/{args.namespace}/buildruns/{args.buildrun}"
        ),
        "pipelinerun": (
            f"/kubernetes/{args.cluster}/apis/tekton.dev/v1/"
            f"namespaces/{args.namespace}/pipelineruns/{args.buildrun}"
        ),
        "taskruns": (
            f"/kubernetes/{args.cluster}/apis/tekton.dev/v1/"
            f"namespaces/{args.namespace}/taskruns"
        ),
    }

    for source in ["buildrun", "pipelinerun"]:
        try:
            add_matches(results, source, client.get_json(paths[source]), pattern)
        except SystemExit as exc:
            results.append({"source": source, "path": "error", "value": str(exc)})

    try:
        taskruns = client.get_json(
            paths["taskruns"],
            {"labelSelector": f"tekton.dev/pipelineRun={args.buildrun}"},
        )
        add_matches(results, "taskruns", taskruns, pattern)
    except SystemExit as exc:
        results.append({"source": "taskruns", "path": "error", "value": str(exc)})

    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    for item in results:
        print(f"{item['source']}\t{item['path']}\t{item['value']}")


if __name__ == "__main__":
    main()
