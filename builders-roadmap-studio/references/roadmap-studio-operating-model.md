# Roadmap Studio Operating Model

Roadmap Studio is a snapshot-first workflow for roadmap governance, sprint
planning discussion, and offline progress review. This document is the durable
operating model for the skill. Earlier standalone design specs have been folded
into the skill, this operating model, and the implementation.

## Source-Of-Truth Boundary

Builders owns shared rules:

- label contract shape
- ACP sprint calendar rule
- snapshot schema
- Roadmap Studio skill versioning
- Jira source-of-truth contract
- HTML view behavior
- cross-team dashboard and repo discovery index behavior

Each team owns minimal repo source:

- `team-profile.yaml`: team key, Jira project, optional external Jira projects, Jira boards, sub-teams, team labels, lanes, optional people for display
- `releases/<version>/roadmap-meta.yaml`: release entrypoint and generated output paths
- `releases/<version>/roadmap.md`: release roadmap source-of-truth
- `releases/<version>/roadmap-changelog.md`: semantic roadmap commitment changes

Jira owns execution and per-Epic planning facts. The detailed human/AI contract is
[jira-source-of-truth-contract.md](jira-source-of-truth-contract.md).

Jira owns:

- Epic labels, Epic Status, workflow status, assignee, updated time, components, and fix versions
- Epic assignee is the Engineering Owner for roadmap capacity review
- child issues/tasks
- issue links for concrete blocking relationships
- `StartAfter` (`customfield_12409`) and `Due Date` (`duedate`) for plan dates
- `Risk` (`customfield_12240`) with values `无 / 低 / 高`
- Epic description for delivery expectation, delivery requirements, output, or DoD
- issue links for concrete Epic dependencies
- `[Roadmap Studio Change]` comments only for real plan-change history

Generated artifacts are not source-of-truth:

- `snapshots/jira-execution-snapshot.yaml`
- `snapshots/roadmap-gantt.html`
- optional `snapshots/roadmap-progress-gantt.html`
- sprint-frozen snapshot/Gantt files
- Builders knowledge root `roadmap-studio-index.md`
- Builders knowledge root `roadmap-dashboard.html`

## Label Contract

Labels are defined by the Jira source-of-truth contract. Each label type has one
responsibility:

- Version label (`roadmap-x-y`): ACP minor version planning scope, for example `roadmap-4-4`.
- Roadmap item label (`roadmap:x.y:<slug>`): maps an Epic to one formal roadmap item in `roadmap.md`, for example `roadmap:4.4:sandboxed-containers-kata`.
- Small features label (`roadmap:x.y:small-features`): marks requirements that are not formal roadmap items but must be delivered in the roadmap cycle.
- Sub-team label: identifies the owning sub-team for team-internal sprint planning, for example `基础设施` or `智能运维&安全`.
- Scenario label (`scenario:<slug>`): optional scenario grouping only; it does not replace roadmap item labels or issue links.
- Cross-team label (`跨团队需求`): optional collaboration marker; concrete blockers still use Jira issue links.
- Plan deviation label (`roadmap:plan-deviation`): marks Epics whose confirmed plan changed, so Jira filters and sprint/release review can find them. The structured `[Roadmap Studio Change]` comment stores the from/to/reason details. Missing StartAfter / Due Date remains a planning gap, not the meaning of this label.
- Agnostic lane label (`lane:agnostic`): marks Epics that are fully Agnostic Extensions. These Epics may target the ACP post-release extension window; mixed Core/Aligned/Agnostic requirements must be split into separate Epics.

Allowed sub-team labels live in `team-profile.yaml`. Roadmap Studio ignores
`team_label_added` and diagnoses deprecated labels such as `roadmap-item-*` and
`bare-metal-delivery-scenario`.

When a roadmap item depends on work owned by another Builders team, the owning
team profile may declare `external_jira_projects`. Roadmap Studio then includes
those projects in snapshot refreshes and treats their Epics as owned by the
external team name instead of requiring an internal sub-team label. This mapping
does not replace Jira issue links: concrete blockers still use Jira links, and
the external Epic must still carry the release and roadmap/small-feature labels
that make it part of the roadmap cycle.

All version-labeled Epics must be either formal roadmap item work or
`small-features`. Otherwise the work is unclassified and may be bypassing
roadmap change review.

## ACP Sprint Rule

