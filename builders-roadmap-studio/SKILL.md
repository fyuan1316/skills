---
name: builders-roadmap-studio
description: Use when the user wants to govern roadmap source files, audit roadmap Jira labels, refresh Jira-backed roadmap snapshots, generate a Gantt or progress timeline from Jira, freeze sprint progress snapshots, regenerate an offline team Roadmap view, or generate the all-team progress overview. Trigger on requests like "根据 Jira 生成 Gantt 图", "刷新 Jira 并生成甘特图", "生成 roadmap 进度时间线", "诊断 roadmap studio 输入", "检查 roadmap label", "刷新最新快照", "冻结 Sprint 进度快照", "生成团队 Roadmap 视图", or "生成所有团队进度总览".
---

# Roadmap Studio

Use this skill for snapshot-first roadmap management. The skill is generic: every
team keeps its own roadmap source and snapshots under its team workspace, while
common label rules, ACP sprint rules, snapshot schema, and HTML behavior live in
Builders. Formal user operation is through the assembled `alauda-ai-config`
workspace produced by `setup.sh`; running inside `alauda-ai-builders` remains a
development-compatible layout.

For the full operating model and durable rules, read
[roadmap-studio-operating-model.md](references/roadmap-studio-operating-model.md).
For the Jira source-of-truth contract that humans and AI must both follow, read
[jira-source-of-truth-contract.md](references/jira-source-of-truth-contract.md).
When the user gives sprint-meeting facts, daily-note facts, or asks to turn
meeting notes into Jira updates, also read
[meeting-facts-to-jira-preview.md](references/meeting-facts-to-jira-preview.md).

## Default Help

```text
常用入口：

- 诊断：看当前识别到的是哪个团队、哪个 release、数据是否完整、roadmap item 是否都能找到 Epic
- 检查 Jira 标签：只读检查 roadmap label、small-features、sub-team label 是否干净
- 刷新最新快照：能访问 Jira 时，刷新当前团队 release 的 latest snapshot，并生成 latest 团队 Roadmap 视图
- 根据 Jira 生成 Gantt：刷新 Jira Epic/Task 后，同时生成团队 Roadmap Dashboard；release 配置了 progress_gantt_output_file 时再生成半月粒度进度时间线
- 冻结 Sprint 进度快照：能访问 Jira 时，按指定 sprint 写入冻结 snapshot/视图，同时刷新 latest alias
- 生成团队 Roadmap 视图：不能访问 Jira 时，基于指定 team-profile.yaml / release snapshot 重新生成该团队视图
- 生成进度时间线：不能访问 Jira 时，基于已有 snapshot 重新生成按 Area/Epic 展开的半月粒度 Gantt
- 生成所有团队进度总览：生成 Builders 侧所有团队的进度总览 dashboard 和 AI 检索索引

团队长期维护：team-profile.yaml、releases/<version>/roadmap-meta.yaml、roadmap.md、roadmap-changelog.md。
团队 Sprint board：team-profile.yaml 的 jira_boards.sprint 维护真实 Jira board，不能使用 builders-jira 的全局默认 board 推断。
跨团队项目：team-profile.yaml 的 external_jira_projects 只维护会参与本团队 roadmap 的外部团队 Jira project；外部项目 Epic 归属外部团队，不要求本团队 sub-team label。
Jira 维护：Epic labels、Epic Status、Assignee、StartAfter、Due Date、Risk、description、issue links；真实计划变更才新增结构化 YAML Roadmap Studio Change comment。
会议/日报事实处理：先生成 Jira change preview，不能直接写 Jira；子 Task 排期晚于所属 Epic target 时，必须检查 Epic Due Date 是否需要跟随。
发版节奏：只有完全属于 Agnostic Extensions 的 Epic 才打 `lane:agnostic`；未打该 label 的 Epic 默认按 Core / Aligned code-freeze 前交付处理。
容量审计：Epic Assignee 就是 Engineering Owner；按 Assignee + sprint 统计 owner 容量，不额外维护 owner 字段或 description 结构块。
Snapshot 和 HTML 是生成物，不手工编辑。
排期窗口：roadmap-meta.yaml 维护 sprint_start_date、code_freeze_date、release_target_date；当前 Sprint 由 snapshot.generated_at 按 release 日历计算。
版本定位：Roadmap Studio skill 版本是日期时间戳，运行 `scripts/roadmap_studio.py version-info` 查看；snapshot、甘特图、团队总览和 index 都会暴露该版本。
版本契约：snapshot 必须保留 `roadmap_studio_version`；gantt 必须暴露 renderer version 和 snapshot version；dashboard 必须暴露 renderer version；index 必须记录当前 Roadmap Studio version，并尽量带各 team snapshot version。这些版本暴露面不能在后续重构中回退，除非有等价或更强的替代方式。
```

