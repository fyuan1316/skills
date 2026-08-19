#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "PyYAML>=6.0",
# ]
# ///
"""Roadmap Studio: team roadmap diagnostics, Jira snapshots, and offline HTML views."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
SHARED_DASHBOARD_CSS = SKILL_ROOT / "assets" / "roadmap-dashboard.css"
ROADMAP_STUDIO_VERSION = "20260721-115855"
ROADMAP_STUDIO_VERSION_SCHEME = "yyyyMMdd-HHmmss"
ROADMAP_PLAN_MARKER = "[Roadmap Studio Plan]"
ROADMAP_PLAN_END_MARKER = "[/Roadmap Studio Plan]"
ROADMAP_CHANGE_MARKER = "[Roadmap Studio Change]"
ROADMAP_CHANGE_END_MARKER = "[/Roadmap Studio Change]"
PLAN_DEVIATION_LABEL = "roadmap:plan-deviation"
LANE_AGNOSTIC_LABEL = "lane:agnostic"
JIRA_EPIC_STATUS_FIELD = "customfield_10003"
JIRA_EPIC_LINK_FIELD = "customfield_10002"
JIRA_START_AFTER_FIELD = "customfield_12409"
JIRA_RISK_FIELD = "customfield_12240"
JIRA_STORY_POINTS_FIELD = "customfield_10006"
JIRA_SPRINT_FIELD = "customfield_10001"
JIRA_BASE_URL = "https://jira.alauda.cn"
CROSS_TEAM_LABEL = "跨团队需求"
JIRA_CHILD_QUERY_BATCH_SIZE = 20
JIRA_CHILD_QUERY_ATTEMPTS = 3
JIRA_CHILD_QUERY_RETRY_SLEEP_SECONDS = 10
# Heuristic mapping: small-feature Epics often share an "initiative" / theme
# (e.g. KubeOS adoption across 5 teams, or New Web Console with 4 own-team
# Epics + 1 cross-team compat Epic). Detect via summary keywords so we can
# group them under one card instead of listing N near-duplicate Epics flat.
#
# This grouping is NOT cross-team-only: an Epic that matches a keyword goes
# into the themed card regardless of whether it carries the 跨团队需求 label.
# The cross-team status is then surfaced as a per-Epic badge inside the card.
#
# Entry order = check order. Tuple = (slug, display name, list of lowercase keywords).
THEMED_FEATURE_INITIATIVES: list[tuple[str, str, tuple[str, ...]]] = [
    ("kubeos", "KubeOS 适配", ("kubeos",)),
    ("k8s-1-35", "Kubernetes 1.35 适配", ("kubernetes 1.35", "k8s 1.35", "k8s-1.35", "支持 kubernetes 1.35", "support kubernetes 1.35")),
    ("new-web-console", "New Web Console", ("new web console", "web console", "console 共存", "console 老/新")),
]
# Back-compat alias — old name still referenced from a few places.
CROSS_TEAM_INITIATIVES = THEMED_FEATURE_INITIATIVES
CHANGE_REQUIRED_FIELDS = ("changed", "from", "to", "reason")
CHANGE_REASON_CATEGORIES = {
    "前置收敛不足",
    "范围扩张",
    "资源挤占",
    "人员切换",
    "执行治理不闭环",
    "优先级调整",
    "外部依赖",
    "容量/假期影响",
    "其他",
}
BUILDERS_TEAM_DIRS = [
    "ai-platform",
    "app-service",
    "container",
    "devops",
    "hyperflux",
    "infrastructure",
    "platform",
    "solution",
]

DOMAIN_NAMES = {
    "1": "Infrastructure",
    "2": "Lifecycle & Operations",
    "3": "Multi-Cluster Management",
    "4": "Security & Compliance",
    "5": "Observability",
    "6": "Developer Experience & Delivery",
    "7": "Application Services",
    "8": "Virtualization",
    "9": "AI & Intelligent Platform",
}


def looks_like_installed_config_root(path: Path) -> bool:
    return (path / ".alauda-config-root").exists() and (path / "knowledge" / "builders").exists()


def looks_like_builders_repo(path: Path) -> bool:
    return (path / "builders" / "skills" / "builders-roadmap-studio").exists() and (path / "builders" / "knowledge" / "builders").exists()


def find_builders_repo(start: Path) -> Path | None:
    resolved = start.expanduser().resolve()
    search_roots = [resolved] if resolved.is_dir() else [resolved.parent]
    for root in search_roots:
        for candidate in (root, *root.parents):
            if looks_like_installed_config_root(candidate):
                return candidate
            if looks_like_builders_repo(candidate):
                return candidate
    return None


def resolve_builders_repo(repo_arg: str | None) -> Path:
    search_starts: list[Path] = []
    if repo_arg:
        search_starts.append(Path(repo_arg).expanduser().resolve())
    env_value = os.environ.get("ROADMAP_STUDIO_REPO") or os.environ.get("ALAUDA_AI_BUILDERS_REPO")
    if env_value:
        search_starts.append(Path(env_value).expanduser().resolve())
    search_starts.extend([Path.cwd(), SKILL_ROOT])
    for start in search_starts:
        repo = find_builders_repo(start)
        if repo:
            return repo
    raise SystemExit(
        "Cannot resolve Roadmap Studio workspace root. Run from alauda-ai-config or alauda-ai-builders, "
        "or pass --repo/ROADMAP_STUDIO_REPO pointing inside one of those workspaces."
    )


def workspace_layout(repo: Path) -> str:
    if looks_like_installed_config_root(repo):
        return "installed"
    if looks_like_builders_repo(repo):
        return "source"
    raise SystemExit(f"Unsupported Roadmap Studio workspace root: {repo}")


def builders_skill_root(repo: Path, skill_name: str) -> Path:
    if workspace_layout(repo) == "installed":
        return repo / ".codex" / "skills" / skill_name
    return repo / "builders" / "skills" / skill_name


def builders_knowledge_root(repo: Path) -> Path:
    if workspace_layout(repo) == "installed":
        return repo / "knowledge" / "builders"
    return repo / "builders" / "knowledge" / "builders"


def team_roadmap_root(repo: Path, team_key: str) -> Path:
    if workspace_layout(repo) == "installed":
        return repo / "knowledge" / team_key / "roadmap"
    return repo / team_key / "knowledge" / team_key / "roadmap"


def dashboard_output_root(repo: Path) -> Path:
    return builders_knowledge_root(repo) / "roadmap"


def builders_dashboard_path(repo: Path) -> Path:
    return dashboard_output_root(repo) / "roadmap-dashboard.html"


def builders_index_path(repo: Path) -> Path:
    return dashboard_output_root(repo) / "roadmap-studio-index.md"


def builders_taxonomy_path(repo: Path) -> Path:
    return builders_knowledge_root(repo) / "framework" / "capability-taxonomy.md"


def available_team_keys(repo: Path) -> list[str]:
    if workspace_layout(repo) == "installed":
        knowledge_root = repo / "knowledge"
        discovered = [
            path.name for path in knowledge_root.iterdir()
            if path.is_dir() and path.name not in {"base", "builders"}
        ] if knowledge_root.exists() else []
        ordered = [team for team in BUILDERS_TEAM_DIRS if team in discovered]
        extras = sorted(set(discovered) - set(BUILDERS_TEAM_DIRS))
        return ordered + extras
    return [team for team in BUILDERS_TEAM_DIRS if (repo / team).is_dir()]


def release_meta_candidates(repo: Path) -> list[Path]:
    patterns = [
        "*/knowledge/*/roadmap/releases/*/roadmap-meta.yaml",
        "knowledge/*/roadmap/releases/*/roadmap-meta.yaml",
    ]
    metas: set[Path] = set()
    for pattern in patterns:
        metas.update(repo.glob(pattern))
    return sorted(metas)


def repo_relative_path(repo: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def html_relative_href(from_file: Path, target: Path) -> str:
    return os.path.relpath(target.resolve(), start=from_file.resolve().parent)


def builders_jira_scripts_path(repo: Path) -> Path:
    candidates = [
        builders_skill_root(repo, "builders-jira") / "scripts",
        repo / "builders" / "skills" / "builders-jira" / "scripts",
        SKILL_ROOT.parent / "builders-jira" / "scripts",
    ]
    for candidate in candidates:
        if (candidate / "jira_client.py").exists():
            return candidate
    raise SystemExit("Cannot resolve builders-jira scripts. Ensure builders-jira exists in the repo or installed skills directory.")


@dataclass
class RoadmapItem:
    roadmap_id: str
    feature_id: str
    ocp_feature: str
    capability: str
    score: str
    effort: str
    title: str
    strategic_rationale: str
    definition_of_done: str
    priority_group: str
    expected_label: str
    domain: str = ""
    epics: list[dict[str, Any]] = field(default_factory=list)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_yaml(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)


def shared_dashboard_css() -> str:
    if SHARED_DASHBOARD_CSS.exists():
        return read_text(SHARED_DASHBOARD_CSS)
    return """
/* Roadmap Studio Shared CSS fallback */
.kpis{align-items:stretch}.kpis>*{height:100%;min-width:0}.kpi-link{display:block;height:100%;color:inherit;text-decoration:none;font-family:inherit;font-weight:inherit}.kpi{height:100%;min-height:148px;display:flex;flex-direction:column}.kpi-bar,.progress-bar{margin-top:auto;flex-shrink:0}
""".strip()


def roadmap_studio_version_line() -> str:
    return f"builders-roadmap-studio {ROADMAP_STUDIO_VERSION}"


def snapshot_roadmap_studio_version(snapshot: dict[str, Any]) -> str:
    version = snapshot.get("roadmap_studio_version")
    if version:
        return str(version)
    generated_by = str(snapshot.get("generated_by") or "")
    match = re.search(r"builders-roadmap-studio\s+([0-9]{8}-[0-9]{6})", generated_by)
    if match:
        return match.group(1)
    return "unknown-pre-versioning"


def slugify(value: str) -> str:
    raw = value.lower().strip()
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return raw or "item"


def compact_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def version_label(version: str) -> str:
    return "roadmap-" + version.replace(".", "-")


def item_label(version: str, slug: str) -> str:
    return f"roadmap:{version}:{slug}"


def small_features_label(version: str) -> str:
    return f"roadmap:{version}:small-features"


def jira_url(key: str) -> str:
    return f"{JIRA_BASE_URL}/browse/{key}"


def jira_md(key: str) -> str:
    return f"[{key}]({jira_url(key)})"


def jira_html(key: str) -> str:
    safe = html.escape(key or "")
    return f'<a href="{jira_url(safe)}" target="_blank" rel="noreferrer">{safe}</a>' if safe else ""


def release_root_from_meta(meta_path: Path) -> Path:
    return meta_path.parent


def roadmap_root_from_release(release_dir: Path) -> Path:
    return release_dir.parent.parent


def profile_team_key_for_meta(meta_path: Path) -> str:
    release_dir = release_root_from_meta(meta_path)
    meta = load_yaml(meta_path) or {}
    profile = load_yaml(team_profile_path(release_dir, meta)) or {}
    return str(profile.get("team_key") or roadmap_root_from_release(release_dir).parent.name)


def find_release_meta(repo: Path, version: str | None, team: str | None = None) -> Path | None:
    metas = release_meta_candidates(repo)
    if team:
        metas = [
            meta for meta in metas
            if profile_team_key_for_meta(meta) == team or roadmap_root_from_release(meta.parent).parent.name == team
        ]
    if version:
        candidates = [meta for meta in metas if meta.parent.name == version]
        if len(candidates) == 1:
            return candidates[0]
        active = [
            meta for meta in candidates
            if (load_yaml(meta) or {}).get("role") == "current" or (load_yaml(meta) or {}).get("status") == "active"
        ]
        if len(active) == 1:
            return active[0]
        if len(candidates) > 1:
            options = ", ".join(f"{profile_team_key_for_meta(meta)}:{meta.parent.name}" for meta in candidates)
            raise SystemExit(f"Ambiguous release {version}. Pass --team. Candidates: {options}")
        return None
    ranked: list[tuple[int, str, Path]] = []
    for meta_path in metas:
        meta = load_yaml(meta_path) or {}
        role = meta.get("role")
        status = meta.get("status")
        ver = str(meta.get("version") or meta_path.parent.name)
        if role == "current":
            ranked.append((0, ver, meta_path))
        elif status == "active":
            ranked.append((1, ver, meta_path))
    if not ranked:
        return None
    best_rank = sorted(ranked)[0][0]
    best = [item for item in ranked if item[0] == best_rank]
    if len(best) > 1:
        options = ", ".join(f"{profile_team_key_for_meta(meta)}:{ver}" for _, ver, meta in best)
        raise SystemExit(f"Ambiguous current Roadmap Studio release. Pass --team and --version. Candidates: {options}")
    return sorted(ranked)[0][2]


def release_file(release_dir: Path, meta: dict[str, Any], key: str, default: str) -> Path:
    value = str(meta.get(key) or default)
    path = Path(value)
    return path if path.is_absolute() else release_dir / path


def team_profile_path(release_dir: Path, meta: dict[str, Any]) -> Path:
    if meta.get("team_profile_file"):
        path = Path(str(meta["team_profile_file"]))
        return path if path.is_absolute() else release_dir / path
    return roadmap_root_from_release(release_dir) / "team-profile.yaml"


def split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_roadmap_items(roadmap_path: Path, version: str) -> list[RoadmapItem]:
    items: list[RoadmapItem] = []
    current_group = ""
    for raw_line in read_text(roadmap_path).splitlines():
        line = raw_line.strip()
        if line.startswith("### 2.1"):
            current_group = "High Priority"
            continue
        if line.startswith("### 2.2"):
            current_group = "Optimization"
            continue
        if line.startswith("### 2.3"):
            current_group = "Production Hardening"
            continue
        if not line.startswith("|") or "|---" in line or "| # |" in line:
            continue
        cells = split_markdown_table_row(line)
        if len(cells) != 9 or not cells[0].isdigit():
            continue
        title = cells[6]
        feature_id = cells[1]
        domain_key = feature_id.split(".", 1)[0]
        slug = slugify(title)
        items.append(RoadmapItem(
            roadmap_id=f"#{cells[0]}",
            feature_id=feature_id,
            ocp_feature=cells[2],
            capability=cells[3],
            score=cells[4],
            effort=cells[5],
            title=title,
            strategic_rationale=cells[7],
            definition_of_done=cells[8],
            priority_group=current_group,
            expected_label=item_label(version, slug),
            domain=DOMAIN_NAMES.get(domain_key, domain_key),
        ))
    return items


def load_context(repo: Path, version_arg: str | None, team_arg: str | None = None) -> dict[str, Any]:
    meta_path = find_release_meta(repo, version_arg, team_arg)
    if not meta_path:
        raise SystemExit(
            "Cannot resolve Roadmap Studio release. Create team-profile.yaml and "
            "releases/<version>/roadmap-meta.yaml, or pass --team and --version."
        )
    return load_context_from_meta(repo, meta_path)


def load_context_from_meta(repo: Path, meta_path: Path) -> dict[str, Any]:
    release_dir = release_root_from_meta(meta_path)
    meta = load_yaml(meta_path) or {}
    version = str(meta.get("version") or release_dir.name)
    profile_path = team_profile_path(release_dir, meta)
    profile = load_yaml(profile_path) or {}
    roadmap_path = release_file(release_dir, meta, "roadmap_file", "roadmap.md")
    changelog_path = release_file(release_dir, meta, "changelog_file", "roadmap-changelog.md")
    snapshot_path = release_file(release_dir, meta, "jira_snapshot_file", "snapshots/jira-execution-snapshot.yaml")
    gantt_path = release_file(release_dir, meta, "gantt_output_file", "snapshots/roadmap-gantt.html")
    progress_gantt_path = release_file(release_dir, meta, "progress_gantt_output_file", "snapshots/roadmap-progress-gantt.html") if meta.get("progress_gantt_output_file") else None
    return {
        "repo": repo,
        "version": version,
        "meta_path": meta_path,
        "meta": meta,
        "release_dir": release_dir,
        "roadmap_root": roadmap_root_from_release(release_dir),
        "profile_path": profile_path,
        "profile": profile,
        "roadmap_path": roadmap_path,
        "changelog_path": changelog_path,
        "snapshot_path": snapshot_path,
        "gantt_path": gantt_path,
        "progress_gantt_path": progress_gantt_path,
        "version_label": version_label(version),
        "small_features_label": small_features_label(version),
        "jira_project": profile.get("jira_project") or meta.get("jira_project") or "",
    }


def sub_team_labels(profile: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for team in profile.get("sub_teams") or []:
        for label in team.get("jira_labels") or []:
            labels.add(str(label))
    return labels


def external_jira_projects(profile: dict[str, Any]) -> list[dict[str, str]]:
    projects: list[dict[str, str]] = []
    for item in profile.get("external_jira_projects") or []:
        if not isinstance(item, dict):
            continue
        team = str(item.get("team") or item.get("name") or "").strip()
        project = str(item.get("project") or item.get("key") or "").strip()
        url = str(item.get("url") or "").strip()
        if team and project:
            projects.append({"team": team, "project": project, "url": url})
    return projects


def external_project_team_map(profile: dict[str, Any]) -> dict[str, str]:
    return {item["project"]: item["team"] for item in external_jira_projects(profile)}


def issue_project_key(issue: dict[str, Any]) -> str:
    return str(issue.get("project_key") or issue.get("key", "").split("-", 1)[0])


def detect_themed_initiative(summary: str) -> tuple[str, str] | None:
    """Return (slug, display_name) for a themed small-feature Epic, or None if
    the Epic's summary does not match any configured initiative. Callers that
    need a fallback bucket should handle the None case explicitly — we no
    longer auto-route unmatched Epics into a generic "other" theme bucket
    because doing so dilutes the signal that themed cards exist to provide.
    """
    s = (summary or "").lower()
    for slug, name, keywords in THEMED_FEATURE_INITIATIVES:
        if any(kw in s for kw in keywords):
            return slug, name
    return None


def detect_cross_team_initiative(summary: str) -> tuple[str, str]:
    """Back-compat shim — old callers expected ("other", ...) as a fallback."""
    match = detect_themed_initiative(summary)
    if match is not None:
        return match
    return "other", "其他跨团队工作"


def is_cross_team_issue(issue: dict[str, Any]) -> bool:
    return CROSS_TEAM_LABEL in (issue.get("labels") or [])


def sub_team_for_issue(issue: dict[str, Any], profile: dict[str, Any]) -> str:
    external_team = external_project_team_map(profile).get(issue_project_key(issue))
    if external_team:
        return external_team
    issue_labels = set(issue.get("labels") or [])
    for team in profile.get("sub_teams") or []:
        if issue_labels.intersection(set(team.get("jira_labels") or [])):
            return str(team.get("name") or "Unknown")
    return "Unknown"


def is_external_issue(issue: dict[str, Any], profile: dict[str, Any]) -> bool:
    return issue_project_key(issue) in external_project_team_map(profile)


def normalize_issue_links(issue: dict[str, Any]) -> list[dict[str, Any]]:
    fields = issue.get("fields") or {}
    links: list[dict[str, Any]] = []
    for link in fields.get("issuelinks") or []:
        link_type = link.get("type") or {}
        linked = link.get("outwardIssue") or link.get("inwardIssue") or {}
        linked_fields = linked.get("fields") or {}
        linked_status = linked_fields.get("status") or {}
        linked_issuetype = linked_fields.get("issuetype") or {}
        if link.get("outwardIssue"):
            direction = "outward"
            relationship = link_type.get("outward") or link_type.get("name") or "links to"
        else:
            direction = "inward"
            relationship = link_type.get("inward") or link_type.get("name") or "linked from"
        links.append({
            "link_type": link_type.get("name") or "",
            "direction": direction,
            "relationship": relationship,
            "key": linked.get("key") or "",
            "summary": linked_fields.get("summary") or "",
            "issue_type": linked_issuetype.get("name") or "",
            "status_name": linked_status.get("name") or "",
            "status_category": (linked_status.get("statusCategory") or {}).get("name") or "",
            "labels": linked_fields.get("labels") or [],
        })
    return links


def option_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("name") or "")
    return str(value or "")


def parse_jira_sprint_name(raw: Any) -> str:
    if not raw:
        return ""
    text = str(raw)
    match = re.search(r"name=([^,\]]+)", text)
    return match.group(1).strip() if match else text


def parse_jira_sprints(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [name for name in (parse_jira_sprint_name(item) for item in value) if name]
    name = parse_jira_sprint_name(value)
    return [name] if name else []


def issue_fields(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    project = fields.get("project") or {}
    status = fields.get("status") or {}
    issuetype = fields.get("issuetype") or {}
    assignee = fields.get("assignee") or {}
    epic_status_field = fields.get(JIRA_EPIC_STATUS_FIELD)
    if isinstance(epic_status_field, dict):
        epic_status = epic_status_field.get("value") or "To Do"
    elif epic_status_field:
        epic_status = str(epic_status_field)
    else:
        epic_status = "To Do"
    comments = ((fields.get("comment") or {}).get("comments") or [])
    roadmap_plan = ""
    roadmap_changes: list[dict[str, Any]] = []
    for comment in reversed(comments):
        body = comment.get("body") or ""
        if ROADMAP_PLAN_MARKER in body:
            roadmap_plan = body
            break
    for comment in comments:
        body = comment.get("body") or ""
        if ROADMAP_CHANGE_MARKER in body:
            change = extract_change(body)
            if change:
                change["comment_id"] = comment.get("id") or ""
                change["created"] = comment.get("created") or ""
                author = comment.get("author") or {}
                change["author"] = author.get("displayName") or author.get("name") or ""
                roadmap_changes.append(change)
    return {
        "key": issue.get("key") or "",
        "project_key": project.get("key") or str(issue.get("key") or "").split("-", 1)[0],
        "project_name": project.get("name") or "",
        "summary": fields.get("summary") or "",
        "description": fields.get("description") or "",
        "issue_type": issuetype.get("name") or "",
        "status_name": status.get("name") or "",
        "status_category": (status.get("statusCategory") or {}).get("name") or "",
        "epic_status": epic_status,
        "assignee": assignee.get("displayName") or assignee.get("name") or "",
        "updated": fields.get("updated") or "",
        "labels": fields.get("labels") or [],
        "components": [component.get("name") for component in (fields.get("components") or [])],
        "fix_versions": [version.get("name") for version in (fields.get("fixVersions") or [])],
        "start_after": fields.get(JIRA_START_AFTER_FIELD) or "",
        "due_date": fields.get("duedate") or "",
        "risk": option_value(fields.get(JIRA_RISK_FIELD)) or "",
        "roadmap_plan": roadmap_plan,
        "roadmap_changes": roadmap_changes,
        "issue_links": normalize_issue_links(issue),
    }


def child_issue_fields(issue: dict[str, Any], epic_key: str) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    issuetype = fields.get("issuetype") or {}
    return {
        "key": issue.get("key") or "",
        "summary": fields.get("summary") or "",
        "issue_type": issuetype.get("name") or "",
        "status_name": status.get("name") or "",
        "status_category": (status.get("statusCategory") or {}).get("name") or "",
        "assignee": assignee.get("displayName") or assignee.get("name") or "",
        "updated": fields.get("updated") or "",
        "story_points": fields.get(JIRA_STORY_POINTS_FIELD),
        "sprints": parse_jira_sprints(fields.get(JIRA_SPRINT_FIELD)),
        "parent_epic": epic_key,
    }


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[idx:idx + size] for idx in range(0, len(items), size)]


def jira_key_list(keys: list[str]) -> str:
    return ", ".join(keys)


def positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def jira_child_query(jira_search, relation: str, batch_idx: int, child_jql: str, child_fields: list[str]) -> list[dict[str, Any]]:
    attempts = positive_int_env("ROADMAP_STUDIO_CHILD_QUERY_ATTEMPTS", JIRA_CHILD_QUERY_ATTEMPTS)
    sleep_seconds = positive_int_env(
        "ROADMAP_STUDIO_CHILD_QUERY_RETRY_SLEEP_SECONDS",
        JIRA_CHILD_QUERY_RETRY_SLEEP_SECONDS,
    )
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return jira_search(child_jql, fields=child_fields, max_results=1000)
        except Exception as exc:
            last_exc = exc
            print(
                f"JIRA: child issue query failed ({relation}) for batch {batch_idx} "
                f"attempt {attempt}/{attempts}: {child_jql} :: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if attempt < attempts:
                time.sleep(sleep_seconds)
    raise RuntimeError(
        f"Jira child issue query failed after {attempts} attempts ({relation}) "
        f"for batch {batch_idx}: {child_jql}"
    ) from last_exc


def child_parent_epic(issue: dict[str, Any], epic_keys: set[str]) -> str:
    fields = issue.get("fields") or {}
    epic_link = fields.get(JIRA_EPIC_LINK_FIELD)
    if isinstance(epic_link, str) and epic_link in epic_keys:
        return epic_link
    if isinstance(epic_link, dict):
        key = epic_link.get("key") or epic_link.get("value")
        if key in epic_keys:
            return str(key)
    parent = fields.get("parent") or {}
    if isinstance(parent, dict):
        key = parent.get("key")
        if key in epic_keys:
            return str(key)
    return ""


def fetch_child_issues_for_epics(jira_search, epics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    epic_keys = [epic.get("key") or "" for epic in epics if epic.get("key")]
    epic_key_set = set(epic_keys)
    if not epic_keys:
        return []
    child_fields = [
        "summary",
        "status",
        "assignee",
        "updated",
        "issuetype",
        JIRA_STORY_POINTS_FIELD,
        JIRA_SPRINT_FIELD,
        JIRA_EPIC_LINK_FIELD,
        "parent",
    ]
    children: list[dict[str, Any]] = []
    seen: set[str] = set()
    batch_size = positive_int_env("ROADMAP_STUDIO_CHILD_QUERY_BATCH_SIZE", JIRA_CHILD_QUERY_BATCH_SIZE)
    batches = chunked(epic_keys, batch_size)
    for batch_idx, batch in enumerate(batches, start=1):
        print(
            f"JIRA: child issue batch {batch_idx}/{len(batches)} ({batch[0]}..{batch[-1]})",
            file=sys.stderr,
            flush=True,
        )
        for relation, child_jql in (
            ("Epic Link", f'"Epic Link" in ({jira_key_list(batch)}) ORDER BY key ASC'),
            ("parent", f'parent in ({jira_key_list(batch)}) ORDER BY key ASC'),
        ):
            batch_children = jira_child_query(jira_search, relation, batch_idx, child_jql, child_fields)
            for child in batch_children:
                child_key = child.get("key") or ""
                if not child_key or child_key in seen:
                    continue
                parent_epic = child_parent_epic(child, epic_key_set)
                if not parent_epic:
                    continue
                seen.add(child_key)
                children.append(child_issue_fields(child, parent_epic))
    return children


def load_jira_client(repo: Path):
    sys.path.insert(0, str(builders_jira_scripts_path(repo)))
    from jira_client import jira_search  # type: ignore
    return jira_search


def fetch_live_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    jira_search = load_jira_client(Path(ctx["repo"]))
    project = ctx["jira_project"]
    profile = ctx["profile"]
    external_keys = [item["project"] for item in external_jira_projects(profile) if item["project"] != project]
    project_keys = [project] + external_keys
    vlabel = ctx["version_label"]
    fields = ["summary", "description", "status", JIRA_EPIC_STATUS_FIELD, "assignee", "updated", "issuetype", "project", "labels", "components", "fixVersions", JIRA_START_AFTER_FIELD, "duedate", JIRA_RISK_FIELD, "comment", "issuelinks"]
    # Restrict external-project Epics to those explicitly marked as cross-team work.
    # Without this, every external team's own roadmap items (with the same version
    # label but their own roadmap slugs) would leak into this team's snapshot.
    own_part = f'project = {project} AND labels = "{vlabel}"'
    if external_keys:
        ext_part = (
            f'project in ({", ".join(external_keys)}) AND labels = "{vlabel}" '
            f'AND labels = "{CROSS_TEAM_LABEL}"'
        )
        jql = f'issuetype = Epic AND (({own_part}) OR ({ext_part})) ORDER BY key ASC'
    else:
        jql = f'issuetype = Epic AND ({own_part}) ORDER BY key ASC'
    print(f"JIRA: fetching roadmap Epics for {', '.join(project_keys)} / {vlabel} (external limited to {CROSS_TEAM_LABEL})...", file=sys.stderr, flush=True)
    issues = [issue_fields(issue) for issue in jira_search(jql, fields=fields, max_results=300)]
    print(f"JIRA: fetched {len(issues)} Epics; fetching child issues...", file=sys.stderr, flush=True)
    children = fetch_child_issues_for_epics(jira_search, issues)
    print(f"JIRA: fetched {len(children)} child issues", file=sys.stderr, flush=True)
    return {
        "schema_version": 2,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": f"{roadmap_studio_version_line()} refresh-snapshot",
        "roadmap_studio_version": ROADMAP_STUDIO_VERSION,
        "roadmap_studio_version_scheme": ROADMAP_STUDIO_VERSION_SCHEME,
        "source_mode": "live-jira",
        "release_version": ctx["version"],
        "jira_project": project,
        "jira_projects": project_keys,
        "external_jira_projects": external_jira_projects(profile),
        "version_label": vlabel,
        "small_features_label": ctx["small_features_label"],
        "issue_count": len(issues),
        "child_issue_count": len(children),
        "issues": issues,
        "child_issues": children,
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    data = load_yaml(path) or {}
    data.setdefault("issues", [])
    data.setdefault("child_issues", [])
    for issue in data.get("issues") or []:
        normalized_changes = []
        for change in issue.get("roadmap_changes") or []:
            if isinstance(change, dict):
                normalized_changes.append(normalize_change_payload(change))
        issue["roadmap_changes"] = normalized_changes
    return data


def extract_plan(raw: str) -> dict[str, Any]:
    if not raw or ROADMAP_PLAN_MARKER not in raw:
        return {}
    body = raw.split(ROADMAP_PLAN_MARKER, 1)[1]
    if ROADMAP_PLAN_END_MARKER in body:
        body = body.split(ROADMAP_PLAN_END_MARKER, 1)[0]
    body = body.strip()
    if not body:
        return {}
    try:
        parsed = yaml.safe_load(body) or {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def normalize_change_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parsed)
    warnings: list[str] = []
    if not normalized.get("from") and normalized.get("old") not in (None, ""):
        normalized["from"] = normalized.get("old")
    if not normalized.get("to") and normalized.get("new") not in (None, ""):
        normalized["to"] = normalized.get("new")
    if normalized.get("notes") in (None, "", []) and normalized.get("impact") not in (None, ""):
        normalized["notes"] = normalized.get("impact")
    missing = [field for field in CHANGE_REQUIRED_FIELDS if normalized.get(field) in (None, "", [])]
    if missing:
        warnings.append("missing required fields: " + ", ".join(missing))
    if warnings:
        normalized["schema_warnings"] = warnings
    else:
        normalized.pop("schema_warnings", None)
    return normalized


def extract_change(raw: str) -> dict[str, Any]:
    if not raw or ROADMAP_CHANGE_MARKER not in raw:
        return {}
    body = raw.split(ROADMAP_CHANGE_MARKER, 1)[1]
    if ROADMAP_CHANGE_END_MARKER in body:
        body = body.split(ROADMAP_CHANGE_END_MARKER, 1)[0]
    body = body.strip()
    if not body:
        return {}
    try:
        parsed = yaml.safe_load(body) or {}
        if not isinstance(parsed, dict):
            return {}
        return normalize_change_payload(parsed)
    except Exception:
        return {}


def normalize_status(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"done", "完成", "已完成", "已解决", "resolved"}:
        return "Done"
    if raw in {"in progress", "进行中", "设计完成", "开发完成", "处理中", "ready for qa"}:
        return "In Progress"
    return "To Do"


def child_status_bucket(issue: dict[str, Any]) -> str:
    category = (issue.get("status_category") or "").lower()
    name = (issue.get("status_name") or "").lower()
    if "cancel" in name or "取消" in name:
        return "cancelled"
    done_names = {"done", "已完成", "已解决", "resolved"}
    progress_names = {"in progress", "处理中", "ready for qa"}
    if category in {"done", "完成"} or name in done_names or "完成" in name:
        return "done"
    if category in {"in progress", "处理中"} or name in progress_names or "进行" in name or "开发" in name or "设计" in name:
        return "in_progress"
    return "todo"



def normalize_token(token: str) -> str:
    aliases = {
        "migration": "migrate",
        "migrating": "migrate",
        "lifecycle": "lifecycle",
        "lifecycles": "lifecycle",
    }
    if token in aliases:
        return aliases[token]
    for suffix in ("ization", "ation", "ing", "ed", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def normalized_tokens(value: str) -> set[str]:
    stop = {"and", "the", "as", "a", "of", "to", "with", "for", "in", "on", "multi", "cluster"}
    return {normalize_token(token) for token in re.findall(r"[a-z0-9]+", slugify(value)) if token and token not in stop}


def label_slug(label: str, version: str) -> str:
    prefix = f"roadmap:{version}:"
    return label[len(prefix):] if label.startswith(prefix) else label


def item_match_score(item: RoadmapItem, issue: dict[str, Any], label: str, version: str) -> int:
    slug = label_slug(label, version)
    candidates = {
        slugify(item.title),
        slugify(re.sub(r"\([^)]*\)", "", item.title)),
        slugify(item.ocp_feature),
        slugify(item.capability),
    }
    if slug in candidates:
        return 100
    issue_summary = str(issue.get("summary") or "")
    if slugify(issue_summary) in candidates or slugify(re.sub(r"\([^)]*\)", "", issue_summary)) in candidates:
        return 90
    label_tokens = normalized_tokens(slug)
    item_tokens = normalized_tokens(" ".join([item.title, item.ocp_feature, item.capability]))
    summary_tokens = normalized_tokens(issue_summary)
    overlap = len(label_tokens & item_tokens) + len(summary_tokens & item_tokens)
    if overlap >= 2:
        return 50 + overlap
    if overlap == 1 and len(label_tokens) == 1:
        return 25
    return 0


def best_item_for_issue(items: list[RoadmapItem], issue: dict[str, Any], version: str) -> RoadmapItem | None:
    labels = [label for label in (issue.get("labels") or []) if label.startswith(f"roadmap:{version}:")]
    best: tuple[int, RoadmapItem] | None = None
    for label in labels:
        for item in items:
            score = item_match_score(item, issue, label, version)
            if score and (best is None or score > best[0]):
                best = (score, item)
    return best[1] if best and best[0] >= 50 else None


def attach_epics(items: list[RoadmapItem], issues: list[dict[str, Any]], version: str, own_project: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify Epics into the team's roadmap items, small-features, or unclassified.

    Cross-team / external-project Epics are treated as follows:
    - Epic slug matches a roadmap item in this team's roadmap.md → attach to that
      item regardless of which Jira project the Epic lives in (external team
      contributing to our roadmap).
    - Epic carries the small-features label → small bucket.
    - Epic has a formal `roadmap:x.y:<slug>` label that does NOT match this team's
      roadmap.md AND lives in an external project AND lacks `跨团队需求`:
      that Epic belongs to the other team's own roadmap and is silently skipped
      so it does not pollute this team's view.
    - Otherwise (own-project unmatched, or external + `跨团队需求` but no slug
      match) → unclassified bucket, tagged with `_unclassified_reason` for audit.
    """
    item_by_id = {item.roadmap_id: item for item in items}
    item_by_expected_label = {item.expected_label: item for item in items}
    small_label = small_features_label(version)
    small: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []
    for item in items:
        item.epics = []
    for issue in issues:
        labels = set(issue.get("labels") or [])
        plan = extract_plan(issue.get("roadmap_plan") or "")
        issue["roadmap_studio_plan"] = plan
        if small_label in labels or plan.get("classification") == "small-features":
            small.append(issue)
            continue
        target_item: RoadmapItem | None = None
        roadmap_item_id = str(plan.get("roadmap_item") or "").strip()
        if roadmap_item_id in item_by_id:
            target_item = item_by_id[roadmap_item_id]
        if not target_item:
            for label in labels:
                if label in item_by_expected_label:
                    target_item = item_by_expected_label[label]
                    break
        if not target_item:
            target_item = best_item_for_issue(items, issue, version)
        if target_item:
            target_item.epics.append(issue)
            continue
        formal_labels = sorted(
            label for label in labels
            if label.startswith(f"roadmap:{version}:") and label != small_label
        )
        if not formal_labels:
            continue
        issue_project = issue.get("project_key") or ""
        is_external = bool(own_project) and bool(issue_project) and issue_project != own_project
        if is_external and CROSS_TEAM_LABEL not in labels:
            # External team's own roadmap item; not relevant to this team's view.
            continue
        # Tag why this Epic landed in unclassified to make audits easy.
        if is_external:
            reason = (
                f"external project {issue_project} carries {CROSS_TEAM_LABEL} but its formal slug(s) "
                f"({', '.join(formal_labels)}) do not match any roadmap item in this team's roadmap.md"
            )
        else:
            reason = (
                f"{issue_project or 'own'} project Epic carries formal slug(s) "
                f"({', '.join(formal_labels)}) not present in this team's roadmap.md"
            )
        issue["_unclassified_reason"] = reason
        unclassified.append(issue)
    return small, unclassified


