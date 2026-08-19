---
name: accelerator-e2e-case-development
description: Develop evidence-backed E2E cases for accelerator plugin and operator releases. Use when a GPU, NPU, HAMi, driver, device-plugin, telemetry, or scheduling release needs source-delta risk analysis, existing-case coverage comparison, missing case implementation, candidate rerun selection, or a live-execution handoff to release and compatibility-test skills.
---

# Accelerator E2E Case Development

Build an **impact cone** from release delta to runtime evidence. Own case analysis,
design, implementation, and static validation. Leave release gate orchestration to
`accelerator-component-release` and live hardware execution to
`accelerator-compatibility-test`.

## 1. Establish the delta

Resolve the repository, base and target commits, candidate identity, package identity,
and existing release materials. Run:

```bash
python3 scripts/collect-release-delta.py \
  --repo <source-repo> --base <tested-base> --target <current-target> \
  --output <release-evidence>/case-development/release-delta.json
```

For a new project without a tested base, inspect its build metadata, deploy manifests,
controllers, CRDs, values, and test tree using `references/project-discovery.md`.

Complete when every changed path is classified as behavior, packaging, deployment,
test, documentation, or generated output, and every exclusion has a reason.

## 2. Trace the impact cone

For every behavioral, packaging, or deployment change, trace:

```text
source/config -> rendered artifact -> deployed object -> runtime behavior -> user outcome
```

Record affected hardware, OS, lifecycle, allocation mode, integration, and failure
mode. Separate source capability, package exposure, deployed configuration, and live
runtime evidence.

Complete when every in-scope delta has either a full trace to an observable outcome
or a named investigation gap with owner and verification action.

## 3. Compare cases and evidence

Inventory existing cases before designing new ones. Read
`references/evidence-states.md`, then mark each relevant assertion as reusable,
invalidated, partial, missing, blocked, or out of scope. Candidate identity changes
invalidate evidence for changed operands even when the surrounding journey passed.

Produce a case-impact table with:

```text
case | affected assertion | prior evidence | reusable? | required action | reason | status
```

Complete when every impact-cone outcome maps to an existing assertion or an explicit
case gap, and every prior PASS has a reuse decision.

## 4. Design and implement the smallest sufficient cases

Read `references/case-contract.md`. Prefer strengthening an existing case when its
user journey already contains the affected behavior. Add a new case only for a new
contract, lifecycle transition, owner boundary, or independently diagnosable failure.

Implement assertions for resolved input, rendered/deployed state, runtime identity,
functional outcome, evidence capture, and cleanup where applicable. Preserve project
conventions and unrelated worktree changes.

Complete when every case gap has executable setup, assertions, evidence paths,
cleanup, status semantics, and a stable case ID; changed scripts pass project-local
syntax and contract tests.

## 5. Validate and hand off live execution

Run the narrow static tests first, then the complete project-local static gate. Keep
static PASS distinct from live PASS. Produce a live execution handoff containing:

- exact candidate/package and immutable operand identities
- environment and hardware prerequisites
- ordered cases and rerun rationale
- expected evidence paths and cleanup ownership
- blockers and mutation requiring approval

Use `accelerator-compatibility-test` for authorized live hardware execution. Return its
action result to `accelerator-component-release`; update release facts only from
validated evidence.

Complete when static validation is recorded and every required live assertion is
either PASS with candidate-bound evidence or remains explicitly NOT RUN/BLOCKED with a
next action. A release claim requires the release orchestrator's remaining gates.

## Output

Store task output under the owning release evidence directory, never inside this
skill. Return:

```json
{
  "actionId": "action.e2e-case-development",
  "status": "succeeded|warning|blocked|failed",
  "summary": {
    "base": "<commit>",
    "target": "<commit>",
    "changedCases": [],
    "requiredLiveCases": [],
    "reusableEvidence": [],
    "producedFacts": [],
    "evidencePaths": []
  }
}
```
