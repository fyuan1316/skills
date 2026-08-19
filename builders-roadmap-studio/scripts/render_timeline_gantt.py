#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Render a compact half-month roadmap Gantt from a Roadmap Studio snapshot."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html
from pathlib import Path

import yaml


COLORS = {"Done": "#10b981", "In Progress": "#3b82f6", "To Do": "#9ca3af", "Cancelled": "#d1d5db"}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def status(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"done", "resolved", "closed", "完成", "已完成"}:
        return "Done"
    if raw in {"in progress", "ready for qa", "进行中", "处理中"}:
        return "In Progress"
    if raw in {"cancelled", "canceled", "won't do", "rejected"}:
        return "Cancelled"
    return "To Do"


def date(value: object) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def counts(children: list[dict]) -> dict[str, int]:
    result = {name: 0 for name in COLORS}
    for child in children:
        result[status(child.get("status_name"))] += 1
    return result


def active_total(value: dict[str, int]) -> int:
    return value["Done"] + value["In Progress"] + value["To Do"]


def pct(done: int, total: int) -> int:
    return round(done / total * 100) if total else 0


def periods(first: dt.date, last: dt.date) -> list[dict]:
    cursor = first.replace(day=1)
    end_month = last.replace(day=1)
    result = []
    while cursor <= end_month:
        final_day = calendar.monthrange(cursor.year, cursor.month)[1]
        result.append({"label": cursor.strftime("%b-1"), "start": cursor, "end": cursor.replace(day=15), "month_start": True})
        result.append({"label": cursor.strftime("%b-2"), "start": cursor.replace(day=16), "end": cursor.replace(day=final_day), "month_start": False})
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return result


def period_index(value: dt.date, slots: list[dict]) -> int:
    for index, slot in enumerate(slots):
        if slot["start"] <= value <= slot["end"]:
            return index
    return 0 if value < slots[0]["start"] else len(slots) - 1


def child_in_month(child: dict, epic: dict, today: dt.date) -> bool:
    tokens = {f"{today.month}月", f"{today.month:02d}月", f"{today.year}-{today.month:02d}"}
    sprints = [str(item) for item in child.get("sprints") or []]
    if sprints:
        return any(token in sprint for sprint in sprints for token in tokens)
    start = date(epic.get("start_after") or epic.get("due_date"))
    target = date(epic.get("due_date") or epic.get("start_after"))
    if not start or not target:
        return False
    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return start <= month_end and target >= month_start


def timeline_background(slots: list[dict], snapshot_index: int, release_index: int) -> str:
    cells = []
    for index, slot in enumerate(slots):
        classes = ["cell"]
        if slot["month_start"]:
            classes.append("month-start")
        if index == snapshot_index:
            classes.append("snapshot")
        if index == release_index:
            classes.append("release")
        cells.append(f'<div class="{" ".join(classes)}"></div>')
    return f'<div class="timeline-bg" style="grid-template-columns:repeat({len(slots)},1fr)">{"".join(cells)}</div>'