def sprint_windows(ctx: dict[str, Any]) -> list[dict[str, str]]:
    version = ctx["version"]
    start_raw = str(ctx["meta"].get("sprint_start_date") or "")
    release_raw = str(ctx["meta"].get("code_freeze_date") or ctx["meta"].get("release_target_date") or "")
    try:
        start_date = dt.date.fromisoformat(start_raw)
        release_date = dt.date.fromisoformat(release_raw)
    except ValueError:
        return []
    sprints: list[dict[str, str]] = []
    index = 1
    cursor = start_date.replace(day=1)
    release_month = release_date.replace(day=1)
    while cursor <= release_month:
        next_month = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        month_end = next_month - dt.timedelta(days=1)
        first_start = max(cursor, start_date)
        first_end = min(cursor.replace(day=15), release_date)
        if first_start <= first_end:
            sprints.append({"name": f"{version}-S{index}", "start": first_start.isoformat(), "end": first_end.isoformat()})
            index += 1
        second_start = max(cursor.replace(day=16), start_date)
        second_end = min(month_end, release_date)
        if second_start <= second_end:
            sprints.append({"name": f"{version}-S{index}", "start": second_start.isoformat(), "end": second_end.isoformat()})
            index += 1
        cursor = next_month
    return sprints


def next_minor_version(version: str) -> str:
    parts = str(version or "").split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{int(parts[1]) + 1}"
    return f"{version}-next"


def add_months(value: dt.date, months: int) -> dt.date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    next_month = (dt.date(year, month, 28) + dt.timedelta(days=4)).replace(day=1)
    month_end = next_month - dt.timedelta(days=1)
    return value.replace(year=year, month=month, day=min(value.day, month_end.day))


def agnostic_extension_windows(ctx: dict[str, Any]) -> list[dict[str, str]]:
    version = next_minor_version(str(ctx.get("version") or ""))
    start_raw = str(ctx.get("meta", {}).get("code_freeze_date") or "")
    release_raw = str(ctx.get("meta", {}).get("release_target_date") or "")
    try:
        start_date = dt.date.fromisoformat(start_raw) + dt.timedelta(days=1)
        end_date = add_months(dt.date.fromisoformat(release_raw), 1)
    except ValueError:
        return []
    if start_date > end_date:
        return []
    windows: list[dict[str, str]] = []
    index = 1
    cursor = start_date
    while cursor <= end_date:
        if cursor.day <= 15:
            period_end = min(cursor.replace(day=15), end_date)
        else:
            next_month = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            period_end = min(next_month - dt.timedelta(days=1), end_date)
        windows.append({"name": f"{version}-S{index} extension window", "start": cursor.isoformat(), "end": period_end.isoformat()})
        index += 1
        cursor = period_end + dt.timedelta(days=1)
    return windows


def snapshot_generated_date(snapshot: dict[str, Any]) -> dt.date | None:
    raw = str(snapshot.get("generated_at") or "")
    if not raw:
        return None
    try:
        generated = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if generated.tzinfo is None:
        return generated.date()
    return generated.astimezone().date()