Internal route names are `diagnose`, `label-audit`, `migration-preview`,
`refresh-snapshot`, `render-gantt`, `render-timeline-gantt`, `render-dashboard`,
`render-progress`, and `version-info`.

For normal users, collapse the routes into three mental models:

- **诊断/检查**：tell the user which team/release was inferred and what is missing.
- **刷新/冻结快照**：when Jira is reachable, refresh the latest snapshot or freeze a sprint snapshot.
- **生成视图**：when Jira is unavailable, render a specific team's Roadmap Dashboard, timeline Gantt, or all-team progress overview from snapshots.

If the user provides meeting/daily facts instead of asking for one route, do not
force them into `diagnose` or `refresh-snapshot`. Read
`references/meeting-facts-to-jira-preview.md`, fetch live Jira facts, and produce
a preview grouped as `建议变更 / 无需变更 / 只留档 / 需要确认`. Do not write Jira
until the user explicitly approves the preview.

Mention route names only when useful for implementation detail or when the user
explicitly asks for commands.

When the user gives a short command such as `diagnose`, first resolve and state
the inferred team/release scope in plain language before listing file paths. A
good response starts with facts like:

```text
我诊断的是 infrastructure 团队的 ACP 4.4 roadmap，Jira project 是 AIT。
数据来源是 repo snapshot，不是 live Jira。
范围包含 sub-teams：基础设施、智能运维&安全。
结论：16/16 roadmap items 都能匹配到 Epic，small-features 有 18 个，unclassified 为 0。
```

Do not expose script paths or source inventories unless the user asks for
implementation details.

## Routes

Choose exactly one route per request.


### `version-info`

Use when a user reports a Roadmap Studio generated artifact problem and you need
to know which skill implementation produced or rendered it.

Run `scripts/roadmap_studio.py version-info`.

The version is a date timestamp in `yyyyMMdd-HHmmss` form. It is also written to
live snapshots as `roadmap_studio_version`, rendered into team Gantt HTML and the
Builders dashboard, and listed in `roadmap-studio-index.md`. When debugging,
compare the snapshot version with the current script version; older snapshots may
need `refresh-snapshot`, while old HTML from a current snapshot may only need
`render-gantt` or `render-dashboard`.

Version visibility is a stable output contract. Snapshot/Gantt/Dashboard/Index
must keep exposing Roadmap Studio version information; later refactors must not
remove those fields or displays unless they replace them with an equivalent or
stronger traceability surface.

### `diagnose`

Use before onboarding or after source structure changes.

It must answer:

- which team was inferred
- which Jira project was inferred
- which release/version was diagnosed
- whether data came from live Jira or repo snapshot
- which sub-teams are in scope
- where `team-profile.yaml` is
- where release `roadmap-meta.yaml` is
- where release `roadmap.md` is
- where the latest Jira snapshot is
- what version/formal/small-feature/scenario label rules apply
- which roadmap items currently discover matching Epics from the snapshot or live Jira

Run `scripts/roadmap_studio.py diagnose --version <version>`. Add `--with-jira`
only when the user explicitly asks to validate live Jira facts; otherwise use the
repo snapshot.

If more than one team has the same version, pass `--team <team_key>`. Never
silently choose a team when the scope is ambiguous.

`diagnose` must not report OK when formal roadmap items match Epics but Jira
`StartAfter` or `Due Date` fields are missing, or an Epic carries
`roadmap:plan-deviation` without a structured `[Roadmap Studio Change]` comment.
In that case, report `Needs planning input` and group the required human input
by sub-team. Epics with both `roadmap:plan-deviation` and a structured change
comment are recorded plan changes, not planning-input gaps.

### `label-audit`

Use for read-only Jira label consistency review.

Run `scripts/roadmap_studio.py label-audit --version <version>`. Add
`--with-jira` to audit live Jira instead of the latest snapshot.