ACP releases are fixed in March, July, and November. Roadmap planning sprints use
two half-month windows: day 1-15 and day 16 through month end. Core and Aligned
roadmap planning windows end at code freeze, not necessarily at the final
release date. After code freeze, teams move into the next release sprint
planning while the current release continues stabilization and release work.
Epics labeled `lane:agnostic` can use the post-release Agnostic extension window
instead of being treated as out-of-cycle.

Release-specific dates live in `roadmap-meta.yaml`, including
`sprint_start_date`, `code_freeze_date`, and `release_target_date`. The
current sprint shown in generated views is calculated from the snapshot
`generated_at` timestamp and the release sprint calendar.

Team-specific Jira board ownership lives in `team-profile.yaml` under
`jira_boards`. Roadmap Studio and agents must not infer team sprint boards from
`builders-jira` examples or a global `JIRA_BOARD_ID`. For sprint operations,
first read the target team profile, then list Jira sprints with the configured
board id, and only then map roadmap sprint labels such as `4.4-S4` to real Jira
sprint names and ids.

Example:

```yaml
jira_boards:
  sprint:
    id: 282
    name: "AIT-NEW"
    type: "scrum"
```

## Snapshot And HTML Outputs

Snapshots are generated from Jira and must not be hand-edited. They include
normalized Epic facts, child issues, plan fields, risk values, description-derived
planning context, change comments, issue links when Jira provides them, and the
Roadmap Studio skill version that generated the snapshot.

Team roadmap HTML lives under the team release snapshots directory, normally
`snapshots/roadmap-gantt.html`. Despite the legacy file name, it is a Roadmap
Dashboard with sprint planning, not a plain Gantt table. It shows snapshot time,
KPI cards, release timeline, roadmap chips, expandable roadmap cards, Jira
links, sub-team, StartAfter / Due Date derived sprint windows, plan health,
capacity/resource signals from Epic assignees and tasks, Epic Status, retro signals, and task
progress when snapshot contains child issues. Small Features render as a peer
section next to Roadmaps.

When `progress_gantt_output_file` is configured, Roadmap Studio also writes a
compact timeline Gantt, normally `snapshots/roadmap-progress-gantt.html`. This
view groups Epics by Area/sub-team, uses half-month timeline slots, sorts by
StartAfter and Due Date, and composes each bar from child-task workflow status.
It marks the snapshot date and release target separately so an offline artifact
does not imply live Jira freshness. Both visible footer text and HTML meta tags
record renderer and snapshot Roadmap Studio versions.

For capacity review, Roadmap Studio treats Epic `Assignee` as the Engineering
Owner. Capacity checks should count active Epics by Assignee and sprint window;
do not introduce a separate owner field or description block unless this contract
is explicitly changed later.

The `jira_snapshot_file`, `gantt_output_file`, and optional
`progress_gantt_output_file` declared by release meta are the latest aliases.
Their filenames may omit `latest` for backward-compatible links, but their
semantic meaning is always "latest generated data/view". Sprint freeze outputs
must add the sprint label as a filename suffix, for example
`jira-execution-snapshot-4.4-S4.yaml`, `roadmap-gantt-4.4-S4.html`, and
`roadmap-progress-gantt-4.4-S4.html`. Freezing a sprint also refreshes the latest
aliases so the newest working view stays current.

The Builders dashboard lives at the current workspace Builders knowledge root:
`knowledge/builders/roadmap/roadmap-dashboard.html` in installed config, or
`builders/knowledge/builders/roadmap/roadmap-dashboard.html` in the source repo.
The companion index lives alongside it as `roadmap-studio-index.md` and is the
repo-level discovery surface for AI agents and humans. `render-dashboard`
maintains both files automatically.


## Skill Versioning

Roadmap Studio has an explicit skill version in `yyyyMMdd-HHmmss` form, for
example `20260507-120338`. The version is maintained in the generator script as
`ROADMAP_STUDIO_VERSION` and should be updated whenever Roadmap Studio behavior,
snapshot schema interpretation, diagnostics, or generated views change.

The version is exposed in all debugging surfaces:

- `scripts/roadmap_studio.py version-info` prints the current implementation
  version.
- refreshed snapshots include `roadmap_studio_version`,
  `roadmap_studio_version_scheme`, and `generated_by` with the version.
- generated team Roadmap HTML includes visible version text and
  `roadmap-studio-version` / `roadmap-studio-snapshot-version` meta tags.
- the Builders dashboard header includes the renderer version.
- `roadmap-studio-index.md`, `diagnose`, `label-audit`, and migration preview
  include version information.

Version visibility is a stable generated-artifact contract:

