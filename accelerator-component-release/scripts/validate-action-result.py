#!/usr/bin/env python3
"""Validate accelerator release action-result JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - local env normally has PyYAML
    yaml = None


VALID_STATUSES = {
    "succeeded",
    "failed",
    "warning",
    "blocked",
    "skipped",
    "dry-run",
    "needs-approval",
}


def error(errors: list[str], path: str, message: str) -> None:
    errors.append(f"{path}: {message}")


def as_list(value):
    return value if isinstance(value, list) else None


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"failed to read JSON {path}: {exc}") from exc


def load_profile(path: Path):
    if yaml is None:
        raise SystemExit("PyYAML is required for --profile validation")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"failed to read YAML profile {path}: {exc}") from exc


def normalize_action_id(doc: dict, errors: list[str]) -> str:
    action_id = doc.get("actionId")
    legacy = doc.get("action", {}).get("id") if isinstance(doc.get("action"), dict) else None
    if action_id and legacy and action_id != legacy:
        error(errors, "actionId", f"does not match action.id ({legacy})")
    action_id = action_id or legacy
    if not isinstance(action_id, str) or not action_id.strip():
        error(errors, "actionId", "missing; expected actionId or legacy action.id")
        return ""
    return action_id


def validate_string_array(value, path: str, errors: list[str], *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            error(errors, path, "missing")
        return []
    items = as_list(value)
    if items is None:
        error(errors, path, "must be an array")
        return []
    seen = set()
    result = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str) or not item.strip():
            error(errors, item_path, "must be a non-empty string")
            continue
        if item in seen:
            error(errors, item_path, f"duplicate value {item!r}")
        seen.add(item)
        result.append(item)
    return result


def validate_profile_contract(profile: dict, action_id: str, produced_facts: list[str], errors: list[str]) -> None:
    actions = profile.get("actions") if isinstance(profile, dict) else None
    if not isinstance(actions, list):
        error(errors, "profile.actions", "missing or not an array")
        return
    action = next((item for item in actions if isinstance(item, dict) and item.get("id") == action_id), None)
    if action is None:
        error(errors, "profile.actions", f"does not contain action id {action_id!r}")
        return
    allowed = set(action.get("produces") or []) | set(action.get("conditionalProduces") or [])
    unknown = [fact for fact in produced_facts if allowed and fact not in allowed]
    if unknown:
        error(
            errors,
            "summary.producedFacts",
            "facts are not declared by profile action: " + ", ".join(unknown),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--profile", type=Path, help="optional release profile to cross-check action/facts")
    parser.add_argument("--strict", action="store_true", help="require status and evidencePaths")
    args = parser.parse_args()

    doc = load_json(args.result)
    errors: list[str] = []
    warnings: list[str] = []
    action_id = ""
    produced_facts: list[str] = []

    if not isinstance(doc, dict):
        error(errors, "$", "must be a JSON object")
    else:
        action_id = normalize_action_id(doc, errors)
        status = doc.get("status")
        if status is None:
            if args.strict:
                error(errors, "status", "missing")
            else:
                warnings.append("status missing; accepted for legacy runner compatibility")
        elif status not in VALID_STATUSES:
            error(errors, "status", f"unsupported value {status!r}")

        summary = doc.get("summary")
        if not isinstance(summary, dict):
            error(errors, "summary", "missing or not an object")
        else:
            produced_facts = validate_string_array(
                summary.get("producedFacts"),
                "summary.producedFacts",
                errors,
                required=True,
            )
            validate_string_array(
                summary.get("evidencePaths"),
                "summary.evidencePaths",
                errors,
                required=args.strict,
            )
            validate_string_array(summary.get("closedGaps"), "summary.closedGaps", errors)

        if args.profile and action_id:
            validate_profile_contract(load_profile(args.profile), action_id, produced_facts, errors)

    for item in warnings:
        print(f"warning: {item}", file=sys.stderr)
    if errors:
        for item in errors:
            print(f"error: {item}", file=sys.stderr)
        return 1

    print(f"ok action-result={args.result} action={action_id} producedFacts={len(produced_facts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
