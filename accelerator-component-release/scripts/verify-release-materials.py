#!/usr/bin/env python3
"""Verify that a canonical release material directory is complete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

FILES = [
    "README.md", "_progress-table.md", "_release-readiness-gaps.md", "_approvals.md",
    "evidence/README.md", "01-change-list.md", "02-artifacts.md", "03-test-report.md",
    "04-security-report.md", "05-legacy-issues.md", "06-nonfunctional-decision.md",
    "07-release-note.md", "08-test-evidence.md", "09-release-rounds.md",
    "10-standard-review-checklist.md", "docs-update.md", "release-profile.yaml",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.release_dir.resolve()
    missing = [p for p in FILES if not (root / p).is_file()]
    empty = [p for p in FILES if (root / p).is_file() and not (root / p).read_text(encoding="utf-8").strip()]
    result = {"releaseDir": str(root), "requiredFiles": len(FILES), "missing": missing, "empty": empty, "passed": not missing and not empty}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"release-dir: {root}")
        print(f"required-files: {len(FILES)} missing: {len(missing)} empty: {len(empty)}")
        if missing:
            print("missing:", *missing, sep="\n- ")
        if empty:
            print("empty:", *empty, sep="\n- ")
        print("status: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
