#!/usr/bin/env python3
"""Collect a deterministic Git release delta for E2E impact analysis."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


CLASSIFIERS = {
    "test": ("test/", "tests/", "e2e/"),
    "documentation": ("doc/", "docs/", "readme"),
    "packaging": ("bundle/", "chart/", "charts/", ".build/", "dockerfile"),
    "deployment": ("deploy/", "deployments/", "manifest/", "manifests/", "helm/"),
    "generated": ("generated/", "vendor/"),
}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise SystemExit(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def classify(path: str) -> str:
    lower = path.lower()
    for category, markers in CLASSIFIERS.items():
        if any(marker in lower for marker in markers):
            return category
    return "behavior"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    base = git(repo, "rev-parse", f"{args.base}^{{commit}}").strip()
    target = git(repo, "rev-parse", f"{args.target}^{{commit}}").strip()
    merge_base = git(repo, "merge-base", base, target).strip()

    numstat = {}
    for line in git(repo, "diff", "--numstat", base, target).splitlines():
        added, deleted, path = line.split("\t", 2)
        numstat[path] = {"added": added, "deleted": deleted}

    files = []
    for line in git(repo, "diff", "--name-status", "-M", base, target).splitlines():
        fields = line.split("\t")
        status = fields[0]
        path = fields[-1]
        item = {"status": status, "path": path, "classification": classify(path)}
        item.update(numstat.get(path, {}))
        if status.startswith("R"):
            item["oldPath"] = fields[1]
        files.append(item)

    commits = []
    for line in git(repo, "log", "--reverse", "--format=%H%x09%s", f"{base}..{target}").splitlines():
        commit, subject = line.split("\t", 1)
        commits.append({"commit": commit, "subject": subject})

    result = {
        "repository": str(repo),
        "base": base,
        "target": target,
        "mergeBase": merge_base,
        "linearFromBase": merge_base == base,
        "commits": commits,
        "files": files,
        "summary": {
            "commitCount": len(commits),
            "fileCount": len(files),
            "classifications": {
                category: sum(item["classification"] == category for item in files)
                for category in sorted({item["classification"] for item in files})
            },
        },
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