The report must include:

- roadmap items with no matching Epic
- version-labeled Epics that are neither formal roadmap work nor small-features
- Epics missing configured sub-team labels
- deprecated labels such as `roadmap-item-*` and `bare-metal-delivery-scenario`
- agnostic extension lane label `lane:agnostic`
- small-features list

Roadmap Studio never writes Jira. Confirmed writes are done through
[$builders-jira](/Users/changjia/alauda-ai-builders/builders/skills/builders-jira/SKILL.md).

### `refresh-snapshot`

User-facing names: **刷新最新快照** and **冻结 Sprint 进度快照**.

Use when Jira is reachable and the user wants the team release data to be fresh.
Without `--freeze-sprint`, this route refreshes the latest offline execution
facts and regenerates the latest team Roadmap view in one operation. With
`--freeze-sprint <version-Sn>`, it additionally writes sprint-frozen snapshot and
view files for review/audit at that sprint boundary.

Run `scripts/roadmap_studio.py refresh-snapshot --version <version>`.

Before running against Alauda Jira, resolve the credential file through
`/Volumes/macOS-2/Users/yuan/Dev/tools/envs/agent-envs/resolve-env.py --match "Jira roadmap gantt"`
and source only the selected env file in the command that needs it. Never print
the env file or credential values.

Behavior:

- reads version-labeled Jira Epics through `builders-jira`
- includes configured `external_jira_projects` from `team-profile.yaml` when refreshing cross-team roadmap Epics
- reads child issues/tasks in batched Jira queries (`Epic Link in (...)` and
  `parent in (...)`) when Jira supports the query, instead of querying every
  Epic one by one
- writes the latest `jira_snapshot_file` declared by release meta; this file is the latest alias even when its filename does not contain `latest`
- writes the latest `gantt_output_file` declared by release meta; this file is the latest team Roadmap view alias
- when `progress_gantt_output_file` is configured, writes the latest half-month timeline Gantt grouped by Area and Epic
- does not edit roadmap source files and does not write Jira

Jira request timeout is controlled by the shared `builders-jira` client. Set
`JIRA_REQUEST_TIMEOUT_SECONDS` when the Jira server is slow; failed child-query
batches are reported with the JQL that failed so the caller can distinguish a
Jira/API problem from missing child tasks.

If the user asks to freeze a sprint, pass `--freeze-sprint <version-Sn>`. The
command still refreshes latest files and additionally writes sprint-suffixed
snapshot/view files, for example `jira-execution-snapshot-4.4-S4.yaml`,
`roadmap-gantt-4.4-S4.html`, and, when configured,
`roadmap-progress-gantt-4.4-S4.html`.

After generation, verify the snapshot `generated_at`, Epic count, child-task
count, and the visible/meta Roadmap Studio versions. A successful HTML write is
not proof that Jira data is current; the snapshot timestamp is the freshness
boundary.

### `render-gantt`

User-facing name: **生成团队 Roadmap 视图**.

Use when Jira is not available, or when the user wants to regenerate one specific
team's offline Roadmap view from an existing snapshot.

Run `scripts/roadmap_studio.py render-gantt --version <version>`.

Behavior:

- does not access Jira
- reads the resolved team's `team-profile.yaml`, release meta, roadmap, and snapshot
- writes the release `gantt_output_file`, normally `snapshots/roadmap-gantt.html`; this is the latest team Roadmap view alias
- supports `--snapshot <file>`, `--output <file>`, and `--sub-team <name>`

The HTML is a Roadmap Dashboard, not a plain table. It must follow the
`4.4-roadmap.html` interaction model: KPI cards, release timeline, roadmap
chips, expandable roadmap cards, and expandable all-Epic/all-task tables.
Each roadmap card must include a Sprint Plan block with Jira Epic links,
sub-team, StartAfter / Due Date derived sprint windows, Epic Status, lane, plan health,
resource signals from assignees/tasks, retro signals, and snapshot generated time.

The HTML must also make missing input obvious. It should show a top-level
planning warning and per-roadmap `Needs plan` markers when `StartAfter` or
`Due Date` values are missing, when a non-`lane:agnostic` Epic targets after code freeze, or when `roadmap:plan-deviation` is present without a structured change comment. Recorded plan changes should be shown as `Plan Changes`, not as planning gaps. Small Features must be rendered as a peer
section next to Roadmaps, not hidden behind Roadmap chips, with quick filters for
All and configured sub-teams. Any Jira key shown in an action item must be
clickable.