def bar(start: dt.date | None, target: dt.date | None, value: dict[str, int], epic_status: str, slots: list[dict]) -> str:
    if not start or not target:
        return '<span class="undated">未排计划周期</span>'
    left = period_index(start, slots) + 1
    right = period_index(target, slots) + 2
    total = sum(value.values())
    if not total:
        return f'<div class="bar simple {epic_status.lower().replace(" ", "_")}" style="grid-column:{left}/{right}"></div>'
    segments = []
    for name in ("Done", "In Progress", "To Do", "Cancelled"):
        amount = value[name]
        if amount:
            klass = name.lower().replace(" ", "_")
            segments.append(f'<div class="seg {klass}" style="flex:{amount}" title="{name}: {amount}">{amount}</div>')
    return f'<div class="bar" style="grid-column:{left}/{right}">{"".join(segments)}</div>'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--release-meta", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Roadmap Progress Gantt")
    parser.add_argument("--renderer-version", default="unknown")
    args = parser.parse_args()

    snapshot = yaml.safe_load(args.snapshot.read_text(encoding="utf-8")) or {}
    profile = yaml.safe_load(args.profile.read_text(encoding="utf-8")) or {}
    release_meta = (
        yaml.safe_load(args.release_meta.read_text(encoding="utf-8")) or {}
        if args.release_meta
        else {}
    )
    issues = snapshot.get("issues") or []
    children = snapshot.get("child_issues") or []
    child_by_epic: dict[str, list[dict]] = {}
    for child in children:
        child_by_epic.setdefault(str(child.get("parent_epic") or ""), []).append(child)

    team_defs = profile.get("sub_teams") or []
    label_to_team = {label: str(team.get("name")) for team in team_defs for label in team.get("jira_labels") or []}
    team_order = [str(team.get("name")) for team in team_defs]
    external_team_by_project = {
        str(item.get("project") or item.get("key")): str(item.get("team") or item.get("name"))
        for item in profile.get("external_jira_projects") or []
        if isinstance(item, dict)
        and (item.get("project") or item.get("key"))
        and (item.get("team") or item.get("name"))
    }
    by_team: dict[str, list[dict]] = {}
    for epic in issues:
        labels = set(epic.get("labels") or [])
        project_key = str(epic.get("project_key") or str(epic.get("key") or "").split("-", 1)[0])
        team = external_team_by_project.get(project_key) or next(
            (label_to_team[label] for label in labels if label in label_to_team),
            "Unknown",
        )
        by_team.setdefault(team, []).append(epic)

    snapshot_generated_at = str(snapshot.get("generated_at") or "")
    try:
        snapshot_date = dt.datetime.fromisoformat(snapshot_generated_at).date()
    except ValueError as exc:
        raise SystemExit(
            f"snapshot must contain a valid generated_at timestamp: {snapshot_generated_at!r}"
        ) from exc
    release_target = date(release_meta.get("release_target_date"))
    sprint_start = date(release_meta.get("sprint_start_date"))
    all_dates = [value for epic in issues for value in (date(epic.get("start_after")), date(epic.get("due_date"))) if value]
    first_candidates = all_dates + [value for value in (sprint_start, snapshot_date) if value]
    last_candidates = all_dates + [value for value in (release_target, snapshot_date) if value]
    first = min(first_candidates) if first_candidates else snapshot_date.replace(day=1)
    last = max(last_candidates) if last_candidates else snapshot_date.replace(day=calendar.monthrange(snapshot_date.year, snapshot_date.month)[1])
    slots = periods(first, last)
    snapshot_index = period_index(snapshot_date, slots)
    release_marker_date = release_target or last
    release_index = period_index(release_marker_date, slots)
    headers = "".join(f'<div class="tcol-head {"month-start" if slot["month_start"] else ""}">{esc(slot["label"])}</div>' for slot in slots)
    markers = (
        f'<div class="markers-overlay" style="left:300px;right:0">'
        f'<div class="marker snapshot" style="left:{(snapshot_index + .5) / len(slots) * 100:.2f}%"><span class="pin">Snapshot · {snapshot_date}</span></div>'
        f'<div class="marker release" style="left:{(release_index + .5) / len(slots) * 100:.2f}%"><span class="pin">Target · {release_marker_date}</span></div></div>'
    )

    summary_rows = []
    detail_sections = []
    for team in sorted(by_team, key=lambda name: (team_order.index(name) if name in team_order else len(team_order), name)):
        epics = sorted(by_team[team], key=lambda item: (item.get("start_after") or "9999", item.get("due_date") or "9999", item.get("key") or ""))
        team_children = [child for epic in epics for child in child_by_epic.get(str(epic.get("key") or ""), [])]
        team_counts = counts(team_children)
        start = min((date(epic.get("start_after")) for epic in epics if date(epic.get("start_after"))), default=None)
        target = max((date(epic.get("due_date")) for epic in epics if date(epic.get("due_date"))), default=None)
        summary_rows.append(
            f'<div class="row-label"><a href="#team-{esc(team).replace(" ", "-")}"><span class="summary">{esc(team)}</span></a><span class="badge">{len(epics)}</span></div>'
            f'<div class="row-time">{timeline_background(slots, snapshot_index, release_index)}<div class="timeline-col-inner" style="grid-template-columns:repeat({len(slots)},1fr);z-index:1">{bar(start,target,team_counts,"To Do",slots)}</div><span class="row-date">{start or "TBD"} → {target or "TBD"}</span></div>'
        )
        monthly_children = [child for epic in epics for child in child_by_epic.get(str(epic.get("key") or ""), []) if child_in_month(child, epic, snapshot_date)]
        monthly_counts = counts(monthly_children)
        area_total = active_total(team_counts)
        month_total = active_total(monthly_counts)
        rows = []
        undated = []
        for epic in epics:
            epic_children = child_by_epic.get(str(epic.get("key") or ""), [])
            value = counts(epic_children)
            start_date = date(epic.get("start_after"))
            target_date = date(epic.get("due_date"))
            epic_status = status(epic.get("status_name") or epic.get("epic_status"))
            label = (
                f'<span class="status-dot" style="background:{COLORS[epic_status]}"></span>'
                f'<a class="key" href="https://jira.alauda.cn/browse/{esc(epic.get("key"))}" target="_blank" rel="noopener">{esc(epic.get("key"))}</a>'
                f'<span class="summary" title="{esc(epic.get("summary"))}">{esc(epic.get("summary"))}</span>'
            )
            if not start_date or not target_date:
                undated.append(f'<li>{label}</li>')
                continue
            rows.append(
                f'<div class="row-label">{label}</div><div class="row-time">{timeline_background(slots,snapshot_index,release_index)}'
                f'<div class="timeline-col-inner" style="grid-template-columns:repeat({len(slots)},1fr);z-index:1">{bar(start_date,target_date,value,epic_status,slots)}</div>'
                f'<span class="row-date">{start_date} → {target_date}</span></div>'
            )
        undated_html = f'<div class="undated"><b>未排计划周期</b><ul>{"".join(undated)}</ul></div>' if undated else ""
        detail_sections.append(
            f'<div class="section-title"><h3 id="team-{esc(team).replace(" ", "-")}">{esc(team)} <span class="count">· {len(epics)} epics · 总体 {pct(team_counts["Done"],area_total)}% · {snapshot_date.month}月 {pct(monthly_counts["Done"],month_total)}%</span></h3><a href="#top">↑ 回到顶部</a></div>'
            f'<div class="card"><div class="gantt-wrap">{markers}<div class="gantt"><div class="gantt-head"><div class="label-col"></div><div class="timeline-col"><div class="timeline-col-inner" style="grid-template-columns:repeat({len(slots)},1fr)">{headers}</div></div></div>{"".join(rows)}</div></div>'
            f'{undated_html}</div>'
        )

    css = """
:root{--panel:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--done:#10b981;--in-progress:#3b82f6;--todo:#9ca3af;--cancelled:#d1d5db;--snapshot:#f59e0b;--release:#22c55e}*{box-sizing:border-box}html,body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;font-size:13px;color:var(--ink);background:linear-gradient(180deg,#f8fafc,#eef2f7)}.page{max-width:1450px;margin:auto;padding:24px}.title-bar,.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 1px 2px #0f172a0a}.title-bar{display:flex;justify-content:space-between;align-items:baseline;padding:16px 20px;margin-bottom:16px}.title-bar h1{font-size:18px;margin:0}.meta{color:var(--muted);font-size:12px}.legend{display:flex;gap:14px;align-items:center}.dot{width:10px;height:10px;border-radius:2px;display:inline-block;margin-right:4px}.card{padding:18px 20px;margin-bottom:18px}.card h2{font-size:14px;margin:0 0 14px}.gantt{display:grid;grid-template-columns:300px 1fr}.gantt-head{display:grid;grid-template-columns:subgrid;grid-column:1/-1}.label-col{border-right:1px solid var(--line)}.timeline-col,.row-time{position:relative;border-bottom:1px solid var(--line)}.timeline-col-inner,.timeline-bg{display:grid;height:100%;position:relative}.tcol-head{text-align:center;font-size:10px;color:var(--muted);padding:6px 0;border-left:1px dashed var(--line)}.tcol-head.month-start,.cell.month-start{border-left:1px solid #cbd5e1}.row-label{display:flex;align-items:center;gap:8px;padding:8px 12px 8px 0;border-right:1px solid var(--line);min-height:34px}.row-label a{text-decoration:none;color:inherit}.badge{font-size:10px;padding:1px 6px;border-radius:999px;background:#f1f5f9;color:var(--muted);margin-left:auto}.row-time{min-height:34px;padding:5px 8px 5px 0;display:grid;align-items:center}.timeline-bg{position:absolute;inset:0;pointer-events:none}.cell{border-left:1px dashed var(--line)}.cell.snapshot{background:#f59e0b14}.cell.release{background:#22c55e0d}.bar{height:18px;border-radius:4px;display:flex;overflow:hidden;color:#fff;font-size:10px;line-height:18px;box-shadow:0 1px 2px #0f172a0f}.bar.simple.done{background:var(--done)}.bar.simple.in_progress{background:var(--in-progress)}.bar.simple.to_do{background:var(--todo)}.seg{display:flex;align-items:center;justify-content:center}.seg.done{background:var(--done)}.seg.in_progress{background:var(--in-progress)}.seg.to_do{background:var(--todo)}.seg.cancelled{background:var(--cancelled);color:#475569}.row-date{position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:10px;color:var(--muted);background:#ffffffdc;padding:1px 6px;border-radius:3px}.markers-overlay{position:absolute;top:-10px;bottom:0;z-index:6;pointer-events:none}.marker{position:absolute;top:0;bottom:0;border-left:2px solid currentColor}.marker.snapshot{color:var(--snapshot)}.marker.release{color:var(--release)}.pin{position:absolute;top:0;transform:translateX(-50%);background:currentColor;color:#fff;font-size:10px;padding:1px 6px;border-radius:4px;white-space:nowrap}.section-title{display:flex;justify-content:space-between;align-items:center;margin:22px 4px 8px}.section-title h3{font-size:14px;margin:0}.section-title .count,.section-title a{color:var(--muted);font-size:11px;text-decoration:none}.status-dot{width:9px;height:9px;border-radius:50%;flex:none}.key{font-family:ui-monospace,monospace;font-size:11px;color:var(--muted)}.summary{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.undated{color:var(--muted);margin-top:14px}.undated li{margin:5px 0;display:flex;gap:8px;align-items:center}.footer{text-align:right;color:var(--muted);font-size:11px;padding:8px 4px}@media(max-width:800px){.page{padding:12px}.gantt{grid-template-columns:220px 1fr}.markers-overlay{left:220px!important}.title-bar{display:block}.meta{margin-top:8px}}
"""
    legend = "".join(f'<span><i class="dot" style="background:{color}"></i>{name}</span>' for name, color in COLORS.items())
    snapshot_version = snapshot.get("roadmap_studio_version") or "unknown"
    content = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="roadmap-studio-version" content="{esc(args.renderer_version)}"><meta name="roadmap-studio-snapshot-version" content="{esc(snapshot_version)}"><title>{esc(args.title)}</title><style>{css}</style></head><body><a id="top"></a><main class="page"><div class="title-bar"><h1>{esc(args.title)}</h1><div class="meta">Cycle: <b>{first}</b> → <b>{last}</b> · Snapshot: <b>{snapshot_date}</b> · Target: <b>{release_marker_date}</b> · {len(issues)} Epics · {len(children)} Tasks</div></div><div class="card" style="padding:12px 20px"><div class="legend">Status: {legend}</div></div><div class="card"><h2>Area timeline</h2><div class="gantt-wrap">{markers}<div class="gantt"><div class="gantt-head"><div class="label-col"></div><div class="timeline-col"><div class="timeline-col-inner" style="grid-template-columns:repeat({len(slots)},1fr)">{headers}</div></div></div>{''.join(summary_rows)}</div></div></div>{''.join(detail_sections)}<div class="footer">Generated {esc(snapshot.get('generated_at'))} · Renderer {esc(args.renderer_version)} · Snapshot {esc(snapshot_version)}</div></main></body></html>'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
