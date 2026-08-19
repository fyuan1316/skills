# Jira Source-Of-Truth Contract

Roadmap implementation facts are maintained in Jira. Roadmap Studio reads Jira,
repo roadmap baselines, and generated snapshots, but Jira remains the execution
source of truth for plan dates, risk, dependencies, and delivery expectations.

This contract applies to both human Jira operations and AI/Agent Jira operations.

## Core Rule

Current plan facts live in Jira fields. Delivery expectations live in Epic
description. Epic dependencies live in Jira issue links. Comments are only for
real plan-change explanations or necessary human notes.

Generated snapshots, Gantt views, dashboards, and indexes are generated artifacts
and must not be hand-edited.

## Jira Field Responsibilities

### Labels

Labels are the discovery and classification contract for Roadmap Studio. Each
label type has one responsibility and must not be used for another purpose.

#### Version Label

Purpose: identifies the ACP minor version planning scope that the Epic belongs
to.

Format:

```text
roadmap-x-y
```

Example:

```text
roadmap-4-4
```

Rules:

- Required for every Epic included in an ACP minor roadmap cycle.
- Roadmap Studio uses this label as the Jira query boundary for the release.
- The label means "this Epic is part of the ACP 4.4 roadmap cycle", not whether it is a formal roadmap item.
- Do not use a future version label unless the Epic is intentionally included in that future planning cycle.

#### Roadmap Item Label

Purpose: maps an Epic to a specific formal roadmap item in `roadmap.md`.

Format:

```text
roadmap:x.y:<roadmap-item-slug>
```

Example:

```text
roadmap:4.4:sandboxed-containers-kata
```

Rules:

- Required for Epics that implement a formal roadmap item.
- The slug must match the generated label candidate for the roadmap item.
- Use this label to connect Jira implementation work back to the roadmap baseline.
- Do not use this label for work that is merely planned in the same cycle but is not part of a formal roadmap item.

#### Small Features Label

Purpose: marks requirements that are not formal roadmap items but still need to
be delivered within the same roadmap cycle.

Format:

```text
roadmap:x.y:small-features
```

Example:

```text
roadmap:4.4:small-features
```

Rules:

- Use this label for planned non-roadmap work in the ACP minor cycle.
- Small-feature Epics must still have the version label and sub-team label.
- Do not combine `small-features` with a roadmap item label unless the owner has explicitly reclassified the Epic; fix labels before refreshing snapshots.

#### Sub-Team Label

Purpose: identifies the owning sub-team so each team can plan and review work in
its own sprint process.

Format:

```text
<configured sub-team label>
```

Examples:

```text
基础设施
智能运维&安全
```

Rules:

- Required for every version-labeled Epic.
- Allowed values come from the owning team's `team-profile.yaml`.
- Use this label for team-internal sprint planning, filtering, and ownership follow-up.
- Do not invent new sub-team labels in Jira without updating the team profile first.

#### Scenario Label

Purpose: groups work by a scenario that cuts across roadmap items.

Format:

```text
scenario:<slug>
```

Example:

```text
scenario:bare-metal-delivery
```

Rules:

- Optional.
- Use only for scenario grouping and review, not for release scope, roadmap item mapping, or sub-team ownership.
- Scenario labels must not replace issue links for dependencies.

#### Cross-Team Label

Purpose: marks an Epic as cross-team collaboration work.

Current label:

```text
跨团队需求
```

Rules:

- Optional.
- Use when the Epic requires cross-team collaboration visibility.
- Concrete blocking relationships still require Jira issue links, usually `Blocks`.
- Do not invent labels such as `roadmap-dependency-x-y` to express dependency direction.

#### Agnostic Extension Lane Label

Purpose: marks an Epic as fully Agnostic Extensions delivery.

Current label:

```text
lane:agnostic
```

Rules:

- Optional, but when present it means the Epic is entirely Agnostic Extensions scope.
- Use only for Epics that do not mix Core / Aligned work with Agnostic work.
- Roadmap Studio interprets this label as permission to display the Epic in the post-release extension window instead of flagging the Due Date as out-of-cycle.
- If the work mixes Core / Aligned and Agnostic, split it into separate Epics before adding this label.

#### Plan Deviation Label

Purpose: marks an Epic whose confirmed plan changed, so Jira filters and
sprint/release review can find it. The label is the filter surface; the
structured `[Roadmap Studio Change]` comment is the source of the change details.