The team dashboard and Builders dashboard share the CSS asset
`assets/roadmap-dashboard.css`, embedded into each generated HTML file for
offline use. Keep stable layout primitives such as KPI card sizing, typography,
and filter controls in that CSS asset instead of duplicating one-off inline
rules in separate renderers.

Planning information is maintained through the skill/Jira operation flow, not by
manual edits to generated snapshot or HTML. When a PM/engineering manager needs
to set plan dates, risk, delivery expectation, dependency links, or confirmed
plan-change labels, first run a read-only preview. After confirmation, update
Jira fields/links/description/labels through `builders-jira`, then refresh the
snapshot. A real change to a previously confirmed plan must update the current
Jira field, add a `[Roadmap Studio Change]` comment, and keep
`roadmap:plan-deviation` for review filtering. Field completion and fact
correction do not require a change comment or deviation label.

### `render-timeline-gantt`

User-facing name: **生成进度时间线**.

Use when Jira is unavailable, when a snapshot was supplied explicitly, or when
the user wants only the compact timeline Gantt rather than the full Roadmap
Dashboard.

Run `scripts/roadmap_studio.py render-timeline-gantt --version <version>`.

Behavior:

- does not access Jira
- reads the release snapshot, `team-profile.yaml`, and `roadmap-meta.yaml`
- groups Epics by configured Area/sub-team labels and sorts them by StartAfter, Due Date, then Jira key
- renders half-month slots, snapshot-as-of and release-target markers, Epic plan bars, and child-task status segments
- shows both overall completion and snapshot-month completion, computed from Done child tasks over active child tasks
- writes `progress_gantt_output_file`; when it is not configured, defaults beside the main Gantt as `roadmap-progress-gantt.html`
- supports `--snapshot <file>` and `--output <file>` for one-off rendering
- fails when the snapshot has no valid `generated_at`; never substitutes the current date for unknown freshness

Do not call an offline render "latest Jira". Report the snapshot `generated_at`
and say that live Jira was not queried.

### `render-dashboard`

User-facing name: **生成所有团队进度总览**.

Use to regenerate the all-team Builders roadmap progress overview.

Run `scripts/roadmap_studio.py render-dashboard`.

Behavior:

- scans Builders top-level team directories, not only teams that already have roadmap metadata
- reads each onboarded team's active/current release roadmap and latest snapshot
- shows teams that are not onboarded or have missing/empty inputs as setup/data gaps
- writes the repo AI discovery index at the current workspace Builders knowledge root:
  `knowledge/builders/roadmap/roadmap-studio-index.md` in installed config,
  or `builders/knowledge/builders/roadmap/roadmap-studio-index.md` in the source repo
- groups formal roadmap items by the Builders capability taxonomy Domain / Capability
- renders Small Features as a peer section, not under Domain / Capability
- renders Cross-Team Work from Epics labeled `跨团队需求`
- writes the all-team dashboard at the current workspace Builders knowledge root:
  `knowledge/builders/roadmap/roadmap-dashboard.html` in installed config,
  or `builders/knowledge/builders/roadmap/roadmap-dashboard.html` in the source repo
- does not write team source files or Jira

The index is mandatory. It is the stable repo-level retrieval surface for AI
agents and humans who ask about Roadmap Studio from the Builders knowledge tree.
Do not require people to open the skill directory to discover onboarded teams,
release roots, generated dashboards, or setup gaps.

Include active/current releases that have a real `roadmap.md`. If the snapshot
is missing or empty, show the team as a setup gap instead of silently hiding it.
Do not show future planning releases such as 4.5 until they become active/current.

Cross-team work contract:

- `跨团队需求` marks an Epic as cross-team work.
- Jira Blocks links describe concrete blocking relationships when they exist.
- A cross-team Epic may have `跨团队需求` without a Blocks link; render it as cross-team collaboration with no declared blocker.
- Roadmap Studio must not invent new cross-team labels such as `roadmap-dependency-x-y`.

## Source-Of-Truth Boundary

Teams maintain only:

