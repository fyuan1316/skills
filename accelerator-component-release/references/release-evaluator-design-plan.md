# Release Gap Evaluator Implementation Plan

> **For Codex:** Use the `executing-plans` skill to implement this plan task-by-task after the rule-freeze review is complete.

**Goal:** Derive release gaps and the next safe action consistently across HAMi, NFD, HAMi Ascend device-plugin and InferNex without encoding one project's packaging model as a universal rule.

**Architecture:** Keep a universal release state machine and candidate-scoped fact model in the accelerator release skill. Put package, hardware, artifact and delivery differences in a component adapter. Start with a read-only evaluator and replay fixtures; add mutation preflight only after the evaluator produces correct results for all reference projects.

**Tech Stack:** YAML release profiles, JSON action results, Markdown evidence, Python read-only evaluator, pytest fixtures, existing specialist skills and Edge/package/cluster evidence.

---

## Current decision

Do not implement `evaluate-release.py` yet. The existing material factory is useful, but the gap semantics, fact scope, invalidation rules and action dependency graph must first be validated against four real release histories.

## Reference sample matrix

| Sample | Package/delivery | Hardware | Main variant to learn |
|---|---|---|---|
| HAMi | Chart/plugin | NVIDIA GPU | multi-image GPU compatibility and package promotion |
| NFD v0.18.3 | Chart/plugin | NVIDIA + Ascend | complete RC/formal/package-smoke/AC lifecycle |
| HAMi Ascend device-plugin | Chart/plugin | Ascend NPU | driver/device-plugin and NPU matrix gates |
| InferNex Bridge | OLM bundle/plugin | Ascend NPU | CRD bundle, modelcar, PD/aggregate and runtime dependencies |

## Rule-freeze criteria

Do not write the evaluator until all four samples have an observation record containing:

- release identity and candidate identity;
- source branch, commit and formal tag provenance;
- initial gaps and the actual next action selected by the maintainer;
- every action result and produced fact;
- failures, retries, external blocks and approvals;
- package, rollout, e2e, security, formal smoke, AC and docs outcomes;
- evidence paths and the reason each gap closed.

A rule is universal only when it is supported by at least two different project types, or is explicitly marked as a universal release invariant. A rule seen in one project remains an adapter rule until a second sample confirms it.

## Target state machine

```text
material-init
  -> source-audit
  -> rc-build
  -> rc-artifact-discovery
  -> rc-package
  -> rc-rollout
  -> rc-function
  -> rc-security
  -> material-precheck
  -> formal-tag
  -> formal-build
  -> formal-package
  -> formal-package-smoke
  -> ac-upload
  -> product-docs
```

The evaluator must allow a component adapter to mark a stage `not_applicable`,
but never infer `passed` from `not_applicable` without an explicit reason and
approval where the stage is normally required.

## Candidate-scoped fact model

Every produced fact must carry this identity:

```yaml
fact: build.rc.images.digest.exists
value: true
scope:
  component: infernex-bridge
  targetVersion: v26.6.0
  candidateVersion: v26.6.0-alauda.4
  sourceCommit: e0052c8
  imageDigests:
    controller: sha256:...
    bundle: sha256:...
observedAt: 2026-07-16T14:10:13Z
evidence:
  - evidence/actions/candidate-build-discovery.json
```

Required invalidation rules:

- source commit changes invalidate downstream package, e2e, security and smoke facts;
- image digest changes invalidate runtime e2e and package smoke facts;
- package checksum changes invalidate package smoke and AC facts;
- environment or dependency version changes invalidate only the affected test facts;
- a historical candidate can explain a gap but cannot close a newer candidate gap.

## Gap state semantics

| State | Meaning |
|---|---|
| `open` | required fact is absent |
| `stale` | fact exists but candidate/evidence identity does not match |
| `blocked` | next action is known but an external prerequisite is unavailable |
| `closed` | required facts exist and verification passed |
| `accepted` | explicit owner/approval/expiry exists for a non-zero risk |
| `deferred` | non-blocking work is recorded with a follow-up action |

`unknown` is never equivalent to `closed`.

## Action contract

Every action definition must declare:

```yaml
id: action.rc-package
ownerSkill: edge-buildrun-ops
requires: []
produces: []
invalidates: []
mutates: []
approval: decision.rc-package.approved
verifyAction: action.rc-package-discovery
blocks: []
```

The next action is selected by: blocking severity, satisfied dependencies,
current release stage, then specialist ownership. If no action is runnable,
the evaluator returns `blocked` with the exact missing external condition.

## Planned implementation tasks

### Task 1: Collect observation records

**Files:**

- Create: `references/fixtures/README.md`
- Create: `references/fixtures/<project>/observation.yaml`
- Source: each project's existing release profile, progress table, gaps and action evidence

Record the real action order for HAMi, NFD, HAMi Ascend device-plugin and InferNex. Do not normalize project-specific names during collection.

### Task 2: Freeze the universal versus adapter boundary

**Files:**

- Create: `references/release-adapter-contract.md`
- Modify: `references/release-evaluator-design-plan.md`

Define universal fields for source, candidate, facts, gaps, gates and approvals. Define adapter fields for packaging type, hardware matrix, package path, artifacts-repo mode, image inventory and optional stages.

### Task 3: Write replay scenarios before implementation

**Files:**

- Create: `references/fixtures/scenarios/no-materials.yaml`
- Create: `references/fixtures/scenarios/stale-rc-evidence.yaml`
- Create: `references/fixtures/scenarios/formal-tag-mismatch.yaml`
- Create: `references/fixtures/scenarios/external-environment-block.yaml`
- Create: `references/fixtures/scenarios/all-rc-gates-closed.yaml`

Expected outputs must include current state, open/stale/blocked gaps, next action and mutation decision.

### Task 4: Implement the read-only evaluator

**Files:**

- Create: `scripts/evaluate-release.py`
- Create: `scripts/tests/test_evaluate_release.py`

The first implementation reads YAML/JSON only. It must not trigger Edge, write artifacts, alter tags, upload packages or modify clusters.

### Task 5: Add mutation preflight

**Files:**

- Modify: `scripts/evaluate-release.py`
- Modify: `scripts/validate-action-result.py`
- Create: `scripts/tests/test_mutation_preflight.py`

Reject mutation when a P0 gap is open/stale/blocked, candidate identity is inconsistent, approval is absent/expired, or runtime mutation opt-in is absent.

### Task 6: Replay all four projects and review false positives

Run the evaluator against the four real profiles and fixtures. For every mismatch, update the adapter contract or rule specification before adding another universal rule.

### Task 7: Integrate into the release skill

**Files:**

- Modify: `SKILL.md`
- Modify: `references/next-release-readiness.md`
- Modify: `references/release-material-template-contract.md`

Make the evaluator output the mandatory `next action` before specialist execution. Keep the material skeleton check as one gap, not the whole release gate.

## Acceptance criteria before enabling automation

- all four project histories replay to the expected next action;
- `.3` evidence cannot close a `.4` gap;
- formal tag mismatch blocks formal build;
- missing package checksum blocks rollout/formal tag;
- missing e2e or security evidence blocks formal tag;
- missing formal package smoke blocks AC upload;
- unavailable environment produces a precise `blocked` result;
- no mutation occurs in read-only mode;
- action result facts are rejected when their candidate scope is inconsistent.

## Stop conditions

Pause implementation and return to rule review when two projects require
contradictory interpretations of the same field, when a gate has no verifiable
evidence source, or when the evaluator would need to infer success from chat
memory or a tag name alone.