def current_sprint_from_snapshot(ctx: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    sprints = sprint_windows(ctx)
    generated_date = snapshot_generated_date(snapshot)
    if not generated_date:
        return {"name": "", "index": 0, "label": "not available", "source_date": ""}
    for idx, sprint in enumerate(sprints, start=1):
        start = parse_date(sprint.get("start"))
        end = parse_date(sprint.get("end"))
        if start and end and start <= generated_date <= end:
            return {
                "name": sprint["name"],
                "index": idx,
                "label": sprint["name"],
                "source_date": generated_date.isoformat(),
            }
    return {
        "name": "",
        "index": 0,
        "label": "not in release sprint window",
        "source_date": generated_date.isoformat(),
    }

def sprint_index(sprints: list[dict[str, str]], name: str | None) -> int | None:
    if not name or name == "TBD":
        return None
    for idx, sprint in enumerate(sprints, start=1):
        if sprint["name"] == name:
            return idx
    return None


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def date_to_sprint(sprints: list[dict[str, str]], value: str | None, issue: dict[str, Any] | None = None, ctx: dict[str, Any] | None = None) -> str:
    date_value = parse_date(value)
    if not date_value:
        return "TBD"
    for sprint in sprints:
        start = parse_date(sprint.get("start"))
        end = parse_date(sprint.get("end"))
        if start and end and start <= date_value <= end:
            return sprint["name"]
    if ctx and issue and agnostic_lane(issue):
        for window in agnostic_extension_windows(ctx):
            start = parse_date(window.get("start"))
            end = parse_date(window.get("end"))
            if start and end and start <= date_value <= end:
                return window["name"]
        return "Beyond extension window"
    if ctx:
        code_freeze = parse_date(str(ctx.get("meta", {}).get("code_freeze_date") or ""))
        if code_freeze and date_value > code_freeze:
            return "Beyond code freeze"
    return "out-of-cycle"


def normalize_sprint_name(value: str | None, version: str | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if version:
        match = re.search(rf"{re.escape(version)}-S\d+", raw)
        if match:
            return match.group(0)
    match = re.search(r"\d+(?:\.\d+)?-S\d+", raw)
    return match.group(0) if match else raw


def sprint_start_date(sprints: list[dict[str, str]], name: str | None) -> str:
    for sprint in sprints:
        if sprint["name"] == name:
            return sprint["start"]
    return ""


def sprint_end_date(sprints: list[dict[str, str]], name: str | None) -> str:
    for sprint in sprints:
        if sprint["name"] == name:
            return sprint["end"]
    return ""


def issue_start_sprint(issue: dict[str, Any], sprints: list[dict[str, str]], ctx: dict[str, Any] | None = None) -> str:
    return date_to_sprint(sprints, issue.get("start_after"), issue, ctx)


def issue_target_sprint(issue: dict[str, Any], sprints: list[dict[str, str]], ctx: dict[str, Any] | None = None) -> str:
    return date_to_sprint(sprints, issue.get("due_date"), issue, ctx)


def agnostic_lane(issue: dict[str, Any]) -> bool:
    return LANE_AGNOSTIC_LABEL in set(issue.get("labels") or [])


def lane_chip_html(issue: dict[str, Any]) -> str:
    if agnostic_lane(issue):
        return '<span class="lane-chip">Agnostic extension</span>'
    return ""


def lane_signal_html(epics: list[dict[str, Any]]) -> str:
    if any(agnostic_lane(epic) for epic in epics):
        return '<span class="lane-chip">Agnostic extension</span>'
    return ""


def plan_deviation(issue: dict[str, Any]) -> bool:
    return PLAN_DEVIATION_LABEL in set(issue.get("labels") or [])


def risk_value(issue: dict[str, Any]) -> str:
    return str(issue.get("risk") or "无")


def risk_set(issue: dict[str, Any]) -> bool:
    return risk_value(issue) in {"低", "高"}


def change_logged(issue: dict[str, Any]) -> bool:
    return bool(issue.get("roadmap_changes") or [])


def latest_change(issue: dict[str, Any]) -> dict[str, Any]:
    changes = issue.get("roadmap_changes") or []
    return changes[-1] if changes else {}


def plan_change_kind(change: dict[str, Any]) -> str:
    field = str(change.get("changed") or "").strip().lower()
    old_date = parse_date(str(change.get("from") or ""))
    new_date = parse_date(str(change.get("to") or ""))
    if field in {"due date", "duedate", "startafter", "start after"} and old_date and new_date:
        if new_date > old_date:
            return "Delayed"
        if new_date < old_date:
            return "Pulled in"
    return "Plan changed"


def change_notes_text(change: dict[str, Any]) -> str:
    notes = change.get("notes")
    if notes in (None, "", []):
        return ""
    return compact_text(notes, 220)


def change_reason_category_text(change: dict[str, Any]) -> str:
    return str(change.get("reason_category") or "").strip()


def change_schema_warning_text(change: dict[str, Any]) -> str:
    warnings = [str(item) for item in (change.get("schema_warnings") or []) if str(item).strip()]
    return "; ".join(warnings)


def plan_change_entries(epics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for epic in epics:
        key = epic.get("key") or ""
        has_deviation_label = plan_deviation(epic)
        for change in epic.get("roadmap_changes") or []:
            entries.append({
                "epic_key": key,
                "kind": plan_change_kind(change),
                "changed": str(change.get("changed") or "Plan"),
                "from": str(change.get("from") or ""),
                "to": str(change.get("to") or ""),
                "reason_category": change_reason_category_text(change),
                "reason": str(change.get("reason") or ""),
                "notes": change_notes_text(change),
                "schema_warning": change_schema_warning_text(change),
                "created": str(change.get("created") or ""),
                "author": str(change.get("author") or ""),
                "comment_id": str(change.get("comment_id") or ""),
                "missing_label": not has_deviation_label,
            })
    return sorted(entries, key=lambda entry: (entry.get("created") or "", entry.get("epic_key") or ""), reverse=True)


def plan_change_count(epics: list[dict[str, Any]]) -> int:
    return len(plan_change_entries(epics))


def plan_changed_epic_count(epics: list[dict[str, Any]]) -> int:
    return sum(1 for epic in epics if change_logged(epic))


def plan_change_summary(epics: list[dict[str, Any]]) -> str:
    entries = plan_change_entries(epics)
    if not entries:
        return ""
    kinds = [entry["kind"] for entry in entries]
    if "Delayed" in kinds:
        label = "Delayed"
    elif "Pulled in" in kinds:
        label = "Pulled in"
    else:
        label = "Plan changed"
    parts = [label, f"{len(entries)} change{'s' if len(entries) != 1 else ''}"]
    latest = entries[0]
    if latest.get("from") or latest.get("to"):
        parts.append(f"{latest.get('from') or '?'} -> {latest.get('to') or '?'}")
    if any(entry.get("missing_label") for entry in entries):
        parts.append("Missing deviation label")
    return " · ".join(parts)


def plan_change_markdown_lines(issue: dict[str, Any]) -> list[str]:
    lines = []
    for entry in plan_change_entries([issue]):
        transition = f"{entry['from']} -> {entry['to']}" if entry.get("from") or entry.get("to") else entry["changed"]
        reason = compact_text(entry.get("reason") or "", 180)
        detail = reason or compact_text(entry.get("notes") or "", 180)
        suffix = f": {detail}" if detail else ""
        missing = " · missing `roadmap:plan-deviation` label" if entry.get("missing_label") else ""
        warning = f" · schema cleanup: {entry['schema_warning']}" if entry.get("schema_warning") else ""
        lines.append(f"- {jira_md(entry['epic_key'])}: {entry['kind']} `{transition}`{suffix}{missing}{warning}")
    return lines


def plan_change_signal_html(epics: list[dict[str, Any]]) -> str:
    summary = plan_change_summary(epics)
    return f'<div class="plan-change-signal">{html_escape(summary)}</div>' if summary else ""


def plan_changes_html(epics: list[dict[str, Any]], limit: int = 3) -> str:
    entries = plan_change_entries(epics)
    if not entries:
        return ""
    rows = []
    for entry in entries[:limit]:
        transition = f'{html_escape(entry["from"] or "?")} -> {html_escape(entry["to"] or "?")}'
        missing = '<span class="change-missing-label">Missing deviation label</span>' if entry.get("missing_label") else ""
        schema_warning = f'<span class="change-missing-label">Legacy comment normalized</span>' if entry.get("schema_warning") else ""
        meta_parts = [part for part in [entry.get("created", "")[:10], entry.get("author", "")] if part]
        meta = f'<span class="change-meta">{html_escape(" · ".join(meta_parts))}</span>' if meta_parts else ""
        reason = compact_text(entry.get("reason") or "", 260)
        notes_text = compact_text(entry.get("notes") or "", 260)
        reason_line = html_escape(reason) if reason else ""
        notes_line = f'<div class="change-notes">{html_escape(notes_text)}</div>' if notes_text else ""
        if entry.get("reason_category"):
            reason_line = f'<b>{html_escape(entry["reason_category"])}</b>{": " + html_escape(reason) if reason else ""}'
        reason_html = f'<div class="change-reason">{reason_line}</div>' if reason_line else ""
        rows.append(
            f'<div class="plan-change-row"><div class="change-title">{jira_html(entry["epic_key"])} '
            f'<span class="change-kind">{html_escape(entry["kind"])}</span> '
            f'<span class="change-field">{html_escape(entry["changed"])} {transition}</span>{missing}{schema_warning}{meta}</div>'
            f'{reason_html}{notes_line}</div>'
        )
    more = f'<div class="change-more">+{len(entries) - limit} more changes</div>' if len(entries) > limit else ""
    return f'<section class="plan-changes"><h4>Plan Changes</h4>{"".join(rows)}{more}</section>'


def child_sprint_names(child: dict[str, Any], version: str) -> list[str]:
    names = []
    for sprint in child.get("sprints") or []:
        name = normalize_sprint_name(sprint, version)
        if name:
            names.append(name)
    return names


def child_latest_sprint_index(child: dict[str, Any], sprints: list[dict[str, str]], version: str) -> int | None:
    indexes = []
    for sprint in child_sprint_names(child, version):
        idx = sprint_index(sprints, sprint)
        if idx:
            indexes.append(idx)
    return max(indexes) if indexes else None


def execution_drift_children(epics: list[dict[str, Any]], children: list[dict[str, Any]], sprints: list[dict[str, str]], version: str, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    due_by_epic = {epic.get("key"): sprint_index(sprints, issue_target_sprint(epic, sprints, ctx)) for epic in epics if epic.get("key")}
    drifted: list[dict[str, Any]] = []
    for child in group_children(epics, children):
        if child_status_bucket(child) == "cancelled":
            continue
        due_idx = due_by_epic.get(child.get("parent_epic"))
        latest_idx = child_latest_sprint_index(child, sprints, version)
        if due_idx and latest_idx and latest_idx > due_idx:
            drifted.append(child)
    return drifted


def story_points_total(children: list[dict[str, Any]]) -> float:
    total = 0.0
    for child in children:
        if child_status_bucket(child) == "cancelled":
            continue
        value = child.get("story_points")
        if isinstance(value, (int, float)):
            total += float(value)
    return total


def clone_children(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [child for child in children if "clone" in str(child.get("summary") or "").lower()]


def assignee_summary(children: list[dict[str, Any]], limit: int = 4) -> str:
    counts: dict[str, int] = {}
    for child in children:
        if child_status_bucket(child) == "cancelled":
            continue
        assignee = str(child.get("assignee") or "未分配")
        counts[assignee] = counts.get(assignee, 0) + 1
    if not counts:
        return "未记录"
    parts = [f"{name}({count})" for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]
    if len(counts) > limit:
        parts.append(f"+{len(counts) - limit}")
    return ", ".join(parts)


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def issue_resources(issue: dict[str, Any]) -> str:
    if issue.get("assignee"):
        return str(issue["assignee"])
    return "未记录"


def issue_plan_text(issue: dict[str, Any]) -> str:
    change = latest_change(issue)
    parts = []
    if issue.get("risk"):
        parts.append(f"Risk: {risk_value(issue)}")
    if change:
        reason = change.get("reason") or change.get("notes") or ""
        parts.append(compact_text(f"Change: {reason}", 180))
    if issue.get("roadmap_plan"):
        legacy = issue_plan_summary(issue)
        if legacy and legacy != "No existing planning hint":
            parts.append(f"Existing planning hint: {legacy}")
    return " / ".join(parts) if parts else "No change note"


def issue_plan(issue: dict[str, Any]) -> dict[str, Any]:
    plan = issue.get("roadmap_studio_plan")
    if isinstance(plan, dict):
        return plan
    return extract_plan(issue.get("roadmap_plan") or "")


def plan_value(issue: dict[str, Any], key: str, default: str = "TBD") -> str:
    value = issue_plan(issue).get(key)
    if value is None or value == "":
        return default
    if isinstance(value, list):
        return "; ".join(str(item) for item in value) or default
    if isinstance(value, dict):
        parts = []
        for role, people in value.items():
            if isinstance(people, list):
                parts.append(f"{role}: {', '.join(str(person) for person in people)}")
        return "; ".join(parts) or default
    return str(value)


def has_plan(issue: dict[str, Any]) -> bool:
    return bool(issue.get("start_after") and issue.get("due_date"))


def issue_gap_text(issue: dict[str, Any], ctx: dict[str, Any] | None = None, sprints: list[dict[str, str]] | None = None) -> str:
    gaps = []
    if not issue.get("start_after"):
        gaps.append("Missing StartAfter")
    if not issue.get("due_date"):
        gaps.append("Missing Due Date")
    if issue.get("due_date") and ctx is not None:
        target = issue_target_sprint(issue, sprints or sprint_windows(ctx), ctx)
        if target == "Beyond code freeze":
            gaps.append(f"Due Date beyond code freeze; add `{LANE_AGNOSTIC_LABEL}` only if this Epic is fully Agnostic")
        elif target == "Beyond extension window":
            gaps.append("Due Date beyond Agnostic extension window")
        elif target == "out-of-cycle":
            gaps.append("Due Date outside configured release calendar")
    if plan_deviation(issue) and not change_logged(issue):
        gaps.append("Plan Deviation missing change comment")
    return "; ".join(gaps) if gaps else "信息完整"


def plan_gap_text(epics: list[dict[str, Any]], ctx: dict[str, Any] | None = None, sprints: list[dict[str, str]] | None = None) -> str:
    if not epics:
        return "缺 Epic"
    gaps = [f"{issue.get('key')}: {issue_gap_text(issue, ctx, sprints)}" for issue in epics if issue_gap_text(issue, ctx, sprints) != "信息完整"]
    return "; ".join(gaps) if gaps else "信息完整"


def issue_gap_html(issue: dict[str, Any], ctx: dict[str, Any] | None = None, sprints: list[dict[str, str]] | None = None) -> str:
    gap = issue_gap_text(issue, ctx, sprints)
    if gap == "信息完整":
        return ""
    key = issue.get("key") or ""
    prefix = jira_html(key) if key else "Unknown Epic"
    return f"{prefix}: {html_escape(gap)}"


def epics_gap_html(epics: list[dict[str, Any]], ctx: dict[str, Any] | None = None, sprints: list[dict[str, str]] | None = None) -> str:
    if not epics:
        return "缺 Epic"
    gaps = [issue_gap_html(issue, ctx, sprints) for issue in epics if issue_gap_text(issue, ctx, sprints) != "信息完整"]
    return "; ".join(gaps) if gaps else "信息完整"


def display_sub_team(team: str) -> str:
    return "未识别 sub-team" if team == "Unknown" else team


def status_bucket_for_issue(issue: dict[str, Any]) -> str:
    return normalize_status(issue.get("epic_status") or issue.get("status_name"))


def linked_keys(keys: list[str]) -> str:
    return ", ".join(jira_html(key) for key in keys if key) or "None"


def issue_child_summary(issue: dict[str, Any], children: list[dict[str, Any]]) -> str:
    return progress_summary(children_for_epic(children, issue.get("key") or ""))


def progress_numbers(children: list[dict[str, Any]]) -> tuple[int, int, int, int, int]:
    counts = child_counts(children)
    total = sum(counts.values())
    active = total - counts["cancelled"]
    return counts["done"], counts["in_progress"], counts["todo"], counts["cancelled"], active


def progress_percent(children: list[dict[str, Any]]) -> int | None:
    done, _, _, _, active = progress_numbers(children)
    if active <= 0:
        return None
    return round(done / active * 100)


def summarize_plan(epics: list[dict[str, Any]]) -> str:
    texts: list[str] = []
    for issue in epics:
        text = issue_plan_text(issue)
        if text != "缺排期说明" and text not in texts:
            texts.append(text)
    return " / ".join(texts) if texts else plan_gap_text(epics)


def collect_gap_actions(items: list[RoadmapItem], small: list[dict[str, Any]], profile: dict[str, Any], ctx: dict[str, Any] | None = None, sprints: list[dict[str, str]] | None = None) -> dict[str, list[str]]:
    actions: dict[str, list[str]] = {}
    for item in items:
        gap = plan_gap_text(item.epics, ctx, sprints)
        if gap != "信息完整":
            actions.setdefault(team_for_epics(item.epics, profile), []).append(
                f"{item.roadmap_id} {item.title}: {gap}"
            )
    for issue in small:
        gap = issue_gap_text(issue, ctx, sprints)
        if gap != "信息完整":
            actions.setdefault(sub_team_for_issue(issue, profile), []).append(
                f"{issue.get('key')} {issue.get('summary')}: {gap}"
            )
    return actions


def team_for_epics(epics: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for epic in epics:
        team = sub_team_for_issue(epic, profile)
        counts[team] = counts.get(team, 0) + 1
    if not counts:
        return "未分配 sub-team"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def first_plan_field(epics: list[dict[str, Any]], key: str, default: str = "TBD") -> str:
    for epic in epics:
        value = plan_value(epic, key, default="")
        if value:
            return value
    return default


def first_issue_date(epics: list[dict[str, Any]], key: str) -> str:
    values = [str(epic.get(key) or "") for epic in epics if epic.get(key)]
    if not values:
        return ""
    return sorted(values)[0] if key == "start_after" else sorted(values)[-1]


def date_plan_fields(epics: list[dict[str, Any]], sprints: list[dict[str, str]], ctx: dict[str, Any] | None = None) -> dict[str, str]:
    start_date = first_issue_date(epics, "start_after")
    due_date = first_issue_date(epics, "due_date")
    start_sprint = date_to_sprint(sprints, start_date, epics[0] if epics else None, ctx)
    target_issue = sorted([epic for epic in epics if epic.get("due_date")], key=lambda epic: str(epic.get("due_date") or ""))[-1] if any(epic.get("due_date") for epic in epics) else (epics[0] if epics else None)
    target_sprint = date_to_sprint(sprints, due_date, target_issue, ctx)
    changes = [latest_change(epic) for epic in epics if latest_change(epic)]
    reasons = []
    for change in changes:
        reason = change.get("reason") or change.get("notes") or ""
        text = compact_text(reason, 160)
        if text and text not in reasons:
            reasons.append(text)
    risks = []
    for epic in epics:
        if risk_set(epic):
            risks.append(f"{epic.get('key')}: {risk_value(epic)}")
    descriptions = [compact_text(epic.get("description"), 220) for epic in epics if epic.get("description")]
    return {
        "start_sprint": start_sprint,
        "target_sprint": target_sprint,
        "start_date": start_date or "TBD",
        "due_date": due_date or "TBD",
        "target_outcome": compact_text(" / ".join(descriptions), 320) or "Epic description needs delivery expectation",
        "resources": ", ".join(sorted({issue_resources(epic) for epic in epics if issue_resources(epic) != "未记录"})) or "未记录",
        "dependencies": dependency_summary(epics),
        "risks": "; ".join(dict.fromkeys(risks)) or "无",
        "notes": " / ".join(reasons) or "No change note",
        "last_confirmed": latest_change_date(epics),
        "lane": "Agnostic extension" if any(agnostic_lane(epic) for epic in epics) else "Core / Aligned",
    }


def latest_change_date(epics: list[dict[str, Any]]) -> str:
    dates = []
    for epic in epics:
        for change in epic.get("roadmap_changes") or []:
            if change.get("created"):
                dates.append(str(change["created"][:10]))
    return sorted(dates)[-1] if dates else "未记录"


def dependency_summary(epics: list[dict[str, Any]]) -> str:
    links = []
    for epic in epics:
        for link in epic.get("issue_links") or []:
            key = link.get("key") or ""
            if not key:
                continue
            relationship = link.get("relationship") or link.get("link_type") or "links"
            links.append(f"{epic.get('key')} {relationship} {key}")
    return "; ".join(dict.fromkeys(links)) or "未声明 Jira link 依赖"


def status_class_name(status: str) -> str:
    if status == "Done":
        return "status-done"
    if status == "In Progress":
        return "status-progress"
    return "status-todo"


def item_status(item: RoadmapItem) -> str:
    statuses = [normalize_status(issue.get("epic_status")) for issue in item.epics]
    if not statuses:
        return "No Epic"
    if all(status == "Done" for status in statuses):
        return "Done"
    if any(status == "In Progress" for status in statuses) or any(status == "Done" for status in statuses):
        return "In Progress"
    return "To Do"


def children_for_epic(children: list[dict[str, Any]], epic_key: str) -> list[dict[str, Any]]:
    return [child for child in children if child.get("parent_epic") == epic_key]


def jira_key_sort_value(key: str | None) -> tuple[str, int, str]:
    raw = str(key or "")
    match = re.match(r"([A-Z]+)-(\d+)", raw)
    if not match:
        return raw, 0, raw
    return match.group(1), int(match.group(2)), raw


def child_counts(children: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"done": 0, "in_progress": 0, "todo": 0, "cancelled": 0}
    for child in children:
        counts[child_status_bucket(child)] += 1
    return counts


def progress_summary(children: list[dict[str, Any]]) -> str:
    counts = child_counts(children)
    total = sum(counts.values())
    active = total - counts["cancelled"]
    if total == 0:
        return "no tasks tracked"
    return f"{counts['done']}/{active} done · {counts['in_progress']} in progress · {counts['todo']} todo · {counts['cancelled']} cancelled"


def active_unfinished_children(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [child for child in children if child_status_bucket(child) in {"todo", "in_progress"}]


def child_story_points_text(child: dict[str, Any]) -> str:
    points = child.get("story_points")
    if points is None or points == "":
        return "未估"
    if isinstance(points, float) and points.is_integer():
        return f"{int(points)}d"
    return f"{points}d"


def child_sprint_candidates(child: dict[str, Any], version: str) -> list[str]:
    raw_sprints = child.get("sprints") or []
    candidates: list[str] = []
    for sprint in raw_sprints:
        normalized = normalize_sprint_name(str(sprint), version)
        if normalized:
            candidates.append(normalized)
    return candidates


def child_sprint_text(child: dict[str, Any], version: str) -> str:
    raw_sprints = [str(sprint).strip() for sprint in (child.get("sprints") or []) if str(sprint).strip()]
    return ", ".join(raw_sprints) if raw_sprints else "未排 Sprint"


def child_sprint_sort_key(child: dict[str, Any], sprints: list[dict[str, str]], version: str) -> tuple[int, int, str, tuple[str, int, str]]:
    known_indexes = [idx for sprint in child_sprint_candidates(child, version) if (idx := sprint_index(sprints, sprint)) is not None]
    if known_indexes:
        return 0, min(known_indexes), "", jira_key_sort_value(child.get("key"))
    if child.get("sprints"):
        return 1, 0, child_sprint_text(child, version), jira_key_sort_value(child.get("key"))
    return 2, 0, "", jira_key_sort_value(child.get("key"))


def render_child_task_details(children: list[dict[str, Any]], sprints: list[dict[str, str]], version: str) -> str:
    tasks = sorted(active_unfinished_children(children), key=lambda child: child_sprint_sort_key(child, sprints, version))
    if not tasks:
        return ""
    rows = []
    for child in tasks:
        bucket = child_status_bucket(child)
        sprint_text = child_sprint_text(child, version)
        sprint_class = " task-sprint-missing" if not child.get("sprints") else ""
        rows.append(
            f'<div class="task-detail-row task-{bucket}">'
            f'<div class="task-detail-main">{jira_html(child.get("key") or "")} '
            f'<span class="task-type">{html_escape(child.get("issue_type") or "Issue")}</span> '
            f'<span class="task-summary" title="{html_escape(child.get("summary") or "")}">{html_escape(child.get("summary") or "")}</span></div>'
            f'<div class="task-detail-meta"><span>{html_escape(child.get("status_name") or "")}</span>'
            f'<span>{html_escape(child.get("assignee") or "未指派")}</span>'
            f'<span class="task-sprint{sprint_class}">{html_escape(sprint_text)}</span>'
            f'<span class="task-points">{html_escape(child_story_points_text(child))}</span></div></div>'
        )
    return f'<div class="task-detail-list">{"".join(rows)}</div>'


def render_bar(start: str | None, target: str | None, status: str, sprints: list[dict[str, str]]) -> str:
    start_idx = sprint_index(sprints, start) or 1
    target_idx = sprint_index(sprints, target) or start_idx
    if target_idx < start_idx:
        target_idx = start_idx
    css = "done" if status == "Done" else "progress" if status == "In Progress" else "todo"
    if not start or start == "TBD" or not target or target == "TBD":
        return f'<div class="bar unscheduled">{html_escape(start or "TBD")} -> {html_escape(target or "TBD")}</div>'
    return f'<div class="bar {css}" style="grid-column:{start_idx}/{target_idx + 1}">{html_escape(start)} -> {html_escape(target)}</div>'


def render_task_card(title: str, subtitle: str, epics: list[dict[str, Any]], status: str, sprints: list[dict[str, str]], children: list[dict[str, Any]]) -> str:
    plan = date_plan_fields(epics, sprints)
    start = plan["start_sprint"]
    target = plan["target_sprint"]
    epic_links = ", ".join(jira_html(issue.get("key") or "") for issue in epics) or "No Epic"
    resources = ", ".join(sorted({issue_resources(issue) for issue in epics if issue_resources(issue)})) or "未记录"
    text = " / ".join(issue_plan_text(issue) for issue in epics if issue_plan_text(issue) != "No change note") or plan_gap_text(epics, ctx, sprints)
    gap = plan_gap_text(epics, ctx, sprints)
    gap_class = "ok" if gap == "信息完整" else "warn"
    return f"""
<article class="task-card {gap_class}">
  <div class="task-main">
    <h3>{html_escape(title)}</h3>
    <div class="subtitle">{html_escape(subtitle)}</div>
    <div class="chips"><span>Jira: {epic_links}</span><span>Owner: {html_escape(resources)}</span><span>Start: {html_escape(plan['start_date'])} / {html_escape(start)}</span><span>Target: {html_escape(plan['due_date'])} / {html_escape(target)}</span><span class="pill {status_class_name(status)}">{html_escape(status)}</span><span class="gap {gap_class}">{html_escape(gap)}</span></div>
    <p>{html_escape(text)}</p>
    <p class="muted">Tasks: {html_escape(progress_summary(children))}</p>
  </div>
  <div class="timeline">{render_bar(start, target, status, sprints)}</div>
</article>"""


def compact_text(value: Any, limit: int = 220) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value if item)
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            if isinstance(val, list):
                parts.append(f"{key}: {', '.join(str(item) for item in val)}")
            elif val:
                parts.append(f"{key}: {val}")
        value = "; ".join(parts)
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(raw) > limit:
        return raw[: limit - 1].rstrip() + "..."
    return raw


def issue_plan_summary(issue: dict[str, Any]) -> str:
    plan = issue_plan(issue)
    for key in ("target_outcome", "notes", "risks", "dependencies"):
        value = plan.get(key)
        if value:
            return compact_text(value)
    return "No existing planning hint"


def epics_plan_summary(epics: list[dict[str, Any]]) -> str:
    summaries = []
    for epic in epics:
        summary = issue_plan_summary(epic)
        if summary and summary not in summaries:
            summaries.append(summary)
    return compact_text(" / ".join(summaries), 280) if summaries else "缺 Epic"


def progress_ratio(children: list[dict[str, Any]]) -> tuple[int, int]:
    counts = child_counts(children)
    active = counts["done"] + counts["in_progress"] + counts["todo"]
    return counts["done"], active


def pct(done: int, total: int) -> int:
    return round((done / total) * 100) if total else 0


def file_link_html(path: Path, label: str) -> str:
    try:
        href = path.resolve().as_uri()
    except ValueError:
        href = str(path)
    return f'<a href="{html_escape(href)}">{html_escape(label)}</a>'


def status_color(status: str) -> str:
    normalized = normalize_status(status)
    if normalized == "Done":
        return "#10b981"
    if normalized == "In Progress":
        return "#3b82f6"
    return "#9ca3af"


def progress_bar_html(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    if total <= 0:
        return '<div class="progress-bar empty"><span style="width:100%;background:#e5e7eb" title="No tasks"></span></div>'
    colors = {"done": "#10b981", "in_progress": "#3b82f6", "todo": "#9ca3af", "cancelled": "#d1d5db"}
    labels = {"done": "Done", "in_progress": "In Progress", "todo": "Todo", "cancelled": "Cancelled"}
    parts = []
    for key in ("done", "in_progress", "todo", "cancelled"):
        value = counts.get(key, 0)
        if value:
            width = value / total * 100
            parts.append(f'<span style="width:{width:.2f}%;background:{colors[key]}" title="{labels[key]}: {value}"></span>')
    return f'<div class="progress-bar">{"".join(parts)}</div>'


def group_children(epics: list[dict[str, Any]], children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    epic_keys = {epic.get("key") for epic in epics if epic.get("key")}
    return [child for child in children if child.get("parent_epic") in epic_keys]


def group_progress(epics: list[dict[str, Any]], children: list[dict[str, Any]]) -> dict[str, Any]:
    relevant = group_children(epics, children)
    counts = child_counts(relevant)
    active = counts["done"] + counts["in_progress"] + counts["todo"]
    if active:
        percent = round(counts["done"] / active * 100)
    elif epics and all(normalize_status(epic.get("epic_status")) == "Done" for epic in epics):
        percent = 100
    else:
        percent = 0
    return {"children": relevant, "counts": counts, "active": active, "percent": percent}


def group_retro_signals(epics: list[dict[str, Any]], children: list[dict[str, Any]], sprints: list[dict[str, str]], version: str) -> dict[str, Any]:
    relevant = group_children(epics, children)
    drifted = execution_drift_children(epics, children, sprints, version)
    changes = [change for epic in epics for change in (epic.get("roadmap_changes") or [])]
    reason_counts: dict[str, int] = {}
    for change in changes:
        category = change_reason_category_text(change)
        if not category:
            continue
        reason_counts[category] = reason_counts.get(category, 0) + 1
    return {
        "story_points": story_points_total(relevant),
        "assignees": assignee_summary(relevant),
        "clones": len(clone_children(relevant)),
        "drifted": len(drifted),
        "changes": len(changes),
        "reason_counts": reason_counts,
    }


def retro_signal_text(signals: dict[str, Any]) -> str:
    parts = []
    if signals.get("story_points"):
        parts.append(f"{signals['story_points']:g} pts")
    if signals.get("assignees") and signals.get("assignees") != "未记录":
        parts.append(f"owners: {signals['assignees']}")
    if signals.get("clones"):
        parts.append(f"{signals['clones']} clone")
    if signals.get("drifted"):
        parts.append(f"{signals['drifted']} drift")
    if signals.get("changes"):
        categories = ", ".join(f"{k}:{v}" for k, v in sorted((signals.get("reason_counts") or {}).items()))
        parts.append(f"{signals['changes']} change ({categories})")
    return " · ".join(parts) if parts else "No retro signals"


def group_status(epics: list[dict[str, Any]], children: list[dict[str, Any]]) -> str:
    if not epics:
        return "No Epic"
    statuses = [normalize_status(epic.get("epic_status") or epic.get("status_name")) for epic in epics]
    if all(status == "Done" for status in statuses):
        return "Done"
    if any(status in {"Done", "In Progress"} for status in statuses):
        return "In Progress"
    progress = group_progress(epics, children)
    if progress["counts"]["done"] or progress["counts"]["in_progress"]:
        return "In Progress"
    return "To Do"


def first_non_tbd(values: list[str], default: str = "TBD") -> str:
    for value in values:
        if value and value != "TBD":
            return value
    return default


def joined_plan_values(epics: list[dict[str, Any]], key: str, limit: int = 260) -> str:
    values = []
    for epic in epics:
        value = plan_value(epic, key, default="")
        if value and value not in values:
            values.append(value)
    return compact_text(" / ".join(values), limit)


def sprint_plan_fields(epics: list[dict[str, Any]], sprints: list[dict[str, str]], ctx: dict[str, Any] | None = None) -> dict[str, str]:
    return date_plan_fields(epics, sprints, ctx)


def render_sprint_plan_strip(start: str, target: str, status: str, sprints: list[dict[str, str]]) -> str:
    if not sprints:
        return '<div class="plan-strip empty">No sprint calendar</div>'
    start_idx = sprint_index(sprints, start)
    target_idx = sprint_index(sprints, target)
    cells = []
    for idx, sprint in enumerate(sprints, start=1):
        classes = ["plan-cell"]
        if start_idx and target_idx and start_idx <= idx <= target_idx:
            classes.append("planned")
            classes.append("done" if status == "Done" else "progress" if status == "In Progress" else "todo")
        if start_idx == idx:
            classes.append("start")
        if target_idx == idx:
            classes.append("target")
        title = f'{sprint["start"]} ~ {sprint["end"]}'
        label = sprint["name"].split("-S")[-1]
        cells.append(f'<div class="{" ".join(classes)}" title="{html_escape(title)}"><span>{html_escape(label)}</span></div>')
    if not start_idx or not target_idx:
        if target.endswith("extension window"):
            gap_text = f"Target in {target}"
        elif target == "Beyond code freeze":
            gap_text = "Target beyond code freeze"
        elif target == "Beyond extension window":
            gap_text = "Target beyond Agnostic extension window"
        else:
            gap_text = "Needs StartAfter / Due Date"
        cells.append(f'<div class="plan-gap">{html_escape(gap_text)}</div>')
    return f'<div class="plan-strip">{"".join(cells)}</div>'


def roadmap_label_for_issue(issue: dict[str, Any], version: str) -> str:
    prefix = f"roadmap:{version}:"
    for label in issue.get("labels") or []:
        if label.startswith(prefix) and label != small_features_label(version):
            return label_slug(label, version)
    return ""


def roadmap_group_slug(item: RoadmapItem, version: str) -> str:
    if item.epics:
        label = roadmap_label_for_issue(item.epics[0], version)
        if label:
            return label
    return label_slug(item.expected_label, version)


def add_group_gap_by_team(group: dict[str, Any], profile: dict[str, Any], gaps_by_team: dict[str, list[str]], ctx: dict[str, Any] | None = None, sprints: list[dict[str, str]] | None = None) -> None:
    if group["gap"] == "信息完整":
        return
    if group["kind"] == "small":
        for epic in group["epics"]:
            gap = issue_gap_text(epic, ctx, sprints)
            if gap != "信息完整":
                team = sub_team_for_issue(epic, profile)
                gaps_by_team.setdefault(team, []).append(f"{issue_gap_html(epic, ctx, sprints)} {html_escape(epic.get('summary') or '')}")
        return
    gaps_by_team.setdefault(group["team"], []).append(f"{html_escape(group['title'])}: {epics_gap_html(group['epics'], ctx, sprints) if group['epics'] else html_escape(group['gap'])}")


def render_gantt_html(ctx: dict[str, Any], snapshot: dict[str, Any], sub_team: str | None = None) -> str:
    version = ctx["version"]
    profile = ctx["profile"]
    items = parse_roadmap_items(ctx["roadmap_path"], version) if ctx["roadmap_path"].exists() else []
    issues = list(snapshot.get("issues") or [])
    children = list(snapshot.get("child_issues") or [])
    small, unclassified = attach_epics(items, issues, version, own_project=ctx.get("jira_project"))
    if sub_team:
        items = [item for item in items if team_for_epics(item.epics, profile) == sub_team or not item.epics]
        small = [issue for issue in small if sub_team_for_issue(issue, profile) == sub_team]
        unclassified = [issue for issue in unclassified if sub_team_for_issue(issue, profile) == sub_team]

    sprints = sprint_windows(ctx)
    current_sprint_info = current_sprint_from_snapshot(ctx, snapshot)
    current_sprint = str(current_sprint_info.get("name") or "")
    current_sprint_label = str(current_sprint_info.get("label") or "not available")
    groups: list[dict[str, Any]] = []
    small_group: dict[str, Any] | None = None
    for item in items:
        team = team_for_epics(item.epics, profile)
        status = item_status(item)
        progress = group_progress(item.epics, children)
        retro = group_retro_signals(item.epics, children, sprints, version)
        groups.append({
            "kind": "formal",
            "slug": roadmap_group_slug(item, version),
            "title": f"{item.roadmap_id} {item.title}",
            "chip": roadmap_group_slug(item, version),
            "domain": item.domain,
            "capability": item.capability,
            "team": team,
            "epics": item.epics,
            "status": status,
            "progress": progress,
            "retro": retro,
            "gap": plan_gap_text(item.epics, ctx, sprints),
            "plan": sprint_plan_fields(item.epics, sprints, ctx),
        })
    if small:
        small_group = {
            "kind": "small",
            "slug": "small-features",
            "title": "Small Features",
            "chip": "small-features",
            "domain": "Non-roadmap planned work",
            "capability": "Small features inside release scope",
            "team": sub_team or "跨子团队",
            "epics": small,
            "status": group_status(small, children),
            "progress": group_progress(small, children),
            "retro": group_retro_signals(small, children, sprints, version),
            "gap": "; ".join(f"{issue.get('key')}: {issue_gap_text(issue, ctx, sprints)}" for issue in small if issue_gap_text(issue, ctx, sprints) != "信息完整") or "信息完整",
            "plan": sprint_plan_fields(small, sprints, ctx),
        }
    if unclassified:
        groups.append({
            "kind": "unclassified",
            "slug": "unclassified-roadmap-work",
            "title": "Unclassified Roadmap Work",
            "chip": "unclassified",
            "domain": "Needs classification",
            "capability": "Add roadmap item label, small-features label, or changelog decision",
            "team": "Unknown",
            "epics": unclassified,
            "status": group_status(unclassified, children),
            "progress": group_progress(unclassified, children),
            "retro": group_retro_signals(unclassified, children, sprints, version),
            "gap": "Version roadmap Epic is neither formal roadmap item nor small-features",
            "plan": sprint_plan_fields(unclassified, sprints, ctx),
        })

    formal_groups = [group for group in groups if group["kind"] == "formal"]
    done_groups = sum(1 for group in formal_groups if group["status"] == "Done")
    in_progress_groups = sum(1 for group in formal_groups if group["status"] == "In Progress")
    todo_groups = sum(1 for group in formal_groups if group["status"] in {"To Do", "No Epic"})
    all_groups = groups + ([small_group] if small_group else [])
    all_epics = [epic for group in all_groups for epic in group["epics"]]
    done_epics = sum(1 for epic in all_epics if normalize_status(epic.get("status_name") or epic.get("epic_status")) == "Done")
    in_progress_epics = sum(1 for epic in all_epics if normalize_status(epic.get("status_name") or epic.get("epic_status")) == "In Progress")
    todo_epics = len(all_epics) - done_epics - in_progress_epics
    child_total_counts = child_counts(children)
    child_active = child_total_counts["done"] + child_total_counts["in_progress"] + child_total_counts["todo"]
    child_done_pct = pct(child_total_counts["done"], child_active)
    info_gap_groups = [group for group in all_groups if group["gap"] != "信息完整"]
    changed_groups = [group for group in all_groups if plan_change_count(group["epics"])]
    gaps_by_team: dict[str, list[str]] = {}
    for group in info_gap_groups:
        add_group_gap_by_team(group, profile, gaps_by_team, ctx, sprints)
    changes_by_team: dict[str, int] = {}
    for group in changed_groups:
        changes_by_team[group["team"]] = changes_by_team.get(group["team"], 0) + plan_change_count(group["epics"])

    today = dt.datetime.now().astimezone().date()
    code_freeze_raw = str(ctx["meta"].get("code_freeze_date") or ctx["meta"].get("release_target_date") or "")
    try:
        code_freeze = dt.date.fromisoformat(code_freeze_raw)
        days_to_freeze = (code_freeze - today).days
    except ValueError:
        days_to_freeze = None
    current_idx = int(current_sprint_info.get("index") or 0)
    remaining_sprints = max(len(sprints) - current_idx + 1, 0) if current_idx else 0

    def kpi_bar(done: int, progress: int, todo: int, extra: int = 0) -> str:
        total = done + progress + todo + extra
        if total <= 0:
            return '<div class="kpi-bar"><span style="width:100%;background:#e5e7eb"></span></div>'
        parts = [(done, "#10b981", "Done"), (progress, "#3b82f6", "In Progress"), (todo, "#9ca3af", "To Do"), (extra, "#d1d5db", "Other")]
        return '<div class="kpi-bar">' + "".join(
            f'<span style="width:{value / total * 100:.2f}%;background:{color}" title="{label}: {value}"></span>'
            for value, color, label in parts if value
        ) + "</div>"

    sprint_header = []
    for sprint in sprints:
        classes = ["sprint"]
        sprint_idx = sprint_index(sprints, sprint["name"]) or 0
        if sprint["name"] == current_sprint:
            classes.append("sp-current")
        elif current_idx and sprint_idx < current_idx:
            classes.append("sp-past")
        else:
            classes.append("sp-feature")
        now_dot = '<span class="now-dot"></span>' if sprint["name"] == current_sprint else ""
        sprint_header.append(
            f'<div class="{" ".join(classes)}" title="{html_escape(sprint["start"])} ~ {html_escape(sprint["end"])}">'
            f'<div class="sp-label">{html_escape(sprint["name"])}</div><div class="sp-date">{html_escape(sprint["start"])}<br>{html_escape(sprint["end"])}</div>{now_dot}</div>'
        )
    timeline_meta = ""
    if sprints:
        freeze_suffix = f" · {days_to_freeze}d" if days_to_freeze is not None else ""
        timeline_meta = (
            f'<div>Cycle Start: <strong>{html_escape(sprints[0]["start"])}</strong></div>'
            f'<div>Code Freeze: <strong>{html_escape(code_freeze_raw or "not set")}</strong>{html_escape(freeze_suffix)}</div>'
            f'<div>Current Sprint: <strong>{html_escape(current_sprint_label)}</strong> · {remaining_sprints} sprints remaining including current</div>'
        )

    health_rows = []
    configured_teams = {str(team.get("name")) for team in profile.get("sub_teams") or [] if team.get("name")}
    team_small_counts: dict[str, int] = {}
    for epic in small:
        team_small_counts[sub_team_for_issue(epic, profile)] = team_small_counts.get(sub_team_for_issue(epic, profile), 0) + 1
    missing_sub_team_epics = [epic for epic in all_epics if sub_team_for_issue(epic, profile) == "Unknown" and not is_external_issue(epic, profile)]
    for team in sorted(configured_teams):
        team_groups = [group for group in groups if group["team"] == team]
        team_gaps = gaps_by_team.get(team, [])
        team_changes = changes_by_team.get(team, 0)
        small_count = team_small_counts.get(team, 0)
        health_rows.append(
            f'<div class="health-row {"risk" if team_gaps else "ok"}"><div><b>{html_escape(team)}</b><span>{len(team_groups)} roadmap groups · {small_count} small features · {len(team_gaps)} plan gaps · {team_changes} plan changes</span></div>'
            f'<div class="health-action">{"补 Jira StartAfter/Due Date/Risk 或变更说明" if team_gaps else "Plan fields available"}</div></div>'
        )
    for team in sorted(set(gaps_by_team) - configured_teams):
        health_rows.append(f'<div class="health-row risk"><div><b>{html_escape(team)}</b><span>{len(gaps_by_team[team])} plan gaps</span></div><div class="health-action">通过 skill 补 sub-team label 或 Jira plan fields</div></div>')
    if missing_sub_team_epics:
        health_rows.append(f'<div class="health-row risk"><div><b>未分配 sub-team</b><span>{len(missing_sub_team_epics)} epics need sub-team label</span></div><div class="health-action">通过 skill 补 Jira sub-team label</div></div>')

    def append_all_epic_row(group_name: str, epic: dict[str, Any]) -> None:
        epic_children = children_for_epic(children, epic.get("key") or "")
        counts = child_counts(epic_children)
        active = counts["done"] + counts["in_progress"] + counts["todo"]
        epic_status_text = epic.get("status_name") or epic.get("epic_status") or "To Do"
        epic_status = normalize_status(epic_status_text)
        cancelled = f" (+{counts['cancelled']} cancelled)" if counts["cancelled"] else ""
        all_epic_rows.append(
            f'<tr><td>{html_escape(group_name)}</td><td>{jira_html(epic.get("key") or "")}</td><td class="cell-summary" title="{html_escape(epic.get("summary") or "")}">{html_escape(epic.get("summary") or "")}</td>'
            f'<td><span class="status-pill" style="background:{status_color(epic_status)}20;color:{status_color(epic_status)}">{html_escape(epic_status_text)}</span></td>'
            f'<td>{html_escape(sub_team_for_issue(epic, profile))}</td><td class="num">{counts["done"]}/{active}{cancelled}</td>'
            f'<td>{html_escape(epic.get("start_after") or "TBD")}</td><td>{html_escape(epic.get("due_date") or "TBD")}</td></tr>'
        )

    chip_html = []
    card_html = []
    all_epic_rows = []
    for group in groups:
        progress = group["progress"]
        status = group["status"]
        chip_class = "rm-chip-complete" if status == "Done" else "rm-chip-in-progress" if status == "In Progress" else "rm-chip-gray"
        gap_badge = '<span class="chip-gap">Needs plan fields</span>' if group["gap"] != "信息完整" else ""
        change_badge = f'<span class="chip-change">{plan_change_count(group["epics"])} changes</span>' if plan_change_count(group["epics"]) else ""
        group_gap_html = epics_gap_html(group["epics"], ctx, sprints) if group["gap"] != "信息完整" else "Plan available"
        group_change_signal = plan_change_signal_html(group["epics"])
        group_lane_signal = lane_signal_html(group["epics"])
        group_changes_html = plan_changes_html(group["epics"])
        chip_html.append(
            f'<a class="rm-chip {chip_class}" data-rm="{html_escape(group["slug"])}" href="#rm-card-{html_escape(group["slug"])}">'
            f'<div class="chip-name">{html_escape(group["chip"])}</div><div class="chip-stats">{progress["percent"]}% · {progress["counts"]["done"]}/{progress["active"] or 0}{gap_badge}{change_badge}</div></a>'
        )
        plan = group["plan"]
        plan_strip = render_sprint_plan_strip(plan["start_sprint"], plan["target_sprint"], status, sprints)

        # Group epics by owning team so cross-team work shows up as its own block
        # rather than a flat mix. Within each team-group, sort by issue key.
        epics_by_team: dict[str, list[dict[str, Any]]] = {}
        for epic in group["epics"]:
            team_key = sub_team_for_issue(epic, profile)
            epics_by_team.setdefault(team_key, []).append(epic)

        configured_sub_team_order = [str(t.get("name")) for t in (profile.get("sub_teams") or []) if t.get("name")]
        external_team_order = [item["team"] for item in external_jira_projects(profile)]

        def _team_sort_key(team_name: str) -> tuple[int, int, str]:
            if team_name in configured_sub_team_order:
                return (0, configured_sub_team_order.index(team_name), team_name)
            if team_name in external_team_order:
                return (1, external_team_order.index(team_name), team_name)
            return (2, 0, team_name)

        team_blocks: list[str] = []
        sorted_team_names = sorted(epics_by_team.keys(), key=_team_sort_key)
        # If everything in this card belongs to a single own-team sub-team,
        # the wrapper just adds noise. Fall back to flat epic-blocks.
        single_own_team = (
            len(sorted_team_names) == 1
            and sorted_team_names[0] not in external_team_order
        )

        for team_name in sorted_team_names:
            team_epics_sorted = sorted(epics_by_team[team_name], key=lambda e: e.get("key") or "")
            is_external_team = team_name in external_team_order
            team_label_text = "跨团队" if is_external_team else "本团队"
            team_display_name = display_sub_team(team_name) if not is_external_team else team_name
            team_class = "team-group cross-team" if is_external_team else "team-group own-team"

            epic_blocks_html = []
            for epic in team_epics_sorted:
                epic_children = children_for_epic(children, epic.get("key") or "")
                counts = child_counts(epic_children)
                active = counts["done"] + counts["in_progress"] + counts["todo"]
                epic_status_text = epic.get("status_name") or epic.get("epic_status") or "To Do"
                epic_status = normalize_status(epic_status_text)
                child_text = f'<strong>{counts["done"]}</strong>/{active} done' if active else '<span class="muted">no tasks</span>'
                if counts["in_progress"] or counts["todo"] or counts["cancelled"]:
                    child_text += f'<span class="muted"> · {counts["in_progress"]} in-progress · {counts["todo"]} todo · {counts["cancelled"]} cancelled</span>'
                task_details = render_child_task_details(epic_children, sprints, version)
                epic_blocks_html.append(
                    f'<div class="epic-block"><div class="epic-row"><div class="epic-meta">{jira_html(epic.get("key") or "")}'
                    f'<span class="status-pill" style="background:{status_color(epic_status)}20;color:{status_color(epic_status)}">{html_escape(epic_status_text)}</span>'
                    f'<span class="epic-summary" title="{html_escape(epic.get("summary") or "")}">{html_escape(epic.get("summary") or "")}</span></div>'
                    f'<div class="epic-children">{child_text}{progress_bar_html(counts)}</div></div>{task_details}</div>'
                )
                append_all_epic_row(group["chip"], epic)

            if single_own_team:
                team_blocks.extend(epic_blocks_html)
                continue

            count_label = f'{len(team_epics_sorted)} epic{"s" if len(team_epics_sorted) != 1 else ""}'
            team_blocks.append(
                f'<div class="{team_class}" data-team="{html_escape(team_name)}">'
                f'<div class="team-group-head">'
                f'<span class="team-group-pill team-group-pill-{"cross" if is_external_team else "own"}">{html_escape(team_label_text)}</span>'
                f'<span class="team-group-name">{html_escape(team_display_name)}</span>'
                f'<span class="team-group-count">{count_label}</span>'
                f'</div>'
                f'{"".join(epic_blocks_html)}'
                f'</div>'
            )
        epic_rows_html = "".join(team_blocks) or '<div class="empty-state">No matching Epic. Add roadmap label or create Epic.</div>'
        card_html.append(
            f'<section class="rm-card" id="rm-card-{html_escape(group["slug"])}" data-rm="{html_escape(group["slug"])}" hidden>'
            f'<header class="rm-head"><div><h3>{html_escape(group["title"])}</h3><div class="rm-subtitle">{html_escape(group["domain"])} · {html_escape(group["capability"])} · {html_escape(group["team"])}</div></div><span class="rm-pct">{progress["percent"]}%</span></header>'
            f'<div class="rm-summary"><strong>{progress["counts"]["done"]}</strong> / {progress["active"] or 0} done · {len(group["epics"])} epics · {len(progress["children"])} tasks total</div>{progress_bar_html(progress["counts"])}'
            f'<div class="rm-summary muted">Retro signals: {html_escape(retro_signal_text(group.get("retro") or {}))}</div>'
            f'<div class="sprint-plan {"needs-plan" if group["gap"] != "信息完整" else ""}"><div class="plan-head"><b>Sprint Plan</b><span>{group_gap_html}</span></div>{plan_strip}'
            f'<div class="plan-grid"><div><span>Start</span><b>{html_escape(plan["start_date"])} / {html_escape(plan["start_sprint"])}</b></div><div><span>Target</span><b>{html_escape(plan["due_date"])} / {html_escape(plan["target_sprint"])}</b></div><div><span>Lane</span><b>{html_escape(plan["lane"])}</b></div><div><span>Last Change</span><b>{html_escape(plan["last_confirmed"])}</b></div></div>'
            f'{group_lane_signal}{group_change_signal}<div class="plan-detail"><p><b>Assignees:</b> {html_escape(plan["resources"])}</p><p><b>Target outcome:</b> {html_escape(plan["target_outcome"])}</p><p><b>Dependencies:</b> {html_escape(plan["dependencies"])}</p><p><b>Risks:</b> {html_escape(plan["risks"])}</p><p><b>Notes:</b> {html_escape(plan["notes"])}</p></div>{group_changes_html}</div>'
            f'<div class="epics">{epic_rows_html}</div></section>'
        )

    # Bucket small features:
    #   themed   = Epic summary matches a configured initiative (KubeOS / K8s
    #              1.35 / New Web Console / ...). 跨团队 status becomes a per-
    #              Epic badge inside the themed card — it is NOT a precondition
    #              for grouping. A New-Web-Console initiative therefore shows
    #              both own-team and cross-team Epics side by side.
    #   unthemed = everything else. These flow into the flat Small Features
    #              list, where cross-team Epics still carry a 跨团队 badge.
    themed_small: list[dict[str, Any]] = []
    unthemed_small: list[dict[str, Any]] = []
    epic_themed_slug: dict[str, tuple[str, str]] = {}
    for epic in small:
        match = detect_themed_initiative(epic.get("summary") or "")
        if match is not None:
            themed_small.append(epic)
            epic_themed_slug[epic.get("key") or ""] = match
        else:
            unthemed_small.append(epic)

    # ----- Themed Features (was Cross-Team Features) -----
    themed_features_html = ""
    if themed_small:
        external_team_order_local = [item["team"] for item in external_jira_projects(profile)]
        configured_sub_team_order_local = [str(t.get("name")) for t in (profile.get("sub_teams") or []) if t.get("name")]

        def _cross_team_sort_key(team_name: str) -> tuple[int, int, str]:
            if team_name in configured_sub_team_order_local:
                return (0, configured_sub_team_order_local.index(team_name), team_name)
            if team_name in external_team_order_local:
                return (1, external_team_order_local.index(team_name), team_name)
            return (2, 0, team_name)

        # Group themed Epics by initiative
        by_initiative: dict[str, dict[str, Any]] = {}
        for epic in themed_small:
            slug, name = epic_themed_slug[epic.get("key") or ""]
            entry = by_initiative.setdefault(slug, {"slug": slug, "name": name, "epics": []})
            entry["epics"].append(epic)

        initiative_order = [s for s, _, _ in THEMED_FEATURE_INITIATIVES]
        initiative_cards = []
        for slug in initiative_order:
            if slug not in by_initiative:
                continue
            entry = by_initiative[slug]
            init_epics = entry["epics"]
            init_children = [
                child for epic in init_epics
                for child in children_for_epic(children, epic.get("key") or "")
            ]
            init_counts = child_counts(init_children)
            init_active = init_counts["done"] + init_counts["in_progress"] + init_counts["todo"]
            teams_in_initiative = sorted({sub_team_for_issue(e, profile) for e in init_epics}, key=_cross_team_sort_key)
            cross_team_count_in_init = sum(1 for e in init_epics if is_cross_team_issue(e))

            epic_rows_html = []
            for epic in sorted(init_epics, key=lambda e: (_cross_team_sort_key(sub_team_for_issue(e, profile)), e.get("key") or "")):
                team_of_epic = sub_team_for_issue(epic, profile)
                is_external = team_of_epic in external_team_order_local
                pill_class = "team-group-pill-cross" if is_external else "team-group-pill-own"
                epic_children = children_for_epic(children, epic.get("key") or "")
                counts = child_counts(epic_children)
                active = counts["done"] + counts["in_progress"] + counts["todo"]
                epic_status_text = epic.get("status_name") or epic.get("epic_status") or "To Do"
                epic_status = normalize_status(epic_status_text)
                child_text = f'<strong>{counts["done"]}</strong>/{active} done' if active else '<span class="muted">no tasks</span>'
                if counts["in_progress"] or counts["todo"] or counts["cancelled"]:
                    child_text += f'<span class="muted"> · {counts["in_progress"]} ip · {counts["todo"]} todo · {counts["cancelled"]} cancel</span>'
                team_display = display_sub_team(team_of_epic) if not is_external else team_of_epic
                cross_badge = (
                    f'<span class="cross-team-badge" title="带 {html_escape(CROSS_TEAM_LABEL)} 标签 — 跨团队协作">跨团队</span>'
                    if is_cross_team_issue(epic) else ""
                )
                epic_rows_html.append(
                    f'<div class="initiative-epic"><div class="epic-row"><div class="epic-meta">'
                    f'{jira_html(epic.get("key") or "")}'
                    f'<span class="status-pill" style="background:{status_color(epic_status)}20;color:{status_color(epic_status)}">{html_escape(epic_status_text)}</span>'
                    f'<span class="team-group-pill {pill_class}">{html_escape(team_display)}</span>'
                    f'{cross_badge}'
                    f'<span class="epic-summary" title="{html_escape(epic.get("summary") or "")}">{html_escape(epic.get("summary") or "")}</span>'
                    f'</div><div class="epic-children">{child_text}{progress_bar_html(counts)}</div></div></div>'
                )
                append_all_epic_row(f"Themed / {entry['name']}", epic)

            init_pct = pct(init_counts["done"], init_active) if init_active else 0
            teams_summary = " · ".join(
                f'<span class="initiative-team">{html_escape(display_sub_team(t) if t not in external_team_order_local else t)}</span>'
                for t in teams_in_initiative
            )
            cross_summary = (
                f' · <span class="initiative-cross-count">含 {cross_team_count_in_init} 个跨团队 Epic</span>'
                if cross_team_count_in_init else ""
            )
            initiative_cards.append(
                f'<section class="initiative-card" data-initiative="{html_escape(slug)}">'
                f'<header class="initiative-head">'
                f'<div><h3>{html_escape(entry["name"])}</h3>'
                f'<div class="initiative-subtitle">{len(init_epics)} epics · {len(teams_in_initiative)} teams · {teams_summary}{cross_summary}</div></div>'
                f'<div class="initiative-stats"><b>{init_pct}%</b><span>{init_counts["done"]}/{init_active} tasks done</span></div>'
                f'</header>{progress_bar_html(init_counts)}'
                f'<div class="initiative-epics">{"".join(epic_rows_html)}</div>'
                f'</section>'
            )

        total_cross_in_themed = sum(1 for e in themed_small if is_cross_team_issue(e))
        themed_features_html = (
            f'<section id="themed-features" class="themed-features-section">'
            f'<header class="section-head"><div><h2>Themed Features '
            f'<span class="count">{len(themed_small)} Epics · {len(by_initiative)} initiative{"s" if len(by_initiative) != 1 else ""} · 跨 {len({sub_team_for_issue(e, profile) for e in themed_small})} 个团队 · {total_cross_in_themed} 个跨团队</span></h2>'
            f'<div class="tagline">这些 Epic 不是正式 roadmap item，但共享同一个 initiative / 主题（例如 KubeOS、Kubernetes 1.35、New Web Console）。按主题聚合，避免被同主题的 N 份 epic 淹没。标注 <span class="cross-team-badge inline">跨团队</span> 的 Epic 带 <code>{html_escape(CROSS_TEAM_LABEL)}</code> 标签，跨团队协作；其余是本团队内部的主题工作。</div></div></header>'
            f'<div class="initiative-list">{"".join(initiative_cards)}</div>'
            f'</section>'
        )

    # ----- Small Features (everything not matched by a theme) -----
    small_feature_rows = []
    small_team_options = sorted(configured_teams)
    if any(sub_team_for_issue(epic, profile) == "Unknown" for epic in unthemed_small):
        small_team_options.append("Unknown")
    small_filter_buttons = ['<button type="button" class="small-filter active" data-small-filter="all">All</button>']
    small_filter_buttons.extend(
        f'<button type="button" class="small-filter" data-small-filter="{html_escape(team)}">{html_escape("未分配 sub-team" if team == "Unknown" else team)}</button>'
        for team in small_team_options
    )
    for epic in sorted(unthemed_small, key=lambda issue: issue.get("key") or ""):
        team = sub_team_for_issue(epic, profile)
        epic_children = children_for_epic(children, epic.get("key") or "")
        counts = child_counts(epic_children)
        active = counts["done"] + counts["in_progress"] + counts["todo"]
        epic_status_text = epic.get("status_name") or epic.get("epic_status") or "To Do"
        epic_status = normalize_status(epic_status_text)
        gap_html = issue_gap_html(epic, ctx, sprints)
        gap_line = f'<div class="small-gap">{gap_html}</div>' if gap_html else '<div class="small-ok">Plan available</div>'
        plan = issue_plan(epic)
        outcome = compact_text(epic.get("description") or issue_plan_text(epic) or "Epic description needs delivery expectation", 260)
        resources = issue_resources(epic)
        task_details = render_child_task_details(epic_children, sprints, version)
        change_signal = plan_change_signal_html([epic])
        lane_signal = lane_chip_html(epic)
        change_detail = plan_changes_html([epic])
        cross_chip = (
            f'<span class="cross-team-badge">跨团队</span>'
            if is_cross_team_issue(epic) else ""
        )
        small_feature_rows.append(
            f'<article class="small-card" data-small-team="{html_escape(team)}">'
            f'<div class="small-main"><div class="small-title">{jira_html(epic.get("key") or "")} <span>{html_escape(epic.get("summary") or "")}</span></div>'
            f'<div class="small-meta"><span class="status-pill" style="background:{status_color(epic_status)}20;color:{status_color(epic_status)}">{html_escape(epic_status_text)}</span><span>{html_escape("未分配 sub-team" if team == "Unknown" else team)}</span><span>{counts["done"]}/{active} tasks done</span>{cross_chip}{lane_signal}</div>'
            f'<p>{html_escape(outcome)}</p>{gap_line}{change_signal}</div>'
            f'<div class="small-plan"><div><span>Start</span><b>{html_escape(epic.get("start_after") or "TBD")} / {html_escape(issue_start_sprint(epic, sprints, ctx))}</b></div><div><span>Target</span><b>{html_escape(epic.get("due_date") or "TBD")} / {html_escape(issue_target_sprint(epic, sprints, ctx))}</b></div><div><span>Assignee</span><b>{html_escape(resources)}</b></div></div>'
            f'{change_detail}'
            f'{task_details}'
            f'</article>'
        )
        append_all_epic_row("Small Features", epic)
    small_features_html = ""
    if unthemed_small:
        own_small_progress = group_progress(unthemed_small, children)
        small_rows_html = "".join(small_feature_rows) or '<div class="empty-state">No small-feature Epics.</div>'
        unthemed_cross_count = sum(1 for e in unthemed_small if is_cross_team_issue(e))
        cross_tag_html = f' · {unthemed_cross_count} 个跨团队' if unthemed_cross_count else ""
        small_features_html = (
            f'<section id="small-features" class="small-features-section">'
            f'<header class="section-head"><div><h2>Small Features <span class="count">{len(unthemed_small)} Epics · 不属于任何 initiative 主题{cross_tag_html}</span></h2>'
            f'<div class="tagline">这些 Epic 属于当前版本排期，但不是正式 roadmap item，也不属于任何已识别的 initiative（KubeOS / K8s 1.35 / New Web Console / ...）。如果影响 roadmap commitment，需要触发 roadmap changelog/review。跨团队的 Epic 以 <span class="cross-team-badge inline">跨团队</span> 徽章标识。</div></div>'
            f'<div class="small-summary"><b>{own_small_progress["percent"]}%</b><span>{own_small_progress["counts"]["done"]}/{own_small_progress["active"] or 0} tasks done</span></div></header>'
            f'<div class="small-filters">{"".join(small_filter_buttons)}</div>'
            f'<div class="small-list">{small_rows_html}</div>'
            f'</section>'
        )

    task_rows = []
    for child in children:
        task_rows.append(
            f'<tr><td>{jira_html(child.get("parent_epic") or "")}</td><td>{jira_html(child.get("key") or "")}</td><td>{html_escape(child.get("issue_type") or "")}</td>'
            f'<td class="cell-summary" title="{html_escape(child.get("summary") or "")}">{html_escape(child.get("summary") or "")}</td><td>{html_escape(child.get("status_name") or "")}</td><td>{html_escape(child.get("assignee") or "")}</td>'
            f'<td>{html_escape(child_sprint_text(child, version))}</td><td>{html_escape(child_story_points_text(child))}</td></tr>'
        )

    # Epic-first execution dashboard. Keep this in the renderer so every live
    # snapshot refresh preserves the area-grouped progress view.
    unique_epics: dict[str, dict[str, Any]] = {}
    for epic in all_epics:
        key = str(epic.get("key") or "")
        if key:
            unique_epics[key] = epic
    try:
        dashboard_date = dt.datetime.fromisoformat(str(snapshot.get("generated_at") or "")).date()
    except ValueError:
        dashboard_date = dt.datetime.now().astimezone().date()
    month_start = dashboard_date.replace(day=1)
    next_month = (month_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    month_end = next_month - dt.timedelta(days=1)
    month_tokens = {
        f"{dashboard_date.month}月",
        f"{dashboard_date.month:02d}月",
        f"{dashboard_date.year}-{dashboard_date.month:02d}",
    }

    def epic_overlaps_current_month(epic: dict[str, Any]) -> bool:
        try:
            start = dt.date.fromisoformat(str(epic.get("start_after") or epic.get("due_date") or ""))
            target = dt.date.fromisoformat(str(epic.get("due_date") or epic.get("start_after") or ""))
        except ValueError:
            return False
        return start <= month_end and target >= month_start

    def child_is_current_month(child: dict[str, Any], epic: dict[str, Any]) -> bool:
        child_sprints = [str(value) for value in child.get("sprints") or []]
        if child_sprints:
            return any(token in sprint for sprint in child_sprints for token in month_tokens)
        return epic_overlaps_current_month(epic)
    area_order = [str(team.get("name")) for team in profile.get("sub_teams") or [] if team.get("name")]
    epics_by_area: dict[str, list[dict[str, Any]]] = {}
    for epic in unique_epics.values():
        area = sub_team_for_issue(epic, profile)
        epics_by_area.setdefault(area, []).append(epic)

    def area_sort_key(area: str) -> tuple[int, str]:
        return (area_order.index(area), area) if area in area_order else (len(area_order), area)

    def epic_plan_sort_key(issue: dict[str, Any]) -> tuple[str, str, str]:
        # ISO dates sort chronologically as strings. Missing plan dates belong
        # at the bottom so the earliest scheduled work is immediately visible.
        start = str(issue.get("start_after") or "9999-12-31")
        target = str(issue.get("due_date") or "9999-12-31")
        return (start, target, str(issue.get("key") or ""))

    area_sections: list[str] = []
    for area in sorted(epics_by_area, key=area_sort_key):
        area_epics = sorted(epics_by_area[area], key=epic_plan_sort_key)
        area_children = [
            child
            for epic in area_epics
            for child in children_for_epic(children, epic.get("key") or "")
        ]
        area_counts = child_counts(area_children)
        area_active = area_counts["done"] + area_counts["in_progress"] + area_counts["todo"]
        area_pct = pct(area_counts["done"], area_active) if area_active else 0
        month_children = [
            child
            for epic in area_epics
            for child in children_for_epic(children, epic.get("key") or "")
            if child_is_current_month(child, epic)
        ]
        month_counts = child_counts(month_children)
        month_active = month_counts["done"] + month_counts["in_progress"] + month_counts["todo"]
        month_pct = pct(month_counts["done"], month_active) if month_active else 0
        epic_progress_rows: list[str] = []
        for epic in area_epics:
            epic_children = children_for_epic(children, epic.get("key") or "")
            counts = child_counts(epic_children)
            active = counts["done"] + counts["in_progress"] + counts["todo"]
            complete_pct = pct(counts["done"], active) if active else 0
            workflow_status_text = epic.get("status_name") or epic.get("epic_status") or "To Do"
            workflow_status = normalize_status(workflow_status_text)
            progress_state = "Done" if active and counts["done"] == active else "In Progress" if counts["done"] or counts["in_progress"] else "To Do"
            epic_progress_rows.append(
                f'<tr><td><div class="epic-progress-title">{jira_html(epic.get("key") or "")}<span title="{html_escape(epic.get("summary") or "")}">{html_escape(epic.get("summary") or "")}</span></div></td>'
                f'<td><span class="status-pill" style="background:{status_color(workflow_status)}20;color:{status_color(workflow_status)}">{html_escape(workflow_status_text)}</span></td>'
                f'<td><span class="status-pill" style="background:{status_color(progress_state)}20;color:{status_color(progress_state)}">{html_escape(progress_state)}</span></td>'
                f'<td><div class="epic-progress-cell"><div class="epic-progress-line"><b>{complete_pct}%</b><span>{counts["done"]}/{active} Done · {counts["in_progress"]} 进行中</span></div>{progress_bar_html(counts)}</div></td>'
                f'<td>{html_escape(issue_resources(epic))}</td>'
                f'<td>{html_escape(epic.get("start_after") or "TBD")} → {html_escape(epic.get("due_date") or "TBD")}</td></tr>'
            )
        area_sections.append(
            f'<section class="area-progress-group"><header class="area-progress-head"><div class="area-progress-name"><h3>{html_escape(display_sub_team(area))}</h3><span>{len(area_epics)} Epics</span></div>'
            f'<div class="area-progress-metrics"><div class="area-metric"><div class="area-metric-line"><span>Q3 总体</span><b>{area_pct}%</b><small>{area_counts["done"]}/{area_active} Done</small></div><div class="area-progress-track"><i style="width:{area_pct}%"></i></div></div>'
            f'<div class="area-metric current-month"><div class="area-metric-line"><span>{dashboard_date.month} 月</span><b>{month_pct}%</b><small>{month_counts["done"]}/{month_active} Done</small></div><div class="area-progress-track"><i style="width:{month_pct}%"></i></div></div></div></header>'
            f'<div class="area-progress-table-wrap"><table class="area-progress-table"><thead><tr><th>Epic</th><th>Jira 状态</th><th>任务推导状态</th><th>任务完成度</th><th>负责人</th><th>计划周期</th></tr></thead><tbody>{"".join(epic_progress_rows)}</tbody></table></div></section>'
        )
    epic_progress_dashboard_html = (
        f'<section id="epic-progress-dashboard" class="epic-progress-dashboard"><header class="section-head"><div><h2>Epic Progress by Area <span class="count">{len(unique_epics)} Epics · 实时 Jira 快照</span></h2>'
        f'<div class="tagline">领域来自 Jira area labels。Jira 状态展示工作流实际状态；任务完成度仅按 Epic 下 Done 任务数 / 活跃任务总数计算。</div></div></header>{"".join(area_sections)}</section>'
    )

    warning_html = ""
    warning_blocks = []
    if info_gap_groups:
        for team, gaps in sorted(gaps_by_team.items()):
            detail_items = "".join(f"<li>{gap}</li>" for gap in gaps[:10])
            if len(gaps) > 10:
                detail_items += f"<li>... and {len(gaps) - 10} more</li>"
            warning_blocks.append(
                f'<li><b>{html_escape(display_sub_team(team))}</b>: {len(gaps)} plan gaps. '
                f'通过 builders-roadmap-studio / builders-jira flow 补 StartAfter / Due Date / Risk 或结构化变更说明；不要手工改 snapshot 或 HTML。'
                f'<ul>{detail_items}</ul></li>'
            )
    if missing_sub_team_epics:
        missing_items = "".join(
            f'<li>{jira_html(epic.get("key") or "")}: {html_escape(epic.get("summary") or "")}</li>'
            for epic in missing_sub_team_epics[:12]
        )
        if len(missing_sub_team_epics) > 12:
            missing_items += f"<li>... and {len(missing_sub_team_epics) - 12} more</li>"
        warning_blocks.append(
            f'<li><b>未分配 sub-team</b>: {len(missing_sub_team_epics)} Epics need a configured sub-team label. '
            f'通过 skill 生成 Jira label 操作预览并确认写入。<ul>{missing_items}</ul></li>'
        )
    if warning_blocks:
        warning_html = f'<section class="warning-panel"><h2>Planning Input Needed</h2><p>以下缺口会影响排期讨论和离线 dashboard 的可信度。所有补充都应通过 skill/Jira flow 写入 Jira，再 refresh snapshot。</p><ul>{"".join(warning_blocks)}</ul></section>'

    task_progress_width = min(100, child_done_pct + pct(child_total_counts["in_progress"], child_active))
    generated = html_escape(snapshot.get("generated_at") or "not available")
    snapshot_studio_version = html_escape(snapshot_roadmap_studio_version(snapshot))
    renderer_studio_version = html_escape(ROADMAP_STUDIO_VERSION)
    team_key = html_escape(profile.get("team_key") or "unknown")
    jira_project = html_escape(ctx["jira_project"])
    scope = html_escape(sub_team or "All sub-teams")
    code_freeze_label = html_escape(str(remaining_sprints) + " sprints" if remaining_sprints else "TBD")
    code_freeze_sub = html_escape((str(days_to_freeze) + " days · ") if days_to_freeze is not None else "") + html_escape(code_freeze_raw or "not set")

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="roadmap-studio-version" content="{renderer_studio_version}">
<meta name="roadmap-studio-snapshot-version" content="{snapshot_studio_version}">
<title>ACP {html_escape(version)} Roadmap Dashboard</title>
<style>
:root {{ --bg:#f8fafc; --panel:#fff; --border:#e5e7eb; --text:#111827; --muted:#6b7280; --blue:#2563eb; --green:#10b981; --amber:#f59e0b; --red:#dc2626; --gray:#9ca3af; --shadow:0 1px 3px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.06); }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; line-height:1.5; }}
.wrap {{ max-width:1420px; margin:0 auto; padding:24px; }} header.top {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16px; border-bottom:1px solid var(--border); padding-bottom:18px; margin-bottom:20px; flex-wrap:wrap; }}
h1 {{ margin:0; font-size:30px; letter-spacing:-.03em; }} h2 {{ margin:0 0 12px; font-size:18px; }} a {{ color:#2563eb; text-decoration:none; font-family:ui-monospace,monospace; font-weight:700; }} a:hover {{ text-decoration:underline; }} .muted {{ color:var(--muted); font-size:12px; }} code {{ background:#f3f4f6; padding:2px 6px; border-radius:5px; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px; }} .kpi-link {{ color:inherit; font-family:inherit; font-weight:inherit; }} .kpi {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:16px 20px; box-shadow:var(--shadow); min-height:124px; }} .kpi-clickable {{ transition:transform .15s, box-shadow .15s; }} .kpi-clickable:hover {{ transform:translateY(-1px); box-shadow:0 6px 14px rgba(15,23,42,.10); }} .kpi-label {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; font-weight:800; }} .kpi-value {{ font-size:34px; font-weight:780; line-height:1.1; margin-top:6px; }} .kpi-sub {{ color:var(--muted); font-size:12px; margin-top:4px; }} .kpi-bar,.progress-bar {{ height:8px; display:flex; overflow:hidden; background:#e5e7eb; border-radius:999px; margin-top:12px; }}
.timeline-panel,.panel,.warning-panel {{ background:linear-gradient(180deg,#fff 0%,#f9fafb 100%); border:1px solid var(--border); border-radius:12px; padding:22px 24px; box-shadow:var(--shadow); margin-bottom:22px; }} .warning-panel {{ background:linear-gradient(180deg,#fffbeb 0%,#fef3c7 100%); border:2px solid #f59e0b; }} .warning-panel ul {{ margin:0; padding-left:20px; }} .tagline {{ color:var(--muted); font-size:13px; margin-bottom:16px; }} .timeline-meta {{ display:flex; gap:18px; flex-wrap:wrap; color:#374151; font-size:13px; margin-bottom:14px; }} .v-badge {{ font-size:12px; font-weight:800; padding:2px 10px; border-radius:999px; background:#1f2937; color:#fff; }}
.sprint-strip {{ display:grid; grid-template-columns:repeat({max(len(sprints), 1)}, minmax(0, 1fr)); gap:6px; overflow-x:auto; padding:4px 2px 8px; }} .sprint {{ position:relative; min-width:0; padding:10px 7px; border-radius:8px; text-align:center; font-size:11px; background:#fff; border:1px solid var(--border); }} .sprint.sp-current {{ background:#2563eb; color:#fff; border-color:#2563eb; box-shadow:0 0 0 3px rgba(37,99,235,.16); }} .sprint.sp-past {{ background:#f3f4f6; color:#6b7280; }} .sp-label {{ font-family:ui-monospace,monospace; font-weight:800; }} .sp-date {{ color:var(--muted); margin-top:3px; line-height:1.3; }} .sp-current .sp-date {{ color:#dbeafe; }} .now-dot {{ position:absolute; right:8px; top:8px; width:8px; height:8px; border-radius:50%; background:#fff; }}
.grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:22px; }} .donut-wrap {{ display:grid; grid-template-columns:160px 1fr; gap:20px; align-items:center; }} .donut {{ width:150px; height:150px; border-radius:50%; background:conic-gradient(#10b981 0 {child_done_pct}%, #3b82f6 {child_done_pct}% {task_progress_width}%, #9ca3af 0); position:relative; }} .donut:after {{ content:"{child_done_pct}%"; position:absolute; inset:34px; background:#fff; border-radius:50%; display:grid; place-items:center; font-size:26px; font-weight:800; }} .legend-row {{ display:grid; grid-template-columns:12px 96px 1fr 44px; align-items:center; gap:8px; margin:8px 0; }} .dot {{ width:10px; height:10px; border-radius:50%; }} .legend-bar {{ height:7px; background:#e5e7eb; border-radius:999px; overflow:hidden; }} .legend-fill {{ display:block; height:100%; }} .health-row {{ display:flex; justify-content:space-between; gap:14px; align-items:center; padding:11px 0; border-bottom:1px solid var(--border); }} .health-row:last-child {{ border-bottom:0; }} .health-row span {{ display:block; color:var(--muted); font-size:12px; }} .health-action {{ font-size:12px; font-weight:800; color:#047857; }} .health-row.risk .health-action {{ color:#92400e; }}
#roadmaps {{ margin-top:4px; }} .count {{ color:var(--muted); font-size:13px; font-weight:400; }} .rm-chips {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:10px; margin:4px 0 14px; }} .rm-chip {{ display:block; padding:12px 14px; border-radius:10px; border:1px solid var(--border); background:var(--panel); text-decoration:none; color:inherit; cursor:pointer; transition:transform .15s, box-shadow .15s, border-color .15s, padding .15s; font-family:inherit; font-weight:inherit; }} .rm-chip:hover {{ transform:translateY(-1px); box-shadow:0 4px 8px rgba(0,0,0,.08); }} .rm-chip-complete {{ background:rgba(16,185,129,.10); border-color:rgba(16,185,129,.35); }} .rm-chip-in-progress {{ background:rgba(59,130,246,.10); border-color:rgba(59,130,246,.35); }} .rm-chip-gray {{ background:rgba(107,114,128,.07); border-color:rgba(107,114,128,.25); }} .chip-name {{ font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .chip-stats {{ color:var(--muted); font-size:12px; margin-top:3px; }} .chip-gap {{ display:inline-block; margin-left:6px; color:#92400e; font-weight:800; }} .rm-chip.active {{ box-shadow:0 0 0 3px rgba(37,99,235,.15); border-width:2px; padding:11px 13px; }} .rm-actions {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }} .rm-action {{ border:1px solid var(--border); background:#fff; border-radius:8px; padding:7px 10px; cursor:pointer; font-weight:700; }} .rm-legend {{ color:var(--muted); font-size:12px; }} .legend-pip {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-left:10px; }} .pip-complete {{ background:#10b981; }} .pip-in-progress {{ background:#3b82f6; }} .pip-gray {{ background:#9ca3af; }}
.rm-card[hidden] {{ display:none; }} .rm-card {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:18px 22px; box-shadow:var(--shadow); margin-bottom:14px; }} .rm-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:6px; }} .rm-head h3 {{ margin:0; font-size:19px; }} .rm-subtitle,.rm-summary {{ color:var(--muted); font-size:13px; }} .rm-pct {{ font-size:26px; font-weight:800; }} .sprint-plan {{ margin:14px 0; padding:14px; border:1px solid #bfdbfe; background:#eff6ff; border-radius:12px; }} .sprint-plan.needs-plan {{ border-color:#f59e0b; background:#fffbeb; }} .plan-head {{ display:flex; justify-content:space-between; gap:12px; margin-bottom:10px; }} .plan-head span {{ color:#92400e; font-size:12px; font-weight:800; }} .plan-strip {{ display:grid; grid-template-columns:repeat({max(len(sprints), 1)},1fr); gap:5px; margin-bottom:12px; }} .plan-cell {{ min-height:24px; border-radius:999px; border:1px solid #d1d5db; background:#fff; text-align:center; color:#6b7280; font-size:11px; padding-top:3px; }} .plan-cell.planned.done {{ background:#dcfce7; border-color:#10b981; color:#047857; }} .plan-cell.planned.progress {{ background:#dbeafe; border-color:#3b82f6; color:#1d4ed8; }} .plan-cell.planned.todo {{ background:#f3f4f6; border-color:#9ca3af; color:#374151; }} .plan-cell.start,.plan-cell.target {{ box-shadow:0 0 0 2px rgba(17,24,39,.12) inset; font-weight:800; }} .plan-gap {{ grid-column:1/-1; padding:5px 10px; border-radius:999px; background:#fef3c7; color:#92400e; text-align:center; font-size:12px; font-weight:800; }} .plan-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }} .plan-grid div {{ background:#fff; border:1px solid rgba(148,163,184,.25); border-radius:8px; padding:8px 10px; }} .plan-grid span {{ display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }} .plan-grid b {{ display:block; margin-top:2px; }} .plan-detail p {{ margin:8px 0 0; color:#374151; }}
.epics {{ margin-top:12px; }} .epic-row {{ display:grid; grid-template-columns:1fr 290px; gap:12px; align-items:center; padding:10px 0; border-top:1px solid var(--border); }} .epic-meta {{ display:flex; gap:8px; align-items:center; min-width:0; }} .status-pill {{ display:inline-block; border-radius:999px; padding:2px 8px; font-size:12px; font-weight:800; white-space:nowrap; }} .epic-summary {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .epic-children {{ min-width:230px; }} .empty-state {{ padding:14px; border-radius:10px; background:#f9fafb; color:var(--muted); }}
.small-features-section {{ background:linear-gradient(180deg,#fff 0%,#f8fafc 100%); border:1px solid var(--border); border-radius:14px; padding:20px 22px; box-shadow:var(--shadow); margin:22px 0; }} .section-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap; }} .small-summary {{ min-width:130px; text-align:right; }} .small-summary b {{ display:block; font-size:28px; line-height:1; }} .small-summary span {{ display:block; color:var(--muted); font-size:12px; margin-top:4px; }} .small-filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0 14px; }} .small-filter {{ border:1px solid var(--border); background:#fff; border-radius:999px; padding:7px 12px; cursor:pointer; font-weight:800; }} .small-filter.active {{ background:#111827; color:#fff; border-color:#111827; }} .small-list {{ display:grid; gap:10px; }} .small-card {{ display:grid; grid-template-columns:1fr 360px; gap:14px; background:#fff; border:1px solid var(--border); border-radius:12px; padding:14px 16px; }} .small-card.is-hidden {{ display:none; }} .small-title {{ display:flex; gap:10px; align-items:center; min-width:0; font-weight:800; }} .small-title span {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .small-meta {{ display:flex; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:12px; margin-top:6px; }} .small-card p {{ margin:8px 0 0; color:#374151; }} .small-gap {{ margin-top:8px; color:#92400e; font-weight:800; font-size:12px; }} .small-ok {{ margin-top:8px; color:#047857; font-weight:800; font-size:12px; }} .small-plan {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; align-content:start; }} .small-plan div {{ background:#f9fafb; border:1px solid var(--border); border-radius:9px; padding:8px 10px; }} .small-plan span {{ display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }} .small-plan b {{ display:block; margin-top:2px; }}
.epic-progress-dashboard {{ margin:22px 0; }} .area-progress-group {{ background:#fff; border:1px solid var(--border); border-radius:14px; overflow:hidden; margin:14px 0; box-shadow:var(--shadow); }} .area-progress-head {{ display:grid; grid-template-columns:minmax(220px,.7fr) minmax(420px,1.3fr); gap:24px; align-items:center; padding:18px 20px; background:#0f172a; color:#fff; }} .area-progress-name h3 {{ margin:0 0 4px; font-size:18px; }} .area-progress-name span {{ color:#94a3b8; font-size:12px; }} .area-progress-metrics {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }} .area-metric-line {{ display:grid; grid-template-columns:72px 54px 1fr; gap:8px; align-items:baseline; margin-bottom:7px; }} .area-metric-line span {{ color:#cbd5e1; font-weight:800; }} .area-metric-line b {{ font-size:22px; }} .area-metric-line small {{ color:#94a3b8; text-align:right; }} .area-progress-track {{ height:10px; background:#334155; border-radius:999px; overflow:hidden; }} .area-progress-track i {{ display:block; height:100%; background:#38bdf8; border-radius:999px; }} .area-metric.current-month .area-progress-track i {{ background:#22c55e; }} .area-progress-table-wrap {{ overflow-x:auto; }} .area-progress-table {{ border:0; border-radius:0; }} .area-progress-table th:nth-child(1) {{ min-width:330px; }} .area-progress-table th:nth-child(4) {{ min-width:260px; }} .epic-progress-title {{ display:flex; gap:9px; align-items:center; min-width:0; }} .epic-progress-title span {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; }} .epic-progress-cell {{ min-width:240px; }} .epic-progress-line {{ display:flex; justify-content:space-between; gap:10px; align-items:center; margin-bottom:5px; }} .epic-progress-line b {{ font-size:16px; }} .epic-progress-line span {{ color:var(--muted); font-size:11px; }}
table {{ width:100%; border-collapse:separate; border-spacing:0; background:#fff; border:1px solid var(--border); border-radius:12px; overflow:hidden; }} th,td {{ padding:10px 12px; border-bottom:1px solid var(--border); vertical-align:top; }} th {{ text-align:left; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; background:#fafbfc; }} tr:last-child td {{ border-bottom:0; }} .cell-summary {{ max-width:520px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .num {{ font-family:ui-monospace,monospace; white-space:nowrap; }} details {{ margin:18px 0; }} details summary {{ cursor:pointer; font-weight:800; color:#374151; margin-bottom:10px; }}
@media(max-width:1000px) {{ .kpis,.grid-2,.plan-grid {{ grid-template-columns:1fr 1fr; }} .epic-row {{ grid-template-columns:1fr; }} .area-progress-head {{ grid-template-columns:1fr; }} table {{ display:block; overflow-x:auto; }} }} @media(max-width:640px) {{ .kpis,.grid-2,.donut-wrap,.plan-grid,.area-progress-metrics {{ grid-template-columns:1fr; }} .wrap {{ padding:16px; }} }}
{shared_dashboard_css()}
</style>
</head>
<body><main class="wrap">
<header class="top"><div><h1>ACP {html_escape(version)} Roadmap Dashboard</h1><div class="muted">Team <code>{team_key}</code> · Jira <code>{jira_project}</code> · Scope <code>{scope}</code> · Current Sprint <code>{html_escape(current_sprint_label)}</code></div></div><div class="muted">Snapshot<br><b>{generated}</b><br>Roadmap Studio <code>{renderer_studio_version}</code><br><span>snapshot <code>{snapshot_studio_version}</code></span></div></header>
<section class="kpis">
  <a href="#roadmaps" class="kpi-link"><article class="kpi kpi-clickable"><div class="kpi-label">Roadmaps</div><div class="kpi-value">{len(formal_groups)}</div><div class="kpi-sub"><strong>{done_groups}</strong> complete · {in_progress_groups} in progress · {todo_groups} not started</div>{kpi_bar(done_groups, in_progress_groups, todo_groups)}</article></a>
  <a href="#all-epics" class="kpi-link"><article class="kpi kpi-clickable"><div class="kpi-label">Epics</div><div class="kpi-value">{len(all_epics)}</div><div class="kpi-sub"><strong>{done_epics}</strong> done · {in_progress_epics} in progress · {todo_epics} todo</div>{kpi_bar(done_epics, in_progress_epics, todo_epics)}</article></a>
  <a href="#all-tasks" class="kpi-link"><article class="kpi kpi-clickable"><div class="kpi-label">Tasks</div><div class="kpi-value">{len(children)}</div><div class="kpi-sub"><strong style="color:#10b981">{child_total_counts['done']}</strong> done · <span style="color:#10b981">{child_done_pct}%</span> of {child_active} active</div>{progress_bar_html(child_total_counts)}</article></a>
  <article class="kpi"><div class="kpi-label">Code Freeze</div><div class="kpi-value">{code_freeze_label}</div><div class="kpi-sub">{code_freeze_sub}</div></article>
</section>
<section class="timeline-panel"><h2>Release Timeline <span class="v-badge">{html_escape(version)}</span></h2><div class="tagline">ACP sprint plan from release meta. Core and Aligned work targets code freeze; Epics labeled <code>{LANE_AGNOSTIC_LABEL}</code> may target the post-release Agnostic extension window.</div><div class="timeline-meta">{timeline_meta}</div><div class="sprint-strip">{''.join(sprint_header)}</div></section>
{warning_html}
<section class="grid-2"><div class="panel"><h2>Task Status <span class="count">{len(children)} tasks</span></h2><div class="donut-wrap"><div class="donut"></div><div class="legend"><div class="legend-row"><span class="dot" style="background:#10b981"></span><span>Done</span><span class="legend-bar"><span class="legend-fill" style="width:{pct(child_total_counts['done'], len(children))}%;background:#10b981"></span></span><b>{child_total_counts['done']}</b></div><div class="legend-row"><span class="dot" style="background:#3b82f6"></span><span>In Progress</span><span class="legend-bar"><span class="legend-fill" style="width:{pct(child_total_counts['in_progress'], len(children))}%;background:#3b82f6"></span></span><b>{child_total_counts['in_progress']}</b></div><div class="legend-row"><span class="dot" style="background:#9ca3af"></span><span>Todo</span><span class="legend-bar"><span class="legend-fill" style="width:{pct(child_total_counts['todo'], len(children))}%;background:#9ca3af"></span></span><b>{child_total_counts['todo']}</b></div><div class="legend-row"><span class="dot" style="background:#d1d5db"></span><span>Cancelled</span><span class="legend-bar"><span class="legend-fill" style="width:{pct(child_total_counts['cancelled'], len(children))}%;background:#d1d5db"></span></span><b>{child_total_counts['cancelled']}</b></div></div></div></div><div class="panel"><h2>Planning Health <span class="count">{len(info_gap_groups)} groups need input</span></h2>{''.join(health_rows) or '<div class="health-row ok"><div><b>No sub-team configured</b><span>Update team-profile.yaml</span></div></div>'}</div></section>
{epic_progress_dashboard_html}
<section id="roadmaps"><h2>Roadmaps <span class="count">{done_groups} complete · {in_progress_groups} in progress · {todo_groups} not started · click a chip to expand detail</span></h2><div class="rm-chips">{''.join(chip_html)}</div><div class="rm-actions"><button type="button" class="rm-action" data-action="show-all">Show all</button><button type="button" class="rm-action" data-action="hide-all">Hide all</button><span class="rm-legend"><span class="legend-pip pip-complete"></span> complete <span class="legend-pip pip-in-progress"></span> in progress <span class="legend-pip pip-gray"></span> not started / no tasks</span></div><div class="rm-cards-wrap">{''.join(card_html)}</div></section>
{themed_features_html}
{small_features_html}
<details id="all-epics"><summary>All Epics ({len(all_epics)}) - click to expand</summary><table><thead><tr><th>Roadmap</th><th>Key</th><th>Summary</th><th>Epic Status</th><th>Sub-team</th><th>Tasks Done</th><th>Start</th><th>Target</th></tr></thead><tbody>{''.join(all_epic_rows)}</tbody></table></details>
<details id="all-tasks"><summary>All Tasks ({len(children)}) - click to expand</summary><table><thead><tr><th>Epic</th><th>Key</th><th>Type</th><th>Summary</th><th>Status</th><th>Assignee</th><th>Sprint</th><th>Points</th></tr></thead><tbody>{''.join(task_rows)}</tbody></table></details>
</main>
<script>
function setCard(name, visible) {{
  const card = document.getElementById('rm-card-' + name);
  const chip = document.querySelector('.rm-chip[data-rm="' + name + '"]');
  if (!card || !chip) return;
  card.hidden = !visible;
  chip.classList.toggle('active', visible);
}}
document.querySelectorAll('.rm-chip').forEach(chip => {{
  chip.addEventListener('click', event => {{
    event.preventDefault();
    const name = chip.dataset.rm;
    const card = document.getElementById('rm-card-' + name);
    const next = card ? card.hidden : true;
    setCard(name, next);
    if (next && card) card.scrollIntoView({{behavior:'smooth', block:'start'}});
  }});
}});
document.querySelectorAll('.rm-action').forEach(button => {{
  button.addEventListener('click', () => {{
    const show = button.dataset.action === 'show-all';
    document.querySelectorAll('.rm-chip').forEach(chip => setCard(chip.dataset.rm, show));
  }});
}});
document.querySelectorAll('.small-filter').forEach(button => {{
  button.addEventListener('click', () => {{
    const filter = button.dataset.smallFilter || 'all';
    document.querySelectorAll('.small-filter').forEach(item => item.classList.toggle('active', item === button));
    document.querySelectorAll('.small-card').forEach(card => {{
      card.classList.toggle('is-hidden', filter !== 'all' && card.dataset.smallTeam !== filter);
    }});
  }});
}});
if (location.hash && location.hash.startsWith('#rm-card-')) {{
  setCard(location.hash.replace('#rm-card-', ''), true);
}}
</script>
</body></html>'''


def render_dashboard_html(repo: Path, output_path: Path | None = None, teams: list[str] | None = None) -> str:
    dashboard_output = output_path or builders_dashboard_path(repo)
    taxonomy_path = builders_taxonomy_path(repo)
    # Optional team scope: when `teams` is given, render a combined overview for only
    # those teams (e.g. app-service + ai-platform + hyperflux) instead of all Builders
    # teams. The default (teams=None) preserves the full all-team dashboard behavior.
    scoped_team_set = {t.strip() for t in teams if t and t.strip()} if teams else None

    def active_release_meta(roadmap_root: Path) -> Path | None:
        metas = sorted(roadmap_root.glob("releases/*/roadmap-meta.yaml"))
        active = [
            meta for meta in metas
            if (load_yaml(meta) or {}).get("role") == "current"
            or (load_yaml(meta) or {}).get("status") == "active"
        ]
        return active[0] if active else None

    def taxonomy_order() -> tuple[list[str], dict[str, list[str]]]:
        domains: list[str] = []
        capabilities: dict[str, list[str]] = {}
        current = ""
        if not taxonomy_path.exists():
            return domains, capabilities
        for line in read_text(taxonomy_path).splitlines():
            domain_match = re.match(r"## Domain \d+:\s*(.+)", line.strip())
            if domain_match:
                current = domain_match.group(1).strip()
                domains.append(current)
                capabilities.setdefault(current, [])
                continue
            if current and line.startswith("|") and "|---" not in line and "| # |" not in line:
                cells = split_markdown_table_row(line)
                if len(cells) >= 2 and re.match(r"\d+\.\d+", cells[0]):
                    capabilities.setdefault(current, []).append(cells[1])
        return domains, capabilities

    domain_order, capability_order = taxonomy_order()
    known_domains = set(domain_order)
    known_capabilities = {cap for values in capability_order.values() for cap in values}
    team_dirs = available_team_keys(repo)
    if scoped_team_set is not None:
        missing_scope = scoped_team_set - set(team_dirs)
        if missing_scope:
            raise SystemExit(f"--teams referenced unknown team(s): {sorted(missing_scope)}. Known: {team_dirs}")
        team_dirs = [team for team in team_dirs if team in scoped_team_set]
    capability_groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    small_items: list[dict[str, Any]] = []
    cross_team_items: list[dict[str, Any]] = []
    team_states: list[dict[str, Any]] = []
    setup_gaps: list[dict[str, str]] = []
    formal_total = matched_total = small_total = plan_gap_total = plan_change_total = 0

    def dashboard_issue_team(issue: dict[str, Any], ctx: dict[str, Any]) -> str:
        project_key = issue_project_key(issue)
        if project_key == str(ctx.get("jira_project") or ""):
            return str(ctx["profile"].get("team_key") or "Unknown")
        return external_project_team_map(ctx["profile"]).get(project_key, "Unknown")

    for team_key in team_dirs:
        roadmap_root = team_roadmap_root(repo, team_key)
        state = {
            "team": team_key,
            "status": "not-onboarded",
            "version": "",
            "formal": 0,
            "matched": 0,
            "small": 0,
            "cross": 0,
            "gaps": 0,
            "changes": 0,
            "gantt": "",
            "snapshot_at": "not available",
            "snapshot_studio_version": "not available",
            "action": "创建 roadmap/team-profile.yaml、releases/<version>/roadmap-meta.yaml 和 roadmap.md",
        }
        if not roadmap_root.exists():
            setup_gaps.append({"team": team_key, "kind": "not-onboarded", "action": state["action"]})
            team_states.append(state)
            continue
        profile_path = roadmap_root / "team-profile.yaml"
        if not profile_path.exists():
            setup_gaps.append({"team": team_key, "kind": "missing-profile", "action": f"创建 {repo_relative_path(repo, profile_path)}"})
            state["action"] = "创建 team-profile.yaml"
            team_states.append(state)
            continue
        meta_path = active_release_meta(roadmap_root)
        if not meta_path:
            setup_gaps.append({"team": team_key, "kind": "missing-active-release", "action": "创建或激活 releases/<version>/roadmap-meta.yaml"})
            state["action"] = "创建或激活 release meta"
            team_states.append(state)
            continue
        try:
            ctx = load_context_from_meta(repo, meta_path)
        except Exception as exc:
            setup_gaps.append({"team": team_key, "kind": "invalid-release-meta", "action": str(exc)})
            state["action"] = "修复 roadmap-meta.yaml"
            team_states.append(state)
            continue
        state["version"] = ctx["version"]
        state["gantt"] = str(ctx["gantt_path"])
        if not ctx["roadmap_path"].exists():
            setup_gaps.append({"team": team_key, "kind": "missing-roadmap", "action": f"维护 {repo_relative_path(repo, ctx['roadmap_path'])}"})
            state["action"] = "维护 roadmap.md"
            team_states.append(state)
            continue

        snapshot = load_snapshot(ctx["snapshot_path"])
        issues = list(snapshot.get("issues") or [])
        children = list(snapshot.get("child_issues") or [])
        state["snapshot_at"] = str(snapshot.get("generated_at") or "not available")
        state["snapshot_studio_version"] = snapshot_roadmap_studio_version(snapshot)
        if not ctx["snapshot_path"].exists():
            setup_gaps.append({"team": team_key, "kind": "missing-snapshot", "action": f"刷新 snapshot: {repo_relative_path(repo, ctx['snapshot_path'])}"})
            state["action"] = "刷新 snapshot"
        elif not issues:
            setup_gaps.append({"team": team_key, "kind": "empty-snapshot", "action": "snapshot 为空；检查 Jira labels 或 refresh-snapshot"})
            state["action"] = "检查 Jira labels 或刷新 snapshot"

        items = parse_roadmap_items(ctx["roadmap_path"], ctx["version"])
        small, unclassified = attach_epics(items, issues, ctx["version"], own_project=ctx.get("jira_project"))
        formal_total += len(items)
        matched_total += sum(1 for item in items if item.epics)
        small_total += len(small)
        state["status"] = "ready" if issues else "needs-data"
        state["formal"] = len(items)
        state["matched"] = sum(1 for item in items if item.epics)
        state["small"] = len(small)
        if unclassified:
            setup_gaps.append({"team": team_key, "kind": "unclassified-roadmap-work", "action": f"{len(unclassified)} Epics 既不是正式 roadmap item 也不是 small-features"})

        state["changes"] = sum(1 for issue in issues if change_logged(issue))
        plan_change_total += state["changes"]

        for item in items:
            sprints_for_entry = sprint_windows(ctx)
            gap = plan_gap_text(item.epics, ctx, sprints_for_entry)
            if gap != "信息完整":
                plan_gap_total += 1
                state["gaps"] += 1
            domain = item.domain or "Unmapped Domain"
            capability = item.capability or "Unmapped Capability"
            if domain not in known_domains:
                setup_gaps.append({"team": team_key, "kind": "unmapped-domain", "action": f"{item.roadmap_id} {item.title}: Domain `{domain}` 不在 capability taxonomy"})
            if capability and known_capabilities and capability not in known_capabilities:
                setup_gaps.append({"team": team_key, "kind": "unmapped-capability", "action": f"{item.roadmap_id} {item.title}: Capability `{capability}` 不在 capability taxonomy"})
            capability_groups.setdefault(domain, {}).setdefault(capability, []).append({
                "team": team_key,
                "version": ctx["version"],
                "item": item,
                "gap": gap,
                "status": item_status(item),
                "progress": group_progress(item.epics, children),
                "plan": sprint_plan_fields(item.epics, sprints_for_entry, ctx),
                "sprints": sprints_for_entry,
                "ctx": ctx,
                "changes": plan_change_entries(item.epics),
            })
        for issue in small:
            sprints_for_entry = sprint_windows(ctx)
            gap = issue_gap_text(issue, ctx, sprints_for_entry)
            if gap != "信息完整":
                plan_gap_total += 1
                state["gaps"] += 1
            small_items.append({
                "team": dashboard_issue_team(issue, ctx),
                "version": ctx["version"],
                "issue": issue,
                "gap": gap,
                "children": children_for_epic(children, issue.get("key") or ""),
                "sprints": sprints_for_entry,
                "ctx": ctx,
                "changes": plan_change_entries([issue]),
            })
        for issue in issues:
            if CROSS_TEAM_LABEL in set(issue.get("labels") or []):
                state["cross"] += 1
                cross_team_items.append({
                    "team": dashboard_issue_team(issue, ctx),
                    "version": ctx["version"],
                    "issue": issue,
                    "links": list(issue.get("issue_links") or []),
                    "link_data_available": "issue_links" in issue,
                })
        team_states.append(state)

    def kpi(label: str, value: str | int, sub: str, risk: bool = False) -> str:
        return f'<article class="kpi {"risk" if risk else ""}"><div class="kpi-label">{html_escape(label)}</div><div class="kpi-value">{html_escape(value)}</div><div class="kpi-sub">{html_escape(sub)}</div></article>'

    team_buttons = ['<button type="button" class="team-filter active" data-team-filter="all">All Teams</button>']
    team_buttons += [f'<button type="button" class="team-filter" data-team-filter="{html_escape(team)}">{html_escape(team)}</button>' for team in team_dirs]
    team_cards = []
    for state in team_states:
        link = f'<a class="button" href="{html_escape(html_relative_href(dashboard_output, Path(state["gantt"])))}">Open team dashboard</a>' if state.get("gantt") and Path(state["gantt"]).exists() else '<span class="muted">No team dashboard yet</span>'
        team_cards.append(f'<article class="team-card {html_escape(state["status"])}" data-team="{html_escape(state["team"])}"><div><h3>{html_escape(state["team"])}</h3><div class="muted">{html_escape(state["version"] or "no active release")} · snapshot {html_escape(state["snapshot_at"])} · studio {html_escape(state["snapshot_studio_version"])}</div></div><div class="team-metrics"><span>{state["matched"]}/{state["formal"]} roadmap</span><span>{state["small"]} small</span><span>{state["cross"]} cross-team</span><span>{state["gaps"]} plan gaps</span><span>{state["changes"]} plan changes</span></div><div>{link}</div><div class="team-action">{html_escape(state["action"] if state["status"] != "ready" else "保持 snapshot 刷新")}</div></article>')

    gap_items = [f'<li data-team="{html_escape(gap["team"])}"><b>{html_escape(gap["team"])}</b> · {html_escape(gap["kind"])}: {html_escape(gap["action"])}</li>' for gap in setup_gaps]
    gap_items += [f'<li data-team="{html_escape(state["team"])}"><b>{html_escape(state["team"])}</b> · planning-input: {state["gaps"]} Epic/Roadmap items need StartAfter / Due Date or structured change-comment review.</li>' for state in team_states if state["gaps"]]

    domain_sections = []
    domains = [domain for domain in domain_order if domain in capability_groups] + sorted(set(capability_groups) - set(domain_order))
    for domain in domains:
        cap_sections = []
        caps = [cap for cap in capability_order.get(domain, []) if cap in capability_groups.get(domain, {})] + sorted(set(capability_groups.get(domain, {})) - set(capability_order.get(domain, [])))
        for capability in caps:
            rows = []
            for entry in capability_groups[domain][capability]:
                item = entry["item"]
                epic_links = ", ".join(jira_html(epic.get("key") or "") for epic in item.epics) or '<span class="muted">No Epic</span>'
                gap_html = epics_gap_html(item.epics, entry.get("ctx"), entry.get("sprints")) if entry["gap"] != "信息完整" else '<span class="ok-text">Plan available</span>'
                plan = entry["plan"]
                change_signal = plan_change_signal_html(item.epics)
                lane_signal = lane_signal_html(item.epics)
                rows.append(f'<article class="roadmap-row" data-team="{html_escape(entry["team"])}"><div class="row-main"><div class="row-title"><span class="team-pill">{html_escape(entry["team"])}</span><b>{html_escape(item.roadmap_id)} {html_escape(item.title)}</b>{lane_signal}</div><div class="muted">ACP {html_escape(entry["version"])} · {html_escape(item.priority_group)} · {html_escape(entry["status"])}</div><div class="jira-links">{epic_links}</div>{change_signal}</div><div class="row-plan"><span>Start <b>{html_escape(plan["start_date"])} / {html_escape(plan["start_sprint"])}</b></span><span>Target <b>{html_escape(plan["due_date"])} / {html_escape(plan["target_sprint"])}</b></span><span>{entry["progress"]["percent"]}% · {entry["progress"]["counts"]["done"]}/{entry["progress"]["active"] or 0} tasks</span></div><div class="row-gap {"risk" if entry["gap"] != "信息完整" else "ok"}">{gap_html}</div></article>')
            cap_sections.append(f'<section class="capability-card"><h3>{html_escape(capability)} <span class="count">{len(rows)} items</span></h3><div class="roadmap-list">{"".join(rows)}</div></section>')
        domain_sections.append(f'<section class="domain-section"><h2>{html_escape(domain)}</h2>{"".join(cap_sections)}</section>')

    # Build set of epic keys already shown in Capability Roadmaps section,
    # so themed-features and cross-team-work sections do not duplicate them.
    roadmap_epic_keys: set[str] = set()
    for _domain, _caps in capability_groups.items():
        for _cap, _entries in _caps.items():
            for _entry in _entries:
                for _epic in _entry["item"].epics:
                    _k = _epic.get("key")
                    if _k:
                        roadmap_epic_keys.add(_k)

    # Partition small_items: themed (matches initiative) vs untheme (remaining flat)
    themed_by_initiative: dict[str, dict[str, Any]] = {}
    untheme_small_entries: list[dict[str, Any]] = []
    for entry in small_items:
        issue = entry["issue"]
        match = detect_themed_initiative(issue.get("summary") or "")
        if match is None:
            untheme_small_entries.append(entry)
            continue
        slug, name = match
        bucket = themed_by_initiative.setdefault(slug, {"slug": slug, "name": name, "entries": []})
        bucket["entries"].append(entry)

    initiative_order = [s for s, _, _ in THEMED_FEATURE_INITIATIVES]

    # Themed initiative cards
    initiative_cards: list[str] = []
    for slug in initiative_order:
        if slug not in themed_by_initiative:
            continue
        bucket = themed_by_initiative[slug]
        bucket_entries = bucket["entries"]
        bucket_children = [c for e in bucket_entries for c in e["children"]]
        bucket_counts = child_counts(bucket_children)
        bucket_active = bucket_counts["done"] + bucket_counts["in_progress"] + bucket_counts["todo"]
        bucket_pct = pct(bucket_counts["done"], bucket_active) if bucket_active else 0
        teams_in_bucket = sorted({e["team"] for e in bucket_entries})
        cross_count_in_bucket = sum(1 for e in bucket_entries if is_cross_team_issue(e["issue"]))
        teams_summary = " · ".join(
            f'<span class="initiative-team">{html_escape(t)}</span>' for t in teams_in_bucket
        )
        cross_summary = (
            f' · <span class="initiative-cross-count">含 {cross_count_in_bucket} 个跨团队 Epic</span>'
            if cross_count_in_bucket else ""
        )

        epic_rows_html: list[str] = []
        for entry in sorted(bucket_entries, key=lambda e: (e["team"], e["issue"].get("key") or "")):
            issue = entry["issue"]
            counts = child_counts(entry["children"])
            active = counts["done"] + counts["in_progress"] + counts["todo"]
            child_text = (
                f'<strong>{counts["done"]}</strong>/{active} done'
                if active else '<span class="muted">no tasks</span>'
            )
            if counts["in_progress"] or counts["todo"] or counts["cancelled"]:
                child_text += (
                    f'<span class="muted"> · {counts["in_progress"]} ip · '
                    f'{counts["todo"]} todo · {counts["cancelled"]} cancel</span>'
                )
            cross_badge = (
                f'<span class="cross-team-badge" title="带 {html_escape(CROSS_TEAM_LABEL)} 标签 — 跨团队协作">跨团队</span>'
                if is_cross_team_issue(issue) else ""
            )
            epic_rows_html.append(
                f'<div class="initiative-epic" data-team="{html_escape(entry["team"])}"><div class="epic-row"><div class="epic-meta">'
                f'{jira_html(issue.get("key") or "")}'
                f'<span class="team-group-pill team-group-pill-own">{html_escape(entry["team"])}</span>'
                f'{cross_badge}'
                f'<span class="epic-summary" title="{html_escape(issue.get("summary") or "")}">{html_escape(issue.get("summary") or "")}</span>'
                f'</div><div class="epic-children">{child_text}{progress_bar_html(counts)}</div></div></div>'
            )

        initiative_cards.append(
            f'<section class="initiative-card" data-initiative="{html_escape(slug)}">'
            f'<header class="initiative-head">'
            f'<div><h3>{html_escape(bucket["name"])}</h3>'
            f'<div class="initiative-subtitle">{len(bucket_entries)} epics · {len(teams_in_bucket)} teams · {teams_summary}{cross_summary}</div></div>'
            f'<div class="initiative-stats"><b>{bucket_pct}%</b><span>{bucket_counts["done"]}/{bucket_active} tasks done</span></div>'
            f'</header>{progress_bar_html(bucket_counts)}'
            f'<div class="initiative-epics">{"".join(epic_rows_html)}</div>'
            f'</section>'
        )

    themed_total_epics = sum(len(b["entries"]) for b in themed_by_initiative.values())
    themed_cross_count = sum(
        1 for b in themed_by_initiative.values() for e in b["entries"] if is_cross_team_issue(e["issue"])
    )
    themed_teams = sorted({e["team"] for b in themed_by_initiative.values() for e in b["entries"]})

    # Slim Small Features to only un-themed entries
    small_rows: list[str] = []
    for entry in sorted(untheme_small_entries, key=lambda item: (item["team"], item["issue"].get("key") or "")):
        issue = entry["issue"]
        counts = child_counts(entry["children"])
        active = counts["done"] + counts["in_progress"] + counts["todo"]
        sprints = entry.get("sprints") or []
        gap_html = issue_gap_html(issue, entry.get("ctx"), sprints) if entry["gap"] != "信息完整" else '<span class="ok-text">Plan available</span>'
        change_signal = plan_change_signal_html([issue])
        lane_signal = lane_chip_html(issue)
        cross_badge = (
            f'<span class="cross-team-badge" title="带 {html_escape(CROSS_TEAM_LABEL)} 标签 — 跨团队协作">跨团队</span>'
            if is_cross_team_issue(issue) else ""
        )
        small_rows.append(
            f'<article class="small-card" data-team="{html_escape(entry["team"])}">'
            f'<div><div class="row-title"><span class="team-pill">{html_escape(entry["team"])}</span>'
            f'{jira_html(issue.get("key") or "")}<b>{html_escape(issue.get("summary") or "")}</b>{lane_signal}{cross_badge}</div>'
            f'<div class="muted">ACP {html_escape(entry["version"])} · {html_escape(issue.get("epic_status") or issue.get("status_name") or "To Do")}</div>'
            f'{change_signal}</div>'
            f'<div class="row-plan"><span>Start <b>{html_escape(issue.get("start_after") or "TBD")} / {html_escape(issue_start_sprint(issue, sprints, entry.get("ctx")))}</b></span>'
            f'<span>Target <b>{html_escape(issue.get("due_date") or "TBD")} / {html_escape(issue_target_sprint(issue, sprints, entry.get("ctx")))}</b></span>'
            f'<span>{counts["done"]}/{active} tasks</span></div>'
            f'<div class="row-gap {"risk" if entry["gap"] != "信息完整" else "ok"}">{gap_html}</div></article>'
        )

    # Slim Cross-Team Work to only items NOT in roadmap AND NOT in themed buckets.
    # In practice most cross-team Epics are either formal roadmap items (DR / Kata)
    # or themed small features (KubeOS / K8s 1.35 / Web Console), so this section
    # becomes a focused short-list of orphan cross-team work.
    themed_keys = {
        e["issue"].get("key") or ""
        for b in themed_by_initiative.values() for e in b["entries"]
    }
    cross_rows: list[str] = []
    for entry in sorted(cross_team_items, key=lambda item: (item["team"], item["issue"].get("key") or "")):
        issue = entry["issue"]
        key = issue.get("key") or ""
        if key in roadmap_epic_keys or key in themed_keys:
            continue
        links = entry["links"]
        if links:
            block_links = [
                f'{html_escape(link.get("relationship") or "Blocks")} {jira_html(link.get("key") or "")} <span class="muted">{html_escape(link.get("summary") or "")}</span>'
                for link in links
                if str(link.get("link_type") or "").lower() == "blocks" or "block" in str(link.get("relationship") or "").lower() or "阻" in str(link.get("relationship") or "")
            ]
            link_text = "<br>".join(block_links) if block_links else "有 issue links，但未发现 Blocks 类型关系"
        elif entry["link_data_available"]:
            link_text = "跨团队协作，未声明阻塞关系"
        else:
            link_text = "dependency links not available, refresh snapshot"
        cross_rows.append(
            f'<article class="cross-card" data-team="{html_escape(entry["team"])}">'
            f'<div><div class="row-title"><span class="team-pill">{html_escape(entry["team"])}</span>'
            f'{jira_html(issue.get("key") or "")}<b>{html_escape(issue.get("summary") or "")}</b></div>'
            f'<div class="muted">ACP {html_escape(entry["version"])} · label `{html_escape(CROSS_TEAM_LABEL)}`</div></div>'
            f'<div class="cross-link-detail">{link_text}</div></article>'
        )

    onboarded = sum(1 for item in team_states if item["status"] in {"ready", "needs-data"})
    total_gap_count = len(gap_items)
    generated_at = html_escape(dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    renderer_studio_version = html_escape(ROADMAP_STUDIO_VERSION)
    if scoped_team_set is not None:
        page_title = "Combined Roadmap Dashboard"
        scope_tagline = (
            f"Combined active roadmap of {html_escape(' + '.join(team_dirs))} · "
            f"organized by capability taxonomy · generated {generated_at}"
        )
    else:
        page_title = "Builders Roadmap Dashboard"
        scope_tagline = f"Cross-team active roadmap overview · organized by capability taxonomy · generated {generated_at}"
    return f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="roadmap-studio-version" content="{renderer_studio_version}"><title>{page_title}</title>
<style>
:root {{ --bg:#f8fafc; --panel:#fff; --border:#e5e7eb; --text:#111827; --muted:#6b7280; --blue:#2563eb; --green:#10b981; --amber:#f59e0b; --red:#dc2626; --shadow:0 1px 3px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.06); }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; line-height:1.5; }}
main {{ max-width:1480px; margin:0 auto; padding:24px; }} header.top {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; border-bottom:1px solid var(--border); padding-bottom:18px; margin-bottom:20px; flex-wrap:wrap; }} h1 {{ margin:0; font-size:30px; letter-spacing:-.03em; }} h2 {{ margin:0 0 12px; font-size:20px; }} h3 {{ margin:0 0 8px; font-size:16px; }} a {{ color:#2563eb; text-decoration:none; font-family:ui-monospace,monospace; font-weight:800; }} a:hover {{ text-decoration:underline; }} .muted,.count {{ color:var(--muted); font-size:12px; font-weight:400; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; margin-bottom:18px; }} .kpi {{ background:#fff; border:1px solid var(--border); border-radius:12px; padding:16px 18px; box-shadow:var(--shadow); }} .kpi.risk {{ background:#fffbeb; border-color:#f59e0b; }} .kpi-label {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; font-weight:800; }} .kpi-value {{ font-size:32px; font-weight:800; line-height:1.1; margin-top:5px; }} .kpi-sub {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.team-switcher,.panel,.warning-panel,.domain-section,.small-section,.cross-section {{ background:linear-gradient(180deg,#fff 0%,#f9fafb 100%); border:1px solid var(--border); border-radius:14px; padding:20px 22px; box-shadow:var(--shadow); margin-bottom:20px; }} .warning-panel {{ background:linear-gradient(180deg,#fffbeb 0%,#fef3c7 100%); border:2px solid #f59e0b; }} .team-filters {{ display:flex; gap:8px; flex-wrap:wrap; }} .team-filter {{ border:1px solid var(--border); background:#fff; border-radius:999px; padding:8px 13px; cursor:pointer; font-weight:800; }} .team-filter.active {{ background:#111827; color:#fff; border-color:#111827; }}
.team-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; }} .team-card {{ background:#fff; border:1px solid var(--border); border-radius:12px; padding:14px 16px; display:grid; gap:9px; }} .team-card.not-onboarded,.team-card.needs-data {{ background:#fffdf5; border-color:#f59e0b; }} .team-metrics {{ display:flex; gap:8px; flex-wrap:wrap; color:#374151; font-size:12px; }} .team-metrics span,.team-pill {{ display:inline-block; border-radius:999px; padding:2px 8px; background:#eef2ff; color:#3730a3; font-size:12px; font-weight:800; }} .team-action {{ color:#92400e; font-size:12px; font-weight:800; }} .button {{ display:inline-block; padding:7px 10px; border:1px solid #93c5fd; background:#eff6ff; color:#1d4ed8; border-radius:8px; text-decoration:none; font-weight:800; }}
.warning-panel ul {{ margin:0; padding-left:20px; }} .warning-panel li {{ margin:6px 0; }} .domain-section h2 {{ border-bottom:1px solid var(--border); padding-bottom:10px; }} .capability-card {{ margin:14px 0; }} .roadmap-list,.small-list,.cross-list {{ display:grid; gap:10px; }} .roadmap-row,.small-card,.cross-card {{ display:grid; grid-template-columns:minmax(0,1fr) 330px 280px; gap:14px; align-items:start; background:#fff; border:1px solid var(--border); border-radius:12px; padding:14px 16px; }} .cross-card {{ grid-template-columns:minmax(0,1fr) 420px; }} .row-title {{ display:flex; gap:9px; align-items:center; min-width:0; flex-wrap:wrap; }} .row-title b {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .jira-links {{ margin-top:6px; }} .row-plan {{ display:grid; gap:5px; color:#374151; font-size:12px; }} .row-plan b {{ font-size:13px; }} .row-gap {{ font-size:12px; font-weight:800; }} .row-gap.risk {{ color:#92400e; }} .row-gap.ok,.ok-text {{ color:#047857; }} .cross-link-detail {{ font-size:13px; color:#374151; }} .is-hidden {{ display:none !important; }}
@media(max-width:1100px) {{ .kpis {{ grid-template-columns:1fr 1fr; }} .roadmap-row,.small-card,.cross-card {{ grid-template-columns:1fr; }} }} @media(max-width:640px) {{ main {{ padding:16px; }} .kpis {{ grid-template-columns:1fr; }} }}
{shared_dashboard_css()}
</style></head>
<body><main>
<header class="top"><div><h1>{page_title}</h1><div class="muted">{scope_tagline}</div></div><div class="muted">Roadmap Studio <code>{renderer_studio_version}</code><br>Source: repo snapshots · Jira is not accessed while rendering</div></header>
<section class="kpis">{kpi('Teams', f'{onboarded}/{len(team_dirs)}', 'onboarded active/current roadmap teams', onboarded != len(team_dirs))}{kpi('Roadmap Items', f'{matched_total}/{formal_total}', 'formal items matched to Epics', matched_total != formal_total)}{kpi('Small Features', small_total, 'non-roadmap planned release work')}{kpi('Cross-Team Work', len(cross_team_items), f'Epics with `{CROSS_TEAM_LABEL}` label')}{kpi('Plan Changes', plan_change_total, 'Epics with structured plan-change history')}{kpi('Gaps', total_gap_count, 'setup/data/planning gaps', total_gap_count > 0)}</section>
<section class="team-switcher"><h2>Teams <span class="count">filter every section</span></h2><div class="team-filters">{''.join(team_buttons)}</div></section>
<section class="panel"><h2>Team Readiness</h2><div class="team-grid">{''.join(team_cards)}</div></section>
<section class="warning-panel"><h2>Setup / Data Gaps <span class="count">{len(gap_items)} actions</span></h2><ul>{''.join(gap_items) or '<li>No setup or planning gaps detected.</li>'}</ul></section>
<section id="capability-roadmaps"><h2>Capability Roadmaps <span class="count">formal roadmap items by Domain / Capability</span></h2>{''.join(domain_sections) or '<div class="panel">No formal roadmap data available.</div>'}</section>
<section id="themed-features" class="themed-features-section"><header class="section-head"><div><h2>Themed Features <span class="count">{themed_total_epics} Epics · {len(themed_by_initiative)} initiative{'s' if len(themed_by_initiative) != 1 else ''} · 跨 {len(themed_teams)} 个团队 · {themed_cross_count} 跨团队</span></h2><div class="tagline">非正式 roadmap item，但共享同一个 initiative / 主题（KubeOS / Kubernetes 1.35 / New Web Console）。按主题聚合，避免被同主题的 N 份 epic 淹没。标注 <span class="cross-team-badge inline">跨团队</span> 的 Epic 带 <code>{html_escape(CROSS_TEAM_LABEL)}</code> 标签。</div></div></header><div class="initiative-list">{''.join(initiative_cards) or '<div class="muted">No themed-feature initiatives matched.</div>'}</div></section>
<section id="small-features" class="small-section"><h2>Small Features <span class="count">{len(small_rows)} non-roadmap Epics · 未属于任何 initiative 主题</span></h2><div class="small-list">{''.join(small_rows) or '<div class="muted">No un-themed small features.</div>'}</div></section>
<section id="cross-team-work" class="cross-section"><h2>Cross-Team Work <span class="count">{len(cross_rows)} Epics · 未在 Capability Roadmaps 也未在 Themed Features 出现的 cross-team 工作</span></h2><div class="cross-list">{''.join(cross_rows) or '<div class="muted">没有孤立的跨团队 Epic。所有 cross-team work 已在上面 Capability Roadmaps / Themed Features 段内（行内带 <span class="cross-team-badge inline">跨团队</span> 徽章）。</div>'}</div></section>
</main>
<script>document.querySelectorAll('.team-filter').forEach(button => {{ button.addEventListener('click', () => {{ const filter = button.dataset.teamFilter || 'all'; document.querySelectorAll('.team-filter').forEach(item => item.classList.toggle('active', item === button)); document.querySelectorAll('[data-team]').forEach(node => {{ node.classList.toggle('is-hidden', filter !== 'all' && node.dataset.team !== filter); }}); }}); }});</script>
</body></html>'''


def render_progress_html(repo: Path, release_specs: list[tuple[str, str]]) -> str:
    # Unified cross-product PROGRESS report (not capability-grouped, no time axis).
    # Designed as a sprint-progress report: top overview (KPIs + status donut +
    # per-product cards), a product filter bar, then per-product collapsible Epics
    # carrying description + child-task list + owner (assignee = Epic Builder).
    renderer_studio_version = html_escape(ROADMAP_STUDIO_VERSION)
    generated_at = html_escape(dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    status_order = {"In Progress": 0, "To Do": 1, "Done": 2, "Cancelled": 3}
    bucket_order = {"in_progress": 0, "todo": 1, "done": 2, "cancelled": 3}
    pill_bg = {"Done": "#10b981", "In Progress": "#3b82f6", "Cancelled": "#9ca3af", "To Do": "#6b7280"}
    elevated_risk = {"高", "high", "中", "medium", "critical", "严重"}

    def is_elevated_risk(value: Any) -> bool:
        return str(value or "").strip().lower() in elevated_risk

    def epic_status_label(epic: dict[str, Any]) -> str:
        raw = str(epic.get("epic_status") or epic.get("status_name") or "")
        if "cancel" in raw.lower() or "取消" in raw:
            return "Cancelled"
        return normalize_status(raw)

    def clean_desc(text: Any) -> str:
        t = re.sub(r'h[1-6]\.\s*', '', str(text or ''))
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def status_pill(label: str) -> str:
        return f'<span class="status-pill" style="background:{pill_bg.get(label, "#6b7280")}">{html_escape(label)}</span>'

    team_acronyms = {"ai", "ml", "ui", "ux", "api", "maas", "sre", "ci", "cd"}

    def display_team(key: str) -> str:
        # Sub-product display name: title-case each hyphen segment, keep acronyms upper.
        parts = str(key).split("-")
        return "-".join(p.upper() if p.lower() in team_acronyms else (p[:1].upper() + p[1:]) for p in parts)

    def render_epic(epic: dict[str, Any], kids_by_epic: dict[str, list[dict[str, Any]]]) -> str:
        ekey = epic.get("key") or ""
        kids = sorted(kids_by_epic.get(ekey, []), key=lambda c: bucket_order.get(child_status_bucket(c), 1))
        cc = child_counts(kids)
        total = cc["done"] + cc["in_progress"] + cc["todo"]
        percent = pct(cc["done"], total)
        status = epic_status_label(epic)
        owner = html_escape(str(epic.get("assignee") or "未指派"))
        summary = html_escape(str(epic.get("summary") or ""))
        risk_raw = str(epic.get("risk") or "").strip()
        risk_badge = f'<span class="risk-badge" title="Risk">⚠ {html_escape(risk_raw)}</span>' if is_elevated_risk(risk_raw) else ""
        desc = clean_desc(epic.get("description"))
        desc_html = f'<p class="epic-desc">{html_escape(desc[:600])}{"…" if len(desc) > 600 else ""}</p>' if desc else '<p class="epic-desc muted">无描述</p>'
        breakdown = f'<div class="epic-breakdown">完成 {cc["done"]} · 进行中 {cc["in_progress"]} · 待办 {cc["todo"]}' + (f' · 取消 {cc["cancelled"]}' if cc["cancelled"] else '') + '</div>'
        if kids:
            task_rows = "".join(
                f'<div class="task-row task-{child_status_bucket(c)}"><span class="tdot"></span>'
                f'{jira_html(c.get("key") or "")}<span class="task-sum">{html_escape(str(c.get("summary") or ""))}</span>'
                f'<span class="task-st">{html_escape(str(c.get("status_name") or ""))}</span>'
                f'<span class="task-as">{html_escape(str(c.get("assignee") or "未指派"))}</span></div>'
                for c in kids
            )
            tasks_html = f'<div class="task-list">{task_rows}</div>'
        else:
            tasks_html = '<div class="muted" style="padding:6px 0">无子任务</div>'
        return (
            '<details class="epic"><summary class="epic-sum">'
            f'<span class="es-left"><span class="caret">▸</span>{status_pill(status)}{jira_html(ekey)}<b class="es-title">{summary}</b>{risk_badge}</span>'
            f'<span class="es-owner" title="Epic Builder">{owner}</span>'
            f'<span class="es-prog">{progress_bar_html(cc)}</span>'
            f'<span class="es-pct">{percent}%</span><span class="es-cnt">{cc["done"]}/{total}</span>'
            f'</summary><div class="epic-body">{desc_html}{breakdown}{tasks_html}</div></details>'
        )

    def epic_order(epic: dict[str, Any], kids_by_epic: dict[str, list[dict[str, Any]]]) -> tuple[int, int]:
        cc = child_counts(kids_by_epic.get(epic.get("key"), []))
        return (status_order.get(epic_status_label(epic), 1),
                -pct(cc["done"], cc["done"] + cc["in_progress"] + cc["todo"]))

    def area_groups_for(profile: dict[str, Any], epics: list[dict[str, Any]], children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        namer: dict[str, str] = {}
        for st in (profile.get("sub_teams") or []):
            for lab in (st.get("jira_labels") or []):
                namer[str(lab)] = str(st.get("name") or lab)
        groups: dict[str, list[dict[str, Any]]] = {}
        for e in epics:
            lab = next((str(l) for l in (e.get("labels") or []) if str(l).startswith("area-")), "area-unassigned")
            groups.setdefault(lab, []).append(e)
        out: list[dict[str, Any]] = []
        for lab, es in groups.items():
            owner_counts: dict[str, int] = {}
            for e in es:
                a = str(e.get("assignee") or "未指派")
                owner_counts[a] = owner_counts.get(a, 0) + 1
            owner = max(owner_counts, key=owner_counts.get)
            owner_label = owner + (f" +{len(owner_counts) - 1}" if len(owner_counts) > 1 else "")
            out.append({
                "label": lab,
                "name": namer.get(lab, lab.replace("area-", "").replace("-", " ").title() or "未分类"),
                "owner": owner, "owner_label": owner_label,
                "epics": es, "prog": group_progress(es, children),
            })
        out.sort(key=lambda g: g["prog"]["percent"])  # lowest progress first → needs attention
        return out

    products: list[dict[str, Any]] = []
    overall_counts = {"done": 0, "in_progress": 0, "todo": 0, "cancelled": 0}
    epic_tally = {"Done": 0, "In Progress": 0, "To Do": 0, "Cancelled": 0}
    grand_epics = grand_done = grand_active = grand_tasks = at_risk = 0

    for team, version in release_specs:
        meta_path = team_roadmap_root(repo, team) / "releases" / version / "roadmap-meta.yaml"
        if not meta_path.exists():
            products.append({"team": team, "version": version, "missing": True})
            continue
        ctx = load_context_from_meta(repo, meta_path)
        snapshot = load_snapshot(ctx["snapshot_path"])
        epics = list(snapshot.get("issues") or [])
        children = list(snapshot.get("child_issues") or [])
        prog = group_progress(epics, children)
        kids_by_epic: dict[str, list[dict[str, Any]]] = {}
        for c in children:
            kids_by_epic.setdefault(c.get("parent_epic"), []).append(c)
        for key in overall_counts:
            overall_counts[key] += prog["counts"][key]
        grand_epics += len(epics)
        grand_done += prog["counts"]["done"]
        grand_active += prog["active"]
        grand_tasks += sum(prog["counts"].values())
        for epic in epics:
            epic_tally[epic_status_label(epic)] += 1
            if is_elevated_risk(epic.get("risk")):
                at_risk += 1
        products.append({
            "team": team, "version": version, "epics": epics, "children": children,
            "kids_by_epic": kids_by_epic, "prog": prog,
            "area_groups": area_groups_for(ctx["profile"], epics, children),
            "generated": str(snapshot.get("generated_at") or "n/a"),
            "jira_project": ctx.get("jira_project") or "",
        })

    live_products = [p for p in products if not p.get("missing")]
    # When a team contributes more than one release to the view (e.g. hyperflux 1.6 + 1.7
    # both fall in one quarter), disambiguate its filter key + label by version so the two
    # products don't collapse into one ambiguous "Hyperflux" button. Single-release teams
    # keep the plain team key/label.
    team_counts: dict[str, int] = {}
    for p in live_products:
        team_counts[p["team"]] = team_counts.get(p["team"], 0) + 1

    def product_key(p: dict[str, Any]) -> str:
        return p["team"] if team_counts.get(p["team"], 0) <= 1 else f'{p["team"]}:{p["version"]}'

    def short_version(p: dict[str, Any]) -> str:
        v = str(p["version"])
        for pre in (display_team(p["team"]) + "-", str(p["team"]) + "-", display_team(p["team"]) + " "):
            if v.startswith(pre):
                return v[len(pre):]
        return v

    def product_label(p: dict[str, Any]) -> str:
        base = display_team(p["team"])
        return base if team_counts.get(p["team"], 0) <= 1 else f'{base} {short_version(p)}'

    all_areas = sorted(
        ((p, g) for p in live_products for g in p["area_groups"]),
        key=lambda pg: pg[1]["prog"]["percent"],
    )
    overall = pct(grand_done, grand_active)
    overall_total = sum(overall_counts.values()) or 1          # all tasks incl. cancelled — legend distribution
    active_base = grand_active or 1                            # excl. cancelled — completion-ring base, matches KPIs
    done_pct = pct(overall_counts["done"], active_base)
    prog_pct = pct(overall_counts["done"] + overall_counts["in_progress"], active_base)

    def kpi(label: str, value: Any, sub: str, risk: bool = False) -> str:
        cls = "kpi risk" if risk else "kpi"
        return f'<div class="{cls}"><div class="kpi-label">{html_escape(label)}</div><div class="kpi-value">{value}</div><div class="kpi-sub">{html_escape(sub)}</div></div>'

    total_areas = sum(len(p["area_groups"]) for p in live_products)
    kpis = "".join([
        kpi("Overall Progress", f"{overall}%", f"{grand_done}/{grand_active} tasks done"),
        kpi("Areas", total_areas, f"owner-led areas across {len(live_products)} products"),
        kpi("Epics", grand_epics, "tracked Epics"),
        kpi("Tasks", grand_tasks, "child issues under Epics"),
        kpi("In Progress", epic_tally["In Progress"], "Epics actively worked"),
        kpi("Not Started", epic_tally["To Do"], "Epics still To Do"),
        kpi("Done", epic_tally["Done"], "Epics completed"),
    ])

    legend = "".join(
        f'<div class="legend-row"><span class="dot" style="background:{c}"></span><span>{lbl}</span>'
        f'<span class="legend-bar"><span class="legend-fill" style="width:{pct(overall_counts[k], overall_total)}%;background:{c}"></span></span>'
        f'<b>{overall_counts[k]}</b></div>'
        for k, lbl, c in [("done", "Done", "#10b981"), ("in_progress", "In Progress", "#3b82f6"), ("todo", "Todo", "#9ca3af"), ("cancelled", "Cancelled", "#d1d5db")]
    )
    donut = (
        f'<div class="donut" style="background:conic-gradient(#10b981 0 {done_pct}%,#3b82f6 {done_pct}% {prog_pct}%,#9ca3af {prog_pct}% 100%)">'
        f'<div class="donut-hole">{done_pct}%</div></div>'
    )

    area_rows = "".join(
        f'<div class="area-row" data-team="{html_escape(product_key(p))}">'
        f'<span class="ar-prod">{html_escape(product_label(p))}</span>'
        f'<span class="ar-name">{html_escape(g["name"])}</span>'
        f'<span class="ar-owner" title="Area owner (lead assignee)">👤 {html_escape(g["owner_label"])}</span>'
        f'<span class="ar-bar">{progress_bar_html(g["prog"]["counts"])}</span>'
        f'<span class="ar-pct">{g["prog"]["percent"]}%</span>'
        f'<span class="ar-cnt">{len(g["epics"])} Epics</span></div>'
        for p, g in all_areas
    )

    filter_buttons = '<button type="button" class="pfilter active" data-pf="all">All</button>' + "".join(
        f'<button type="button" class="pfilter" data-pf="{html_escape(product_key(p))}">{html_escape(product_label(p))} ({len(p["epics"])})</button>'
        for p in products if not p.get("missing")
    )

    sections: list[str] = []
    first_open_done = False
    for p in products:
        if p.get("missing"):
            sections.append(
                f'<details class="product"><summary class="prod-head"><span class="caret">▸</span>'
                f'<div><h2>{html_escape(display_team(p["team"]))} <code>{html_escape(p["version"])}</code></h2>'
                f'<div class="muted">release meta not found</div></div></summary></details>'
            )
            continue
        team, version, prog, kids_by_epic = p["team"], p["version"], p["prog"], p["kids_by_epic"]
        area_blocks: list[str] = []
        for g in p["area_groups"]:
            ap = g["prog"]
            epic_html = "".join(
                render_epic(e, kids_by_epic)
                for e in sorted(g["epics"], key=lambda e: epic_order(e, kids_by_epic))
            )
            area_blocks.append(
                f'<details class="area">'
                f'<summary class="area-head"><span class="caret">▸</span>'
                f'<span class="area-name">{html_escape(g["name"])}</span>'
                f'<span class="owner-badge" title="Area owner (lead assignee)">👤 {html_escape(g["owner_label"])}</span>'
                f'<span class="area-cnt muted">{len(g["epics"])} Epics</span>'
                f'<span class="area-bar">{progress_bar_html(ap["counts"])}</span>'
                f'<span class="area-pct">{ap["percent"]}%</span></summary>'
                f'<div class="epic-list">{epic_html}</div></details>'
            )
        area_html = "".join(area_blocks) or '<div class="muted">No Epics in snapshot.</div>'
        in_progress_n = sum(1 for e in p["epics"] if epic_status_label(e) == "In Progress")
        open_attr = "" if first_open_done else " open"
        first_open_done = True
        sections.append(
            f'<details class="product" data-team="{html_escape(product_key(p))}"{open_attr}>'
            f'<summary class="prod-head"><span class="caret">▸</span>'
            f'<div><h2>{html_escape(display_team(team))} <code>{html_escape(version)}</code> '
            f'<span class="muted">· {html_escape(p["jira_project"])}</span></h2>'
            f'<div class="muted">{len(p["epics"])} Epics · {len(p["area_groups"])} areas · {prog["percent"]}% done · '
            f'{prog["counts"]["done"]}/{prog["active"]} tasks · In Progress {in_progress_n} · snapshot {html_escape(p["generated"])}</div></div>'
            f'<span class="prod-pct">{prog["percent"]}%</span></summary>'
            f'<div class="area-list">{area_html}</div></details>'
        )

    css = (
        ":root{--bg:#f8fafc;--panel:#fff;--border:#e5e7eb;--text:#111827;--muted:#6b7280;--shadow:0 1px 3px rgba(0,0,0,.05)}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;line-height:1.5}"
        "main{max-width:1240px;margin:0 auto;padding:24px}"
        "header.top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;border-bottom:1px solid var(--border);padding-bottom:16px;margin-bottom:18px;flex-wrap:wrap}"
        "h1{margin:0;font-size:27px;letter-spacing:-.02em}h2{margin:0;font-size:19px}"
        "a{color:#2563eb;text-decoration:none;font-family:ui-monospace,monospace;font-weight:800}a:hover{text-decoration:underline}"
        ".muted{color:var(--muted);font-size:12px;font-weight:400}"
        ".kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}"
        ".kpi{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}"
        ".kpi.risk{background:#fffbeb;border-color:#f59e0b}"
        ".kpi-label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em;font-weight:800}"
        ".kpi-value{font-size:28px;font-weight:800;line-height:1.1;margin-top:4px}.kpi-sub{color:var(--muted);font-size:12px;margin-top:3px}"
        ".grid-2{display:grid;grid-template-columns:340px 1fr;gap:16px;margin-bottom:18px}"
        ".panel{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow)}"
        ".donut-wrap{display:grid;grid-template-columns:150px 1fr;gap:18px;align-items:center}"
        ".donut{width:140px;height:140px;border-radius:50%;position:relative}"
        ".donut-hole{position:absolute;inset:30px;background:#fff;border-radius:50%;display:grid;place-items:center;font-size:24px;font-weight:800}"
        ".legend-row{display:grid;grid-template-columns:12px 84px 1fr 34px;align-items:center;gap:8px;margin:7px 0}"
        ".dot{width:10px;height:10px;border-radius:50%}.legend-bar{height:7px;background:#e5e7eb;border-radius:999px;overflow:hidden}.legend-fill{display:block;height:100%}"
        ".area-scorecard{display:grid;gap:6px;max-height:340px;overflow:auto}"
        ".area-row{display:grid;grid-template-columns:92px minmax(0,1fr) 132px 100px 40px 60px;gap:10px;align-items:center;padding:7px 8px;border:1px solid var(--border);border-radius:9px;font-size:13px}.area-row.is-hidden{display:none}"
        ".ar-prod{color:#3730a3;background:#eef2ff;border-radius:999px;padding:1px 8px;font-size:11px;font-weight:800;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".ar-name{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ar-owner{color:#374151;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".ar-pct{font-weight:800;text-align:right}.ar-cnt{color:var(--muted);font-size:12px;text-align:right;white-space:nowrap}"
        ".area-list{display:grid;gap:8px;padding-top:2px}"
        ".area{border:1px solid var(--border);border-radius:10px;background:#fcfcfd}.area[open]{border-color:#c7d2fe;background:#fff}"
        ".area-head{display:grid;grid-template-columns:auto minmax(0,1fr) auto auto 132px 46px;gap:10px;align-items:center;padding:9px 12px;cursor:pointer;list-style:none}"
        ".area-head::-webkit-details-marker{display:none}.area[open]>.area-head{border-bottom:1px solid var(--border)}"
        ".area-name{font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".owner-badge{background:#ecfdf5;color:#047857;border:1px solid #a7f3d0;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:800;white-space:nowrap}"
        ".area-cnt{font-size:12px;color:var(--muted);white-space:nowrap}.area-pct{font-weight:800;text-align:right;color:#1d4ed8}"
        ".area .epic-list{padding:10px 12px}"
        ".filterbar{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--border);margin-bottom:14px}"
        ".pfilter{border:1px solid var(--border);background:#fff;border-radius:999px;padding:7px 13px;cursor:pointer;font-weight:800}.pfilter.active{background:#111827;color:#fff;border-color:#111827}"
        ".tools{margin-left:auto;display:flex;gap:8px}.tool{border:1px solid var(--border);background:#fff;border-radius:8px;padding:6px 10px;cursor:pointer;font-weight:700;font-size:12px}"
        ".product{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:16px;box-shadow:var(--shadow)}"
        ".product.is-hidden{display:none}"
        ".prod-head{display:flex;align-items:center;gap:12px;cursor:pointer;list-style:none;padding-bottom:12px}.product[open]>.prod-head{border-bottom:1px solid var(--border);margin-bottom:10px}"
        ".prod-head::-webkit-details-marker{display:none}.prod-head h2{margin:0}"
        ".prod-pct{margin-left:auto;font-size:26px;font-weight:800;color:#1d4ed8}"
        ".caret{display:inline-block;transition:transform .15s;color:var(--muted);font-size:11px;flex-shrink:0}details[open]>summary .caret{transform:rotate(90deg)}"
        ".risk-badge{background:#fef3c7;color:#92400e;border-radius:999px;padding:1px 8px;font-size:11px;font-weight:800;white-space:nowrap;flex-shrink:0}"
        ".epic-breakdown{color:var(--muted);font-size:12px;margin:0 0 8px}"
        ".epic-list{display:grid;gap:7px}"
        ".epic{border:1px solid var(--border);border-radius:10px;overflow:hidden}.epic[open]{border-color:#bfdbfe;box-shadow:0 1px 4px rgba(37,99,235,.10)}"
        ".epic-sum{display:grid;grid-template-columns:minmax(0,1fr) 130px 150px 42px 50px;gap:10px;align-items:center;padding:9px 12px;cursor:pointer;list-style:none}"
        ".epic-sum::-webkit-details-marker{display:none}.epic[open] .epic-sum{background:#f8fafc;border-bottom:1px solid var(--border)}"
        ".es-left{display:flex;gap:8px;align-items:center;min-width:0}.es-title{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".es-owner{color:#374151;font-size:12px;font-weight:700;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".es-pct{font-weight:800;text-align:right}.es-cnt{color:var(--muted);font-size:12px;text-align:right}"
        ".status-pill{display:inline-block;border-radius:999px;padding:2px 9px;font-size:11px;font-weight:800;color:#fff;white-space:nowrap}"
        ".progress-bar{height:9px;display:flex;overflow:hidden;background:#e5e7eb;border-radius:999px}.progress-bar span{display:block;height:100%}"
        ".epic-body{padding:12px 14px;background:#fff}.epic-desc{margin:0 0 10px;color:#374151;font-size:13px}"
        ".task-list{display:grid;gap:4px}"
        ".task-row{display:grid;grid-template-columns:12px 90px minmax(0,1fr) 120px 120px;gap:8px;align-items:center;font-size:12px;padding:4px 0;border-top:1px dashed var(--border)}"
        ".task-sum{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.task-st,.task-as{color:var(--muted)}"
        ".tdot{width:9px;height:9px;border-radius:50%;background:#9ca3af}.task-done .tdot{background:#10b981}.task-in_progress .tdot{background:#3b82f6}.task-cancelled .tdot{background:#d1d5db}"
        "@media(max-width:900px){.kpis{grid-template-columns:1fr 1fr}.grid-2{grid-template-columns:1fr}.epic-sum{grid-template-columns:minmax(0,1fr) auto auto;gap:8px}.es-prog,.es-cnt{display:none}.task-row{grid-template-columns:12px auto 1fr}.task-st,.task-as{display:none}.area-row{grid-template-columns:minmax(0,1fr) auto auto;gap:6px}.ar-prod,.ar-bar,.ar-cnt{display:none}.area-head{grid-template-columns:auto minmax(0,1fr) auto auto;gap:8px}.area-bar,.area-cnt{display:none}}"
    )
    js = (
        "document.querySelectorAll('.pfilter').forEach(b=>b.addEventListener('click',()=>{"
        "const f=b.dataset.pf;document.querySelectorAll('.pfilter').forEach(x=>x.classList.toggle('active',x===b));"
        "document.querySelectorAll('.product[data-team],.area-row[data-team]').forEach(s=>s.classList.toggle('is-hidden',f!=='all'&&s.dataset.team!==f));}));"
        "document.querySelectorAll('[data-toolall]').forEach(b=>b.addEventListener('click',()=>{"
        "const open=b.dataset.toolall==='open';"
        "if(open){document.querySelectorAll('.product:not(.is-hidden)').forEach(d=>d.open=true);}"
        "document.querySelectorAll('.product:not(.is-hidden) details.epic').forEach(d=>d.open=open);}));"
    )
    return (
        '<!doctype html>\n<html lang="zh-CN">\n<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="roadmap-studio-version" content="{renderer_studio_version}">'
        '<title>2026Q3 Unified Roadmap Progress</title>\n'
        f'<style>{css}</style></head>\n<body><main>\n'
        '<header class="top"><div><h1>2026Q3 Unified Roadmap Progress</h1>'
        '<div class="muted">Cross-product Epic progress — status · child-task completion · Epic Builder. '
        f'Generated {generated_at}</div></div>'
        f'<div class="muted">Roadmap Studio <code>{renderer_studio_version}</code><br>Source: repo snapshots · no time axis (Epic dates not set)</div></header>\n'
        f'<section class="kpis">{kpis}</section>\n'
        f'<section class="grid-2"><div class="panel"><h2>Task Status <span class="muted">{grand_tasks} tasks</span></h2>'
        f'<div class="donut-wrap">{donut}<div class="legend">{legend}</div></div></div>'
        f'<div class="panel"><h2>By Area <span class="muted">{total_areas} areas · owner-led · 按进度升序(最落后在前)</span></h2><div class="area-scorecard">{area_rows}</div></div></section>\n'
        f'<nav class="filterbar">{filter_buttons}<span class="tools"><button type="button" class="tool" data-toolall="open">展开全部</button>'
        '<button type="button" class="tool" data-toolall="close">收起全部</button></span></nav>\n'
        f'{"".join(sections)}\n'
        f'</main>\n<script>{js}</script>\n</body></html>'
    )


def render_index_md(repo: Path) -> str:
    rows: list[str] = []
    gaps: list[str] = []
    for team_key in available_team_keys(repo):
        roadmap_root = team_roadmap_root(repo, team_key)
        profile_path = roadmap_root / "team-profile.yaml"
        if not roadmap_root.exists():
            rows.append(f"| {team_key} | Not onboarded | Missing | Missing | Missing | Missing |")
            gaps.append(f"- `{team_key}`: create roadmap/team-profile.yaml, releases/<version>/roadmap-meta.yaml, and roadmap.md")
            continue
        if not profile_path.exists():
            rows.append(f"| {team_key} | `{repo_relative_path(repo, roadmap_root)}` | Missing | Missing | Missing | Missing |")
            gaps.append(f"- `{team_key}`: create `{repo_relative_path(repo, profile_path)}`")
            continue
        metas = sorted(roadmap_root.glob("releases/*/roadmap-meta.yaml"))
        active = [
            meta for meta in metas
            if (load_yaml(meta) or {}).get("role") == "current"
            or (load_yaml(meta) or {}).get("status") == "active"
        ]
        if not active:
            rows.append(f"| {team_key} | `{repo_relative_path(repo, roadmap_root)}` | `team-profile.yaml` | Missing active/current release | Missing | Missing |")
            gaps.append(f"- `{team_key}`: create or activate `releases/<version>/roadmap-meta.yaml`")
            continue
        meta_path = active[0]
        try:
            ctx = load_context_from_meta(repo, meta_path)
        except Exception as exc:
            rows.append(f"| {team_key} | `{repo_relative_path(repo, roadmap_root)}` | `team-profile.yaml` | Invalid release meta | Missing | Missing |")
            gaps.append(f"- `{team_key}`: fix `{repo_relative_path(repo, meta_path)}` ({exc})")
            continue
        snapshot = load_snapshot(ctx["snapshot_path"])
        snapshot_at = str(snapshot.get("generated_at") or "not available")
        dashboard = ctx["gantt_path"]
        snapshot_studio_version = snapshot_roadmap_studio_version(snapshot)
        rows.append(
            f"| {team_key} | `{repo_relative_path(repo, roadmap_root)}` | `team-profile.yaml` | "
            f"`releases/{ctx['version']}` | `{dashboard.relative_to(roadmap_root)}` | `{snapshot_studio_version}` |"
        )
        if not ctx["roadmap_path"].exists():
            gaps.append(f"- `{team_key}`: maintain `{repo_relative_path(repo, ctx['roadmap_path'])}`")
        if not ctx["snapshot_path"].exists():
            gaps.append(f"- `{team_key}`: refresh snapshot at `{repo_relative_path(repo, ctx['snapshot_path'])}`")
        elif not snapshot.get("issues"):
            gaps.append(f"- `{team_key}`: snapshot has no issues; check Jira labels or refresh snapshot")
        if snapshot_at == "not available":
            gaps.append(f"- `{team_key}`: snapshot generated time is not available")

    generated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "# Roadmap Studio Index",
        "",
        "This index is the repo-level discovery surface for AI agents and humans.",
        "It points to onboarded Roadmap Studio teams, their source files, and their latest generated views.",
        "",
        "The index is generated by `builders-roadmap-studio render-dashboard`; do not hand-edit it.",
        f"Generated at: `{generated_at}`",
        f"Roadmap Studio version: `{ROADMAP_STUDIO_VERSION}`",
        "",
        "## Skill And Contract",
        "",
        f"- Skill version: `{ROADMAP_STUDIO_VERSION}` (`{ROADMAP_STUDIO_VERSION_SCHEME}`)",
        "- Skill entrypoint: `builders/skills/builders-roadmap-studio/SKILL.md`",
        "- Operating model and durable rules: `builders/skills/builders-roadmap-studio/references/roadmap-studio-operating-model.md`",
        "",
        "## Registered Teams",
        "",
        "| Team | Roadmap Root | Team Profile | Current Release | Team Dashboard | Snapshot Studio Version |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
        "## File Roles",
        "",
        "- `team-profile.yaml`: team-level Jira project, Jira boards, sub-team labels, lanes, and display people.",
        "- `releases/<version>/roadmap-meta.yaml`: release entrypoint, sprint window, and generated output paths.",
        "- `releases/<version>/roadmap.md`: release roadmap source-of-truth.",
        "- `releases/<version>/roadmap-changelog.md`: semantic roadmap commitment changes.",
        "- `releases/<version>/snapshots/jira-execution-snapshot.yaml`: latest generated Jira execution snapshot, including StartAfter, Due Date, Risk, links, and real plan-change comments.",
        "- `releases/<version>/snapshots/roadmap-gantt.html`: latest generated team Roadmap Dashboard.",
        f"- `{repo_relative_path(repo, builders_dashboard_path(repo))}`: cross-team Roadmap Dashboard generated from team snapshots.",
        "",
        "## Setup / Data Gaps",
        "",
        *(gaps or ["- None"]),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_diagnose(ctx: dict[str, Any], with_jira: bool = False) -> str:
    missing = []
    for label, path in [("team profile", ctx["profile_path"]), ("release meta", ctx["meta_path"]), ("roadmap", ctx["roadmap_path"]), ("changelog", ctx["changelog_path"]), ("snapshot", ctx["snapshot_path"] )]:
        if not path.exists():
            missing.append(f"{label}: `{path}`")
    items = parse_roadmap_items(ctx["roadmap_path"], ctx["version"]) if ctx["roadmap_path"].exists() else []
    snapshot = ctx.get("_diagnose_snapshot_override") or load_snapshot(ctx["snapshot_path"])
    issues = list(snapshot.get("issues") or [])
    small, unclassified = attach_epics(items, issues, ctx["version"], own_project=ctx.get("jira_project"))
    matched_items = sum(1 for item in items if item.epics)
    sub_team_names = [str(team.get("name")) for team in (ctx["profile"].get("sub_teams") or []) if team.get("name")]
    external_projects = external_jira_projects(ctx["profile"])
    external_project_label = ", ".join(f"`{item['team']}={item['project']}`" for item in external_projects) or "`None`"
    data_source = "live Jira" if with_jira and ctx.get("_diagnose_snapshot_override") else "repo snapshot"
    sprint_board = ((ctx["profile"].get("jira_boards") or {}).get("sprint") or {})
    if isinstance(sprint_board, dict) and sprint_board.get("id"):
        sprint_board_name = sprint_board.get("name") or "unknown"
        sprint_board_label = f"{sprint_board_name} ({sprint_board.get('id')})"
    else:
        sprint_board_label = "not configured"
    sprints = sprint_windows(ctx)
    plan_gap_items = [item for item in items if plan_gap_text(item.epics, ctx, sprints) != "信息完整"]
    small_gap_items = [issue for issue in small if issue_gap_text(issue, ctx, sprints) != "信息完整"]
    plan_changed_issues = [issue for issue in issues if change_logged(issue)]
    gaps_by_team = collect_gap_actions(plan_gap_items, small_gap_items, ctx["profile"], ctx, sprints)
    if missing or matched_items != len(items) or unclassified:
        conclusion = "Needs structure or label review"
    elif plan_gap_items or small_gap_items:
        conclusion = "Needs planning input"
    else:
        conclusion = "Ready"

    lines = [
        f"# Roadmap Studio Diagnose - {ctx['version']}",
        "",
        "## Scope",
        "",
        f"- Team: `{ctx['profile'].get('team_key') or 'unknown'}`",
        f"- Jira Project: `{ctx['jira_project'] or 'unknown'}`",
        f"- External Jira Projects: {external_project_label}",
        f"- Jira Sprint Board: `{sprint_board_label}`",
        f"- Release: `{ctx['version']}` (`{ctx['meta'].get('status', 'unknown')}` / `{ctx['meta'].get('role', 'unknown')}`)",
        f"- Sub-teams: {', '.join(f'`{name}`' for name in sub_team_names) or '`None`'}",
        f"- Data source: `{data_source}`",
        f"- Snapshot generated_at: `{snapshot.get('generated_at', 'not available')}`",
        f"- Snapshot Roadmap Studio version: `{snapshot_roadmap_studio_version(snapshot)}`",
        f"- Current Roadmap Studio version: `{ROADMAP_STUDIO_VERSION}`",
        "",
        "## Conclusion",
        "",
        f"- Result: `{conclusion}`",
        f"- Formal roadmap items matched to Epics: `{matched_items}/{len(items)}`",
        f"- Small-feature Epics: `{len(small)}`",
        f"- Unclassified roadmap work: `{len(unclassified)}`",
        f"- Missing source files: `{len(missing)}`",
        f"- Roadmap / planning information gaps: `{len(plan_gap_items) + len(small_gap_items)}`",
        f"- Plan changed Epics: `{len(plan_changed_issues)}`",
        "",
        "## Meaning",
        "",
        "- Roadmap/Epic discovery is healthy only when formal roadmap items can match Jira Epics and unclassified work is 0.",
        f"- Planning is not complete while any Epic lacks `StartAfter` / `Due Date`, carries `{PLAN_DEVIATION_LABEL}` without a structured change comment, or exceeds the code-freeze window without `{LANE_AGNOSTIC_LABEL}`.",
        f"- `{PLAN_DEVIATION_LABEL}` marks Epics whose plan changed and should be filterable during sprint/release review.",
        f"- `{LANE_AGNOSTIC_LABEL}` marks fully Agnostic Extension Epics whose target may fall in the post-release extension window.",
        "- If you are a sub-team PM or engineering manager, start from the sections below for missing input and recorded plan changes.",
        "",
        "## What Needs Human Input",
        "",
    ]
    if gaps_by_team:
        for team, values in sorted(gaps_by_team.items()):
            lines.append(f"### {team}")
            lines.extend(f"- {value}" for value in values)
            lines.append("")
    else:
        lines.append("- None. Snapshot has enough Jira plan fields for the currently discovered work.")
        lines.append("")
    lines += [
        "## Plan Changed",
        "",
    ]
    if plan_changed_issues:
        for issue in sorted(plan_changed_issues, key=lambda item: item.get("key") or ""):
            lines.extend(plan_change_markdown_lines(issue) or [f"- {jira_md(issue.get('key') or '')}: plan changed"])
    else:
        lines.append("- None")
    lines.append("")
    lines += [
        "## Label Rules",
        "",
        f"- Version label: `{ctx['version_label']}` identifies the ACP minor version scope.",
        f"- Roadmap item labels: `roadmap:{ctx['version']}:<slug>` map Epics to formal roadmap items.",
        f"- Small features label: `{ctx['small_features_label']}` marks planned non-roadmap work in this cycle.",
        "- Sub-team labels come from `team-profile.yaml` and drive team-internal sprint planning.",
        "- External Jira projects come from `team-profile.yaml` and identify cross-team Epic ownership; they do not replace Jira issue links.",
        "- Scenario labels use `scenario:<slug>` for grouping only.",
        f"- Plan deviation label: `{PLAN_DEVIATION_LABEL}` marks Epics with recorded plan changes for Jira filtering and review.",
        f"- Lane label: `{LANE_AGNOSTIC_LABEL}` marks Epics that are fully Agnostic Extensions and may target the extension release window.",
        "- Ignored label: `team_label_added`.",
        "",
        "## Roadmap Items",
        "",
        "| Item | Generated Label Candidate | Matching Epics | Status |",
        "|---|---|---|---|",
    ]
    for item in items:
        epics = ", ".join(jira_md(issue.get("key") or "") for issue in item.epics) or "None"
        lines.append(f"| {item.roadmap_id} {item.title} | `{item.expected_label}` | {epics} | {item_status(item)} |")
    lines += [
        "",
        "## Non-Roadmap Planned Work",
        "",
        f"Small-features: {', '.join(jira_md(issue.get('key') or '') for issue in small) or 'None'}",
        "",
        "## Unclassified Roadmap Work",
        "",
        ", ".join(jira_md(issue.get("key") or "") for issue in unclassified) or "None",
        "",
        "## Source Files",
        "",
        f"- Team profile: `{ctx['profile_path'].resolve()}`",
        f"- Release meta: `{ctx['meta_path'].resolve()}`",
        f"- Roadmap: `{ctx['roadmap_path'].resolve()}`",
        f"- Changelog: `{ctx['changelog_path'].resolve()}`",
        f"- Snapshot: `{ctx['snapshot_path'].resolve()}`",
    ]
    if missing:
        lines += ["", "## Missing Sources", ""] + [f"- {item}" for item in missing]
    return "\n".join(lines) + "\n"


def render_label_audit(ctx: dict[str, Any], snapshot: dict[str, Any]) -> str:
    version = ctx["version"]
    items = parse_roadmap_items(ctx["roadmap_path"], version)
    issues = list(snapshot.get("issues") or [])
    small, unclassified = attach_epics(items, issues, version, own_project=ctx.get("jira_project"))
    deprecated: list[str] = []
    missing_team: list[str] = []
    missing_deviation_label: list[str] = []
    missing_change_comment: list[str] = []
    agnostic_epics: list[str] = []
    team_labels = sub_team_labels(ctx["profile"])
    action_count = 0
    for issue in issues:
        labels = set(issue.get("labels") or [])
        for label in labels:
            if label.startswith("roadmap-item-") or label == "bare-metal-delivery-scenario":
                deprecated.append(f"{issue.get('key')}: {label}")
        if not is_external_issue(issue, ctx["profile"]) and not labels.intersection(team_labels):
            missing_team.append(str(issue.get("key")))
        if change_logged(issue) and PLAN_DEVIATION_LABEL not in labels:
            missing_deviation_label.append(str(issue.get("key")))
        if PLAN_DEVIATION_LABEL in labels and not change_logged(issue):
            missing_change_comment.append(str(issue.get("key")))
        if LANE_AGNOSTIC_LABEL in labels:
            agnostic_epics.append(str(issue.get("key")))
    lines = [f"# Roadmap Label Audit - {version}", "", f"Snapshot: `{snapshot.get('generated_at', 'not available')}`", f"Roadmap Studio version: `{ROADMAP_STUDIO_VERSION}`", f"Snapshot Roadmap Studio version: `{snapshot_roadmap_studio_version(snapshot)}`", "", "## Add/Fix Actions", ""]
    for item in items:
        if not item.epics:
            lines.append(f"- Review: `{item.expected_label}` has no matching Epic in snapshot for {item.roadmap_id} {item.title}.")
            action_count += 1
    for issue in unclassified:
        lines.append(f"- Review: {jira_md(issue.get('key') or '')} has formal roadmap label but does not match roadmap.md generated labels or existing planning hint.")
        action_count += 1
    for key in missing_team:
        lines.append(f"- Add sub-team label: {jira_md(key)} has no configured sub-team label.")
        action_count += 1
    for key in missing_deviation_label:
        lines.append(f"- Add `{PLAN_DEVIATION_LABEL}`: {jira_md(key)} has a structured plan-change comment but is not filterable by the deviation label.")
        action_count += 1
    for key in missing_change_comment:
        lines.append(f"- Add `{ROADMAP_CHANGE_MARKER}` comment: {jira_md(key)} has `{PLAN_DEVIATION_LABEL}` but no structured change history in snapshot.")
        action_count += 1
    if action_count == 0:
        lines.append("- None")
    lines += ["", "## Agnostic Extension Lane", ""]
    if agnostic_epics:
        lines.append(f"- `{LANE_AGNOSTIC_LABEL}` Epics: " + ", ".join(jira_md(key) for key in sorted(agnostic_epics)))
        lines.append("- Governance: these Epics must be fully Agnostic Extensions. Split Core/Aligned work into separate Epics before using this label.")
    else:
        lines.append(f"- None. Add `{LANE_AGNOSTIC_LABEL}` only for Epics that are fully Agnostic Extensions.")
    lines += ["", "## Deprecated Cleanup Candidates", ""]
    lines += [f"- {item}" for item in deprecated] or ["- None"]
    lines += ["", "## Small Features", ""]
    lines += [f"- {jira_md(issue.get('key') or '')}: {issue.get('summary') or ''}" for issue in small] or ["- None"]
    return "\n".join(lines) + "\n"


def render_change_comment_template(issue: dict[str, Any], field: str, old: str, new: str, sprint: str) -> str:
    owner = issue.get("assignee") or "<owner>"
    return "\n".join([
        ROADMAP_CHANGE_MARKER,
        f"sprint: {sprint or '<sprint>'}",
        f"changed: {field}",
        f"from: {old or '<empty>'}",
        f"to: {new or '<new value>'}",
        f"owner: {owner}",
        "reason: <变更缘由>",
        "notes: []",
        ROADMAP_CHANGE_END_MARKER,
    ])


def delivery_expectation_present(description: str) -> bool:
    text = str(description or "").lower()
    markers = ["roadmap studio delivery expectation", "delivery expectation", "definition of done", "交付", "验收", "scope", "范围", "产出", "目标", "完成"]
    return any(marker in text for marker in markers)


def migration_preview_for_issue(issue: dict[str, Any], sprints: list[dict[str, str]], version: str) -> list[str]:
    plan = issue_plan(issue)
    lines = [f"### {issue.get('key')} {issue.get('summary') or ''}", ""]
    actions = []
    legacy_start = normalize_sprint_name(plan.get("start_sprint"), version)
    legacy_target = normalize_sprint_name(plan.get("target_sprint"), version)
    suggested_start = sprint_start_date(sprints, legacy_start) if legacy_start and legacy_start != "TBD" else ""
    suggested_due = sprint_end_date(sprints, legacy_target) if legacy_target and legacy_target != "TBD" else ""
    date_change_needed = False
    labels = set(issue.get("labels") or [])
    if not issue.get("start_after") and suggested_start:
        date_change_needed = True
        actions.append(f"- Set `StartAfter` (`{JIRA_START_AFTER_FIELD}`): `{suggested_start}` from existing planning hint `{legacy_start}`")
    elif not issue.get("start_after"):
        actions.append("- Planning input needed: StartAfter is missing and no existing start date hint was found")
    if not issue.get("due_date") and suggested_due:
        date_change_needed = True
        actions.append(f"- Set `Due Date` (`duedate`): `{suggested_due}` from existing planning hint `{legacy_target}`")
    elif not issue.get("due_date"):
        actions.append("- Planning input needed: Due Date is missing and no existing target date hint was found")
    if PLAN_DEVIATION_LABEL in labels and not change_logged(issue):
        actions.append(f"- Add `{ROADMAP_CHANGE_MARKER}` comment: `{PLAN_DEVIATION_LABEL}` is set but no structured change history exists")
    if change_logged(issue) and PLAN_DEVIATION_LABEL not in labels:
        actions.append(f"- Add `{PLAN_DEVIATION_LABEL}`: structured plan-change history exists and should be filterable")
    if not issue.get("risk"):
        actions.append(f"- Review `Risk` (`{JIRA_RISK_FIELD}`): confirm `无` or set to `低 / 高`")
    if not delivery_expectation_present(issue.get("description") or ""):
        outcome = compact_text(plan.get("target_outcome") or "", 240)
        actions.append("- Append delivery expectation section to Epic description" + (f": {outcome}" if outcome else ""))
    if not actions:
        actions.append("- No source-of-truth action needed.")
    lines.extend(actions)
    lines.append("")
    return lines


def render_migration_preview(ctx: dict[str, Any], snapshot: dict[str, Any]) -> str:
    version = ctx["version"]
    sprints = sprint_windows(ctx)
    items = parse_roadmap_items(ctx["roadmap_path"], version) if ctx["roadmap_path"].exists() else []
    issues = list(snapshot.get("issues") or [])
    small, unclassified = attach_epics(items, issues, version, own_project=ctx.get("jira_project"))
    ordered: list[dict[str, Any]] = []
    for item in items:
        ordered.extend(item.epics)
    ordered.extend(small)
    ordered.extend(unclassified)
    seen: set[str] = set()
    deduped = []
    for issue in ordered:
        key = issue.get("key") or ""
        if key and key not in seen:
            seen.add(key)
            deduped.append(issue)
    lines = [
        f"# Roadmap Studio Source-Of-Truth Preview - {version}",
        "",
        f"Roadmap Studio version: `{ROADMAP_STUDIO_VERSION}`",
        f"Snapshot Roadmap Studio version: `{snapshot_roadmap_studio_version(snapshot)}`",
        "",
        "This is read-only. It does not write Jira or repo files.",
        "",
        "## Contract",
        "",
        f"- Plan dates: `StartAfter` (`{JIRA_START_AFTER_FIELD}`) and `Due Date` (`duedate`).",
        f"- Risk field: `Risk` (`{JIRA_RISK_FIELD}`) with values `无 / 低 / 高`.",
        f"- Deviation label: `{PLAN_DEVIATION_LABEL}` marks confirmed plan changes for Jira filtering and review.",
        "- Comments are not the plan fact source; add comments only for real plan changes or necessary human notes.",
        "",
        "## Suggested Actions",
        "",
    ]
    for issue in deduped:
        lines.extend(migration_preview_for_issue(issue, sprints, version))
    return "\n".join(lines).rstrip() + "\n"


def freeze_paths(snapshot_path: Path, gantt_path: Path, sprint: str | None) -> tuple[Path, Path]:
    if not sprint:
        return snapshot_path, gantt_path
    return snapshot_path.with_name(f"{snapshot_path.stem}-{sprint}{snapshot_path.suffix}"), gantt_path.with_name(f"{gantt_path.stem}-{sprint}{gantt_path.suffix}")


def freeze_artifact_path(path: Path, sprint: str | None) -> Path:
    if not sprint:
        return path
    return path.with_name(f"{path.stem}-{sprint}{path.suffix}")


def render_progress_gantt(ctx: dict[str, Any], snapshot_path: Path, output: Path | None = None) -> Path | None:
    output = output or ctx.get("progress_gantt_path")
    if not output:
        return None
    output = Path(output)
    script = Path(__file__).with_name("render_timeline_gantt.py")
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--snapshot",
            str(snapshot_path),
            "--profile",
            str(ctx["profile_path"]),
            "--release-meta",
            str(ctx["meta_path"]),
            "--output",
            str(output),
            "--title",
            f"{ctx['version']} Progress Gantt",
            "--renderer-version",
            ROADMAP_STUDIO_VERSION,
        ],
        check=True,
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Roadmap Studio snapshot and HTML helper")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("diagnose", "label-audit", "migration-preview", "refresh-snapshot", "render-gantt", "render-timeline-gantt", "render-dashboard", "render-progress", "version-info"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--version")
        cmd.add_argument("--team")
        cmd.add_argument("--repo")
        cmd.add_argument("--sub-team")
        cmd.add_argument("--with-jira", action="store_true")
        cmd.add_argument("--snapshot")
        cmd.add_argument("--output")
        cmd.add_argument("--freeze-sprint")
        cmd.add_argument("--teams", help="render-dashboard only: comma-separated team scope for a combined overview, e.g. app-service,ai-platform,hyperflux")
        cmd.add_argument("--releases", help="render-progress only: comma-separated team=version specs, e.g. app-service=2026Q3,ai-platform=AI-2026Q3,hyperflux=Hyperflux-1.7")
    args = parser.parse_args()
    if args.command == "version-info":
        print(f"{roadmap_studio_version_line()} ({ROADMAP_STUDIO_VERSION_SCHEME})")
        return 0
    repo = resolve_builders_repo(args.repo)
    if args.command == "render-progress":
        specs: list[tuple[str, str]] = []
        for raw in (args.releases or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            if "=" not in raw:
                raise SystemExit(f"--releases entry must be team=version, got: {raw!r}")
            team, version = raw.split("=", 1)
            specs.append((team.strip(), version.strip()))
        if not specs:
            raise SystemExit("render-progress requires --releases team=version,... (e.g. app-service=2026Q3,ai-platform=AI-2026Q3,hyperflux=Hyperflux-1.7)")
        output = Path(args.output).expanduser().resolve() if args.output else dashboard_output_root(repo) / "roadmap-q3-unified-progress.html"
        write_text(output, render_progress_html(repo, specs))
        print(f"UNIFIED PROGRESS ({', '.join(f'{t}/{v}' for t, v in specs)}): wrote {output}")
        return 0
    if args.command == "render-dashboard":
        teams = [t for t in (args.teams or "").split(",") if t.strip()] or None
        if teams:
            output = (
                Path(args.output).expanduser().resolve()
                if args.output
                else dashboard_output_root(repo) / f"roadmap-combined-{'-'.join(teams)}.html"
            )
            write_text(output, render_dashboard_html(repo, output, teams=teams))
            print(f"COMBINED PROGRESS OVERVIEW ({', '.join(teams)}): wrote {output}")
            return 0
        output = Path(args.output).expanduser().resolve() if args.output else builders_dashboard_path(repo)
        write_text(output, render_dashboard_html(repo, output))
        if not args.output:
            index_output = builders_index_path(repo)
            write_text(index_output, render_index_md(repo))
            print(f"INDEX: wrote {index_output}")
        print(f"ALL-TEAM PROGRESS OVERVIEW: wrote {output}")
        return 0
    ctx = load_context(repo, args.version, args.team)
    if args.command == "diagnose":
        if args.with_jira:
            live_snapshot = fetch_live_snapshot(ctx)
            ctx["_diagnose_snapshot_override"] = live_snapshot
        print(render_diagnose(ctx, with_jira=args.with_jira), end="")
        return 0
    snapshot_path = Path(args.snapshot).expanduser().resolve() if args.snapshot else ctx["snapshot_path"]
    if args.command == "refresh-snapshot":
        snapshot = fetch_live_snapshot(ctx)
        out_snapshot, out_gantt = freeze_paths(ctx["snapshot_path"], ctx["gantt_path"], args.freeze_sprint)
        write_yaml(out_snapshot, snapshot)
        write_text(out_gantt, render_gantt_html(ctx, snapshot, args.sub_team))
        if args.freeze_sprint:
            write_yaml(ctx["snapshot_path"], snapshot)
            write_text(ctx["gantt_path"], render_gantt_html(ctx, snapshot, args.sub_team))
            print(f"FROZEN SNAPSHOT: wrote {out_snapshot}")
            print(f"FROZEN TEAM ROADMAP VIEW: wrote {out_gantt}")
            print(f"LATEST SNAPSHOT: refreshed {ctx['snapshot_path']}")
            print(f"LATEST TEAM ROADMAP VIEW: refreshed {ctx['gantt_path']}")
        else:
            print(f"LATEST SNAPSHOT: wrote {out_snapshot}")
            print(f"LATEST TEAM ROADMAP VIEW: wrote {out_gantt}")
        configured_progress = ctx.get("progress_gantt_path")
        if configured_progress and args.freeze_sprint:
            frozen_progress = render_progress_gantt(
                ctx,
                out_snapshot,
                freeze_artifact_path(Path(configured_progress), args.freeze_sprint),
            )
            latest_progress = render_progress_gantt(ctx, ctx["snapshot_path"], Path(configured_progress))
            print(f"FROZEN PROGRESS GANTT: wrote {frozen_progress}")
            print(f"LATEST PROGRESS GANTT: refreshed {latest_progress}")
        elif configured_progress:
            progress_output = render_progress_gantt(ctx, out_snapshot, Path(configured_progress))
            print(f"LATEST PROGRESS GANTT: wrote {progress_output}")
        return 0
    if args.command in {"render-gantt", "render-timeline-gantt"} and not snapshot_path.exists():
        raise SystemExit(
            f"Cannot render roadmap view: snapshot not found at {snapshot_path}. "
            "Run refresh-snapshot when Jira is reachable, or pass --snapshot <file>."
        )
    snapshot = load_snapshot(snapshot_path)
    if args.command == "label-audit":
        if args.with_jira:
            snapshot = fetch_live_snapshot(ctx)
        print(render_label_audit(ctx, snapshot), end="")
        return 0
    if args.command == "migration-preview":
        if args.with_jira:
            snapshot = fetch_live_snapshot(ctx)
        print(render_migration_preview(ctx, snapshot), end="")
        return 0
    if args.command == "render-gantt":
        output = Path(args.output).expanduser().resolve() if args.output else ctx["gantt_path"]
        write_text(output, render_gantt_html(ctx, snapshot, args.sub_team))
        print(f"TEAM ROADMAP VIEW: wrote {output}")
        progress_output = render_progress_gantt(ctx, snapshot_path)
        if progress_output:
            print(f"PROGRESS GANTT: wrote {progress_output}")
        return 0
    if args.command == "render-timeline-gantt":
        output = (
            Path(args.output).expanduser().resolve()
            if args.output
            else ctx.get("progress_gantt_path") or ctx["gantt_path"].with_name("roadmap-progress-gantt.html")
        )
        progress_output = render_progress_gantt(ctx, snapshot_path, Path(output))
        print(f"TIMELINE PROGRESS GANTT: wrote {progress_output}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