- `team-profile.yaml` (including Jira project, sub-team labels, and Jira boards)
- `team-profile.yaml` may also declare `external_jira_projects` for other teams whose Jira projects hold cross-team roadmap Epics; this is project ownership metadata, not a sub-team label replacement.
- `releases/<version>/roadmap-meta.yaml`
- `releases/<version>/roadmap.md`
- `releases/<version>/roadmap-changelog.md`

Jira maintains:

- Epic existence and labels, including `roadmap:plan-deviation`
- Agnostic extension lane label `lane:agnostic` for Epics that are fully Agnostic Extensions
- Epic Status
- Assignee as the Engineering Owner for roadmap capacity review
- `StartAfter` (`customfield_12409`) and `Due Date` (`duedate`)
- `Risk` (`customfield_12240`) with values `无 / 低 / 高`
- Epic description for delivery expectation / output / DoD
- issue links for Epic dependencies
- workflow status, assignee, updated time, components, versions
- `[Roadmap Studio Change]` comments only for real plan-change history

Generated files:

- `snapshots/jira-execution-snapshot.yaml`
- `snapshots/roadmap-gantt.html`
- optional `snapshots/roadmap-progress-gantt.html`
- optional sprint-frozen snapshot/Gantt files
- builders cross-team `roadmap-dashboard.html`

## Label Rules

- Version label (`roadmap-x-y`): required release boundary for every Epic in an ACP minor roadmap cycle, for example `roadmap-4-4`.
- Roadmap item label (`roadmap:x.y:<slug>`): maps an Epic to one formal roadmap item in `roadmap.md`, for example `roadmap:4.4:sandboxed-containers-kata`.
- Small features label (`roadmap:x.y:small-features`): marks requirements that are not formal roadmap items but still need delivery in the same roadmap cycle.
- Sub-team label: identifies the owning sub-team for team-internal sprint planning; allowed values live in `team-profile.yaml`, for example `基础设施` and `智能运维&安全`.
- Scenario label (`scenario:<slug>`): optional grouping only; it does not replace roadmap item labels or issue links.
- Cross-team label (`跨团队需求`): optional collaboration marker; concrete blockers still use Jira issue links.
- Plan deviation label (`roadmap:plan-deviation`): marks Epics whose confirmed plan changed, so Jira filters and sprint/release review can find them. A real plan change needs current Jira fields, a `[Roadmap Studio Change]` comment, and this label. Missing StartAfter / Due Date is a planning gap, not the meaning of this label.
- Agnostic lane label (`lane:agnostic`): marks an Epic as fully Agnostic Extensions delivery. It may target the ACP post-release extension window; mixed Core/Aligned/Agnostic requirements must be split into separate Epics.
- Ignored label: `team_label_added`.
- Deprecated labels are diagnosed but not removed by default.

## Hard Rules

- Do not generate Markdown briefing files.
- Do not maintain item-to-Epic mapping files in repo.
- Do not duplicate execution status in repo source files.
- Do not use Jira comments to maintain StartAfter, Due Date, Risk, dependencies, or delivery expectation.
- Do not turn field completion, migration, or fact correction into a plan-change comment.
- Do not update historical Jira comments; append a new `[Roadmap Studio Change]`
  comment only for each confirmed real plan change.
- `[Roadmap Studio Change]` comments must be YAML inside the marker block with
  at least `changed`, `from`, `to`, and `reason`. Natural-language lines such as
  `changed: Due Date from: old to: new` are invalid and will still render as
  `Plan Deviation missing change comment`.
- AI writes must use preview -> confirmation -> write -> readback -> refresh snapshot/dashboard.
- After writing a real plan-change comment, the readback is not complete until a
  refreshed snapshot shows that Epic with non-empty `roadmap_changes`; if it is
  still empty, the comment format is wrong or the parser cannot recognize it.
- Do not write Jira from Roadmap Studio; use `builders-jira` after explicit confirmation.
- Snapshot and HTML files are generated artifacts and must not be hand-edited.
- Sprint-meeting or daily-note facts are valid inputs for Jira change preview, but
  never for immediate writes. Always fetch live Jira fields and comments first.
- When a child Task remains in an Epic's completion scope and its Sprint is later
  than the Epic target sprint, preview an Epic Due Date change unless the user
  explicitly says that child is only follow-up/out-of-scope.