- snapshots must retain `roadmap_studio_version` and related version metadata;
- generated team Gantt HTML must expose renderer version and snapshot version;
- generated Builders dashboard must expose renderer version;
- generated `roadmap-studio-index.md` must record the current Roadmap Studio
  version and should retain per-team snapshot versions when available.

These traceability surfaces must not regress in later refactors unless they are
replaced by an equivalent or stronger version-identification mechanism.

When debugging a user report, first capture the artifact type, snapshot
`generated_at`, snapshot `roadmap_studio_version`, and current `version-info`
output. If the snapshot version is old, refresh from Jira. If only the HTML is
old, regenerate the view from the existing snapshot.

## Team Onboarding

1. Create `team-profile.yaml` in the team's roadmap root.
2. Create `releases/<version>/roadmap-meta.yaml` from the template.
3. Create `releases/<version>/roadmap.md`.
4. Create `releases/<version>/roadmap-changelog.md`.
5. Run `diagnose --version <version>`.
6. Run `label-audit --version <version> --with-jira` if Jira is reachable.
7. Run a read-only preview before any Jira write or cleanup operation.
8. Use `builders-jira` to add/fix labels, fields, issue links, descriptions, and real Roadmap Studio Change comments after user confirmation.
9. Run `refresh-snapshot --version <version>` to refresh the latest snapshot, team Roadmap view, and configured progress Gantt.
10. Run `refresh-snapshot --version <version> --freeze-sprint <version-Sn>` only when a sprint boundary should be frozen for review/audit.
11. Offline users run `render-gantt --version <version>` for the full team view or `render-timeline-gantt --version <version>` for the compact progress timeline.
12. Run `render-dashboard` to refresh the all-team progress overview and Roadmap Studio index after onboarding or snapshot changes.

## Jira Source-Of-Truth Contract

Roadmap Studio follows [jira-source-of-truth-contract.md](jira-source-of-truth-contract.md).
The short version is:

- Current plan facts live in Jira fields: `StartAfter`, `Due Date`, and `Risk`.
- Delivery expectations, dependency background, risk notes, and other current
  context live in Epic description.
- Concrete dependencies live in Jira issue links.
- Comments are changelog entries or human explanations, not the plan fact source.
- Add a `[Roadmap Studio Change]` comment only for a real change to a previously
  confirmed plan. Field completion, fact correction, label cleanup, and
  description completion do not require comments.
- AI operations must use preview -> confirmation -> write -> readback -> refresh
  snapshot/dashboard.

### Plan Change Comment

Only real plan changes use this template:

```yaml
[Roadmap Studio Change]
sprint: 4.4-S4
changed: Due Date
from: 2026-06-30
to: 2026-07-15
owner: <name>
reason: <具体变更原因>
notes:
  - <可选补充>
[/Roadmap Studio Change]
```

`reason_category` is optional. Use it only when the team already wants
structured reason aggregation. When used, it should be one of:
`前置收敛不足`, `范围扩张`, `资源挤占`, `人员切换`, `执行治理不闭环`,
`优先级调整`, `外部依赖`, `容量/假期影响`, `其他`.

## Recommended Workflow

- Use `diagnose` to check team/release source structure.
- Use `label-audit` to find Jira label and classification gaps.
- Use `builders-jira` for confirmed Jira writes.
- Use `refresh-snapshot` after Jira changes or before a planning discussion.
- Use `render-gantt` when Jira is unavailable but snapshot exists.
- Use `render-timeline-gantt` for a compact Area/Epic timeline from an existing snapshot.
- Use `render-dashboard` for cross-team Builders overview.
- Use a read-only preview before any Jira write or cleanup operation; previews must not write Jira.

## Rules

- The release roadmap file is always named `roadmap.md`.
- Do not maintain repo item-to-Epic mapping files.
- Do not keep repo planning/dependency/capacity YAML files for per-Epic facts.
- Do not generate Markdown briefing files.
- Do not duplicate execution status in repo source files.
- Do not use Jira comments to maintain StartAfter, Due Date, Risk, dependencies, or delivery expectation.
- Do not turn field completion, or fact correction into a plan-change comment.
- Do not update historical Jira comments for normal changes; append a new `[Roadmap Studio Change]` comment only for a real confirmed plan change.
- Do not hand-edit snapshots or generated HTML.
- Latest snapshot/Gantt files are overwritten by default.
- Use `--freeze-sprint <version-Sn>` only when a product/engineering owner explicitly asks to freeze a sprint view.
