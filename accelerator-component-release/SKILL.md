---
name: accelerator-component-release
description: Orchestrate Alauda accelerator component releases from a source repo and branch to audit-ready release materials. Use when releasing or auditing HAMi/HAMi WebUI/GPU/NPU/Ascend/vGPU/vNPU accelerator components, building a release profile, driving source-first RC/formal build loops, closing release gaps, checking artifacts repo or AC listing, updating product docs, or generating the post-AC plugin release email.
---

# Accelerator Component Release

Use this skill as the release orchestrator. Keep it focused on profile, state, gate, gap, evidence, and audit decisions. Delegate mechanical work to specialist skills and scripts.

## Core Model

Drive every release with this loop:

```text
conversation -> release profile -> facts -> gaps/actions -> specialist skill
  -> action result -> profile facts -> next loop -> audit-ready materials
```

The first release action is material initialization, not a BuildRun. A release
must have its canonical documentation directory and profile skeleton before any
RC build, package sync, cluster rollout, formal tag, or AC mutation.

Default start mode is `source-first`: the user can provide only a local project, branch, target version, and constraints. Package URL, checksum, image refs, image digests, formal package, AC listing, and docs evidence should be produced by actions and written back into the profile.

Use the accelerator-test design docs as the detailed reference when needed:

```text
/Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/accelerator-test/docs/accelerator-release-automation
```

For the completed ADP v1.3.0 lessons, read `references/adp-v130-lessons.md`.

When starting a new component release, read `references/next-release-readiness.md`
before the first runner pass.

When preparing the cross-project gap evaluator, read
`references/release-evaluator-design-plan.md` and collect observations using
`references/release-observation-schema.md`. Do not implement the evaluator
until the rule-freeze criteria in that plan pass across the reference projects.

When a release needs `artifacts-plugin`, AC upload, artifacts-repo registration,
or related-image/package failures, read
`references/plugin-package-and-related-images.md`.

When the final installable package exists, read
`references/formal-package-smoke.md` before declaring the formal package
correct or allowing AC upload.

After AC CN/IO listing is verified, read
`references/plugin-release-email-template.md` and generate the Chinese plugin
release email with `scripts/render-plugin-release-email.py`. Keep Markdown as
the internal audit record and provide Outlook-compatible HTML as the
user-facing email. Generate both from the same JSON facts. This workflow ends
after returning or saving the email content and has no email-delivery step.

## Specialist Boundaries

Delegate instead of reimplementing:

| Work | Preferred owner |
|---|---|
| Edge BuildRun query/trigger | `edge-buildrun-ops` |
| package-minio/package digest discovery | `package-artifact-discovery` |
| OLM/package rollout | `edge-plugin-package-rollout` or `sync-bundle` |
| Final formal package smoke | `edge-plugin-package-rollout` plus `accelerator-compatibility-test` |
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
9. **Plugin package availability**: AC upload requires a packaged plugin/install artifact URL. Building it with `artifacts-plugin` is optional: skip it when the component pipeline already produced the formal plugin package, and use it only as the fallback build path when the component pipeline produced chart/image metadata but no plugin package.
10. **Formal package smoke**: deploy the exact final installable package in one representative non-production environment and verify component readiness, one accelerator workload, actual runtime image digests, and cleanup. Retag, matching source commits, matching image digests, package-content inspection, and successful package construction do not waive this gate. Do not declare the formal package correct until `gate.formal-package-smoke.passed=true`.
11. **AC upload/listing**: upload is a final mutating action. Run only after the formal package smoke gate and all other blocking gaps except the post-AC docs gate are closed, the user approves upload, and the branch/parameter table is confirmed.
12. **Release email draft**: after AC CN/IO upload and listing are verified, automatically generate internal `11-release-email.md` and user-facing `11-release-email-outlook.html` in the canonical release directory. Use the strict two-column table and field order in `references/plugin-release-email-template.md`, populate both from the same verified release facts, and record `communication.release-email.generated=true` only after both outputs are synchronized and validated. Return or save the Outlook-compatible HTML as the delivery format; this workflow does not send email. If the public documentation URL is not yet verified, mark both materials as drafts and do not claim that the documentation is published.
13. **Docs**: product docs/release notes/version docs are a post-AC gate. Run docs update/check only after formal tag provenance, formal artifacts, artifacts-repo registration, plugin package availability, formal package smoke, and AC CN/IO listing are complete, unless docs are explicitly declared not required. The docs gate must classify package-owned/related images separately from package-external runtime images and record how each is acquired, mapped or rewritten, architecture-checked, and verified by actual runtime image IDs.

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

After verified AC CN/IO listing, add this generated communication material:

```text
11-release-email.md
11-release-email-outlook.html
```

Create both outputs with `scripts/render-plugin-release-email.py --html-output`
and retain their shared input JSON under `evidence/release-email/`. Record the
renderer outputs and action result under
`evidence/actions/action.post-ac-release-email/`.

### Mandatory material initialization

Use the bundled template factory at the start of every new project release:

```bash
python3 /Users/yuan/.codex/skills/accelerator-component-release/scripts/init-release-materials.py \
  --component <component> \
  --version <version> \
  --source-branch <branch> \
  --output <repo>/docs/releases/<component>-<version>

python3 /Users/yuan/.codex/skills/accelerator-component-release/scripts/verify-release-materials.py \
  --release-dir <repo>/docs/releases/<component>-<version>
```

The factory is non-destructive: it refuses to overwrite an existing release
file unless `--force` is explicitly used. It creates the profile, all standard
review documents, `evidence/README.md`, and the action/evidence directories.
The canonical `<component>-<version>` directory is required even when an
isolated `<component>-<version>-test` rehearsal directory is also used.

`verify-release-materials.py` is a hard pre-mutation check. Do not trigger an
RC BuildRun or create/push a formal tag when it fails. Record the generated
directory and verification result as `material.release-skeleton.created` and
`gate.release-material-skeleton.passed` in the profile/action evidence.

Read `references/release-material-template-contract.md` when a component has
special package, hardware, or product-doc sections. Do not reconstruct the
standard file set from another project's directory during a release.

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