Current label:

```text
roadmap:plan-deviation
```

Rules:

- Use when a confirmed plan changes, such as a Due Date moving from one sprint to another.
- A real plan change must update the current Jira fields, add a structured `[Roadmap Studio Change]` comment, and keep this label for review filtering.
- Missing `StartAfter` or `Due Date` is a planning gap, not the meaning of this label.
- This is a review/filter marker, not a roadmap item, release, or sub-team classification.
- Keep it through the current release review by default; clean it up later through an explicit governance action.
- Do not use it for first-time field entry, field correction, or cleanup that does not represent a real plan change.

#### Operational And Deprecated Labels

Some Jira labels are operational metadata and should not be interpreted as
roadmap classification.

Current ignored label:

```text
team_label_added
```

Deprecated labels diagnosed by Roadmap Studio include:

```text
roadmap-item-*
bare-metal-delivery-scenario
```

Rules:

- Do not add deprecated labels to new Epics.
- Do not remove deprecated labels automatically unless a separate cleanup is previewed and confirmed.
- Roadmap Studio may diagnose deprecated labels, but they are not the source of truth.

Do not use comment text to replace labels. If dashboard classification is wrong,
check Jira labels first.

### Assignee

Meaning:

- The Epic assignee is the Engineering Owner for roadmap capacity review.
- Roadmap Studio capacity checks count active Epics by Assignee and sprint window.

Rules:

- Set the Epic assignee to the person responsible for engineering delivery coordination.
- Do not maintain a separate Engineering Owner field or description block unless the
  Roadmap Studio contract is explicitly changed later.
- If a product owner or coordinator needs to follow the Epic but is not the engineering
  owner, use Jira watchers/comments or normal team communication rather than changing
  the assignee away from the engineering owner.

### StartAfter

Field: `customfield_12409` / `StartAfter`.

Meaning:

- Planned Epic start date.
- Roadmap Studio maps it to the release sprint calendar.
- Missing value means `Planning Input Needed`.

Correct an inaccurate value directly in Jira. A field correction is not a plan
change and does not require a comment.

### Due Date

Field: `duedate` / `Due Date`.

Meaning:

- Planned Epic completion date.
- Roadmap Studio maps it to the target sprint.
- Missing value means `Planning Input Needed`.

Correct an inaccurate value directly in Jira. A field correction is not a plan
change and does not require a comment.

### Risk

Field: `customfield_12240` / `Risk`.

Allowed values: `无`, `低`, `高`.

Rules:

- Set `无` when there is no known risk.
- Set `低` or `高` when a risk exists.
- If Risk is `低` or `高`, the Epic description or a necessary human comment must explain the risk.
- Prefer Epic description for risk notes.
- Add a plan-change comment only when the risk changes the committed plan.

### Epic Description

Epic description carries the current delivery facts and necessary context.

Recommended sections:

```text
h3. Roadmap Studio Delivery Expectation

<What this Epic delivers, completion criteria, expected output, or DoD.>

h3. Roadmap Studio Dependencies

* <Dependency or prerequisite.>

h3. Roadmap Studio Risk Notes

* <Risk explanation.>

h3. Roadmap Studio Notes

* <Other relevant context.>
```

Updating description to correct or complete facts is not a plan change and does
not require a comment.

### Issue Links

Concrete Epic dependencies must be represented with Jira issue links.

Common link types:

- `Blocks`
- `Relate`
- `Clone`
- `Duplicate`

Comment text may explain dependency background, but issue links are the
relationship source of truth.

## Comment Rules

Jira comments are changelog entries or human explanations. They are not the plan
fact source.

Use comments for:

- A confirmed plan change.
- Due Date changing from one confirmed date to another confirmed date.
- StartAfter changing because of resource, dependency, or priority changes.
- Risk escalation or resolution that changes the committed plan.
- Meeting decisions that need audit history.
- Cross-team or external dependency explanations that must be kept as history.

Do not add comments for:

- First-time StartAfter / Due Date entry.
- Correcting inaccurate field values.
- Filling Jira fields from an already confirmed plan.
- Completing Epic description.
- Completing Risk.
- Completing labels.
- Automated cleanup or normalization where no real plan change happened.

### Plan Change Comment Template

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

