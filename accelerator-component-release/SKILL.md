---
name: accelerator-component-release
description: Orchestrate Alauda accelerator component releases from a source repo and branch to audit-ready release materials. Use when releasing or auditing HAMi/HAMi WebUI/GPU/NPU/Ascend/vGPU/vNPU accelerator components, building a release profile, driving source-first RC/formal build loops, closing release gaps, checking artifacts repo or AC listing, or updating product docs after release.
---

# Accelerator Component Release

Use this skill as the release orchestrator. Keep it focused on profile, state, gate, gap, evidence, and audit decisions. Delegate mechanical work to specialist skills and scripts.

## Core Model

Drive every release with this loop:

```text
conversation -> release profile -> facts -> gaps/actions -> specialist skill
  -> action result -> profile facts -> next loop -> audit-ready materials
```

Default start mode is `source-first`: the user can provide only a local project, branch, target version, and constraints. Package URL, checksum, image refs, image digests, formal package, AC listing, and docs evidence should be produced by actions and written back into the profile.

Use the accelerator-test design docs as the detailed reference when needed:

```text
/Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/accelerator-test/docs/accelerator-release-automation
```

For the completed ADP v1.3.0 lessons, read `references/adp-v130-lessons.md`.

When starting a new component release, read `references/next-release-readiness.md`
before the first runner pass.

## Specialist Boundaries

Delegate instead of reimplementing:

| Work | Preferred owner |
|---|---|
| Edge BuildRun query/trigger | `edge-buildrun-ops` |
| package-minio/package digest discovery | `package-artifact-discovery` |
| OLM/package rollout | `edge-plugin-package-rollout` or `sync-bundle` |
| GPU/NPU/HAMi e2e | `accelerator-compatibility-test` |
| HAMi/device-plugin debugging | `hami-debug-workflow` |
| release-grade image CVE scan | `remote-trivy-scan` |
| image CVE fix | `baseimage-cve-fix` |
| release material audit | `plugin-release-review` local scan plus manual gate review |
| product docs update | docs/product documentation skill or direct docs repo workflow |

The orchestrator records what each specialist produced as facts and evidence paths. It should not hide specialist failures or silently mark gaps closed.

## Action Result Contract

Specialist skills must return machine-readable action results before profile
facts are updated. Prefer this shape:

```json
{
  "actionId": "action.rc-build-or-discover",
  "status": "succeeded",
  "summary": {
    "producedFacts": ["build.rc.discovery.attempted"],
    "evidencePaths": ["run/actions/action.rc-build-or-discover/buildrun.json"]
  }
}
```

For compatibility, legacy results with `action.id` are accepted, but new
specialist outputs should use top-level `actionId`.

Before applying any specialist output, validate it:

```bash
python3 /Users/yuan/.codex/skills/accelerator-component-release/scripts/validate-action-result.py \
  --profile <profile.yaml> \
  <action-result.json>
```

Only apply facts listed in `summary.producedFacts`. Do not manually mark gaps
closed from chat memory; let the next runner pass derive gap status from facts.

## Mandatory Gates

Use these guardrails before allowing mutation:

1. **RC build/artifacts**: RC package URL, package checksum, image refs, and image digests must be recorded.
2. **RC package/rollout**: package content, CSV/chart/relatedImages, OLM/Helm rollout, and runtime workload must be verified.
3. **Function**: release scenarios must pass on the blocking hardware matrix.
4. **Security**: build-time image scan is only a signal. Release-grade CVE scan is independent and runs after RC rollout, function test, and package content checks. Critical/High must be zero or have explicit release approval.
5. **Formal tag**: create and push a formal tag only after RC function/security/material gates pass and the user approves. Record remote peeled commit.
6. **Formal build**: trigger formal package build only from the formal tag, not directly from a release branch.
7. **Formal verification**: record formal package URL/checksum, formal image digests, package content proof, and formal scan.
8. **Artifacts repo**: for self-built components, `aml/artifacts` may be registration-only, but it still must contain `master` latest registration and `<component>-<version>` historical branch registration.
9. **AC upload/listing**: upload is a final mutating action. Run only after all other blocking gaps are closed, user approves upload, and the branch/parameter table is confirmed.
10. **Docs**: release is not done until product docs/release notes/version docs are updated or explicitly declared not required.

## Mutation Policy

Default to dry-run for mutating actions. Require both:

- profile/user approval fact, such as `decision.formal-tag-create.approved=true`
- explicit runtime opt-in, such as `ACCELERATOR_RELEASE_ALLOW_MUTATION=true`

This applies to RC BuildRun trigger, formal tag creation, formal BuildRun trigger, artifacts repo writes, AC upload, and docs repo commits/pushes.

Never print secrets. Resolve internal credentials from `/Volumes/macOS-2/Users/yuan/Dev/tools/envs` only inside the command that needs them.

## Material Shape

For each release, keep materials under:

```text
docs/releases/<component>-<version>/
```

Expected files:

```text
README.md
_progress-table.md
_release-readiness-gaps.md
_approvals.md
evidence/README.md
01-change-list.md
02-artifacts.md
03-test-report.md
04-security-report.md
05-legacy-issues.md
06-nonfunctional-decision.md
07-release-note.md
08-test-evidence.md
09-release-rounds.md
10-standard-review-checklist.md
docs-update.md
```

Use `plugin-release-review/scripts/scan_release_docs.py` as a signal scan, then manually verify gate correctness. Missing `ReleaseTestPlan`, `EnvironmentTemplate`, or `TestTemplate` keywords may be acceptable only when the material clearly records replacement evidence: deployment YAML or commands, environment export, test entrypoint, cases, JUnit/results, and artifact paths.

## Gap Handling

Classify gaps as `SCOPE`, `ARTIFACT`, `ENV`, `DEPENDENCY`, `DEPLOY`, `FUNCTION`, `COMPATIBILITY`, `SECURITY`, `NONFUNCTIONAL`, `MATERIAL`, `APPROVAL`, or `DOCUMENTATION`.

Every gap needs:

- owner skill
- blocking severity
- required facts
- evidence path
- next action
- verification action
- final status: closed, accepted, deferred, or not_a_blocker

Keep historical RC rounds. Do not erase failed or superseded rounds; mark which candidate is current and why older rounds only explain gap progression.

## Tool Cache

External tools should resolve from:

```bash
hack/accelerator-release-tool-cache.sh resolve <tool> <version>
```

Default cache root:

```text
~/.cache/accelerator-release/tools
```

Cache tools such as `violet`, `packtool`, `trivy`, and `skopeo`. Do not cache tokens, passwords, kubeconfigs, or registry credentials.
