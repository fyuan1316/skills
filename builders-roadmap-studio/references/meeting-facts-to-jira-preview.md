# Meeting Facts To Jira Preview

Use this reference when the user gives sprint-meeting notes, daily-note facts, or
asks to analyze roadmap Jira changes from a daily report. The goal is to turn
natural-language facts into a Jira change preview that follows the Roadmap Studio
source-of-truth contract.

Do not write Jira from this flow until the user confirms the preview. Roadmap
Studio itself still does not write Jira; confirmed writes go through
`builders-jira`, then the snapshot/Gantt are refreshed.

## Required flow

1. Extract every Jira key from the user's facts and from the referenced daily
   note section.
2. Fetch live Jira, not only the latest snapshot. Pull at least:
   - issue type, summary, status, assignee
   - Sprint (`customfield_10001`) for child issues
   - StartAfter (`customfield_12409`) and Due Date (`duedate`) for Epics
   - Risk (`customfield_12240`)
   - labels, especially `roadmap:plan-deviation` and `lane:agnostic`
   - description
   - issue links, parent/Epic relationship when available
   - comments containing `[Roadmap Studio Change]`
3. Build the relationship graph:
   - Which keys are Roadmap Epics?
   - Which keys are child Tasks/Documents/Jobs under those Epics?
   - Which Sprint is each child in?
   - Does any child Sprint extend beyond the Epic target sprint?
   - Did the user say the child is still in completion scope, or only follow-up /
     out-of-scope / detail-only?
4. Classify each possible action:
   - Field correction or fact completion: update current Jira facts or Epic
     description; no `[Roadmap Studio Change]` comment.
   - Real plan change: update current Jira field, add or keep
     `roadmap:plan-deviation`, and append a new `[Roadmap Studio Change]`
     comment.
   - Risk maintenance: change `Risk` only when the user states or confirms a
     risk. `Risk=低/高` requires risk notes in the Epic description or a needed
     human comment.
   - Detail-only: keep for daily-note memory; do not generate a Jira change.
5. Output only these groups:
   - `建议变更`
   - `无需变更`
   - `只留档`
   - `需要确认`

Avoid long intermediate taxonomy dumps. The user needs actionable preview, not a
transcript of your reasoning.

## Sprint-to-Epic target rule

If a child issue remains part of an Epic's completion scope and is scheduled in a
later sprint than the Epic target, preview moving the Epic Due Date to the later
sprint end date. This is a real plan change if the previous target was already
confirmed.

Do not apply this rule when the user says the child is detail-only, not blocking,
post-release follow-up, or explicitly outside the Epic's completion definition.
If unclear, put it under `需要确认`.

## Comments and labels

Use `[Roadmap Studio Change]` comments only for real changes to a previously
confirmed plan: due date, start date, scope, dependency, priority, resource, or
lane. Do not write a change comment for field completion, migration cleanup, or
fact correction.

When a real plan change is previewed:

- show the exact field diff;
- keep or add `roadmap:plan-deviation`;
- draft the change comment in the preview as parseable YAML inside
  `[Roadmap Studio Change]` / `[/Roadmap Studio Change]`;
- state why it is a plan change rather than a fact correction.

The comment body must parse as a YAML mapping. Required fields are `changed`,
`from`, `to`, and `reason`; include `sprint`, `owner`, `reason_category`, and
`notes` when useful. Do not write natural-language pseudo-YAML such as
`changed: Due Date from: 2026-05-31 to: 2026-06-15`; Roadmap Studio cannot parse
that as a valid change and will still report `Plan Deviation missing change
comment`.

Valid example:

```yaml
[Roadmap Studio Change]
changed: Due Date
from: 2026-05-31
to: 2026-06-15
sprint: 4.4-S6
owner: Chao Zhou
reason_category: 方案调整
reason: Framework approach changed; the original 4.4-S5 plan needs another update.
notes: Source is meok 2026-06-01 Manual facts; confirmed by Chao Zhou.
[/Roadmap Studio Change]
```

When only the Epic description should be clarified, say that no change comment is
needed.

## Regression example: AIT-68925 OLM v1

Input facts:

- `AIT-68925` is the OLM v1 Investigation Epic.
- `AIT-70392` and `AIT-70393` are in `基础设施-4.4-S6`; expected output is to
  synchronize OLM v1 investigation results.
- Those two tasks do not block `AIT-70521` ACP Kernel because OLM v1 is not Core;
  it is expected to be L4 or L5.
- `AIT-70394` waits for Tianpeng's investigation result; Zhiguang Jia's concrete
  action is not clear yet; it is placed in `基础设施-4.4-S7`.
- Sentry moving to L4 is detail-only for the daily note; the user does not want
  to treat it as a roadmap risk.

If live Jira says `AIT-68925` has `Due Date=2026-06-15` / `4.4-S6`, and
`AIT-70394` is still in the OLM v1 completion chain, the expected preview is:

```text
建议变更
- AIT-68925: Due Date 2026-06-15 -> 2026-06-30.
  Reason: AIT-70394 is scheduled in 基础设施-4.4-S7 and remains a follow-up task
  under the OLM v1 Investigation completion chain, so the Epic target cannot stay
  at 4.4-S6.
  Comment: append [Roadmap Studio Change] with the reason above.
  Label: keep roadmap:plan-deviation.

无需变更
- AIT-70521: OLM v1 does not block ACP Kernel / Core trimming. No Due Date or
  Risk change from this fact.

只留档
- Sentry is being adjusted toward L4, but 4.4 may not fully remove it. The user
  marked this as detail-only; do not create a Risk or Due Date change.

需要确认
- Whether AIT-68925 description should explicitly record that OLM v1 is L4/L5 and
  not ACP Core. If this only clarifies scope, it is fact completion and does not
  need a change comment.
```

Wrong behavior to avoid:

- Treating the facts as a generic meeting note and missing the Epic target shift.
- Asking the user to manually explain that S7 child work implies a S7 Epic target.
- Marking Risk just because work moved later.
- Updating `AIT-70521` unless live Jira contradicts the non-blocking Core/L4/L5
  boundary.
- Writing non-parseable change comments that look structured to humans but do
  not contain a YAML mapping with `changed`, `from`, `to`, and `reason`.