The marker body must be valid YAML. `changed`, `from`, `to`, and `reason` are
required by the renderer. Put old/new values on separate keys; do not combine
them into one prose line. For example, this is invalid and will not satisfy
`roadmap:plan-deviation`:

```text
[Roadmap Studio Change]
changed: Due Date from: 2026-05-31 to: 2026-06-15
reason: ...
[/Roadmap Studio Change]
```

`reason_category` is optional. Use it only when the team has already formed a
stable review taxonomy and wants structured aggregation in dashboards or review
reports. When used, it should be one of:

- `前置收敛不足`
- `范围扩张`
- `资源挤占`
- `人员切换`
- `执行治理不闭环`
- `优先级调整`
- `外部依赖`
- `容量/假期影响`
- `其他`

Do not update historical comments for normal plan changes. Add a new comment for
each real change.

### Comment Normalization

The canonical Roadmap Studio Change payload is the structured YAML template
above. For generated snapshots, Roadmap Studio may normalize legacy or natural
language change comments into structured `roadmap_changes` data so generated
views remain explainable. The normalized snapshot data must preserve enough
provenance to debug the source comment and must not become a new Jira source of
truth.

Agents should still write new change comments in the canonical structured form.
Natural language comments are tolerated as input for AI-assisted snapshot
normalization, not as the preferred write format. If a comment cannot be
normalized confidently, diagnostics should surface a governance gap instead of
silently inventing facts.

## AI / Agent Write Rules

AI must follow preview -> confirm -> write -> verify.

Before writing Jira, AI must show:

- Jira keys to operate on.
- Current field values.
- Target field values.
- Whether description will be updated.
- Whether issue links will be created.
- Whether comments will be added.
- Whether unnecessary roadmap-automation comments will be cleaned up.
- Operation reason.
- Items that still need human input.

Recommended write sequence:

1. Read current Jira issues.
2. Generate preview.
3. Wait for user confirmation.
4. Update Jira fields.
5. Create issue links.
6. Update description.
7. Add comments only for real plan changes.
8. Clean up clearly identified unnecessary roadmap-automation comments.
9. Read Jira back for verification.
10. Refresh snapshot.
11. Render team dashboard and all-team dashboard.
12. Output a final status report.

AI must not:

- Batch-write Jira without confirmation.
- Turn field completion, field completion, or fact correction into a plan-change comment.
- Add comments only because a wrong field was corrected.
- Update old comments.
- Use comments to maintain StartAfter, Due Date, Risk, dependencies, or delivery expectations.
- Delete human comments that cannot be clearly identified as non-compliant roadmap-automation comments.
- Treat generated snapshots or dashboards as a source to write back into Jira.

## Human Operation Rules

When creating a roadmap Epic, fill:

- Version label.
- Roadmap item label or small-features label.
- Sub-team label.
- StartAfter.
- Due Date.
- Risk.
- Delivery expectation in Epic description.
- Required issue links.

When changing an Epic:

- Fact correction or missing-field completion does not need a comment.
- A true change to a confirmed plan must add a Roadmap Studio Change comment.

## Compliance Checklist

Each roadmap Epic should satisfy:

```text
[ ] Has roadmap version label.
[ ] Has roadmap item label or small-features label.
[ ] Has sub-team label.
[ ] Has StartAfter.
[ ] Has Due Date.
[ ] Risk is 无 / 低 / 高.
[ ] If Risk is 低 / 高, risk notes exist.
[ ] Description contains delivery expectation.
[ ] Concrete dependencies use Jira issue links.
[ ] No unnecessary roadmap-automation comment remains.
[ ] Every roadmap:plan-deviation label has a matching structured Roadmap Studio Change comment.
[ ] lane:agnostic is used only when the Epic is fully Agnostic Extensions scope.
```

## Fact Correction Versus Plan Change

Fact correction examples:

- Filling Jira fields from an already confirmed plan.
- Correcting an inaccurate StartAfter or Due Date.
- Completing description.
- Completing Risk.
- Correcting labels.
- Cleaning up unnecessary roadmap-automation comments.

Fact corrections do not require a change comment.

Real plan change examples:

- Confirmed Due Date changes from one date to another.
- Confirmed StartAfter moves earlier or later.
- Work committed for this release moves to a later release.
- Scope expansion changes the delivery date.
- Resource, dependency, personnel, or risk changes alter the committed plan.

Real plan changes require a Roadmap Studio Change comment.
