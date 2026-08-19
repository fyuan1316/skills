---
name: hami-release-decision
description: Evidence-based release go/no-go decision workflow for Alauda HAMi ecosystem components. Use when deciding whether to follow an upstream HAMi/HAMi-core/HAMi-WebUI/accelerator component release, comparing upstream release notes or git commits against the current downstream version, scoring urgency and necessity, applying one-vote veto rules, or producing a release decision memo for HAMi component version planning.
---

# HAMi Release Decision

Use this skill before `hami-version-upgrade`. It answers "should we release this new upstream version downstream?" rather than "how do we upgrade?"

Treat the Codex runtime copy in `~/.codex/skills/hami-release-decision` as the operational copy. Mirror the same skill directory into `fy-skills/hami-release-decision` for git storage and sharing after functional changes.

Write decision reports in Chinese by default because the audience is internal maintainers. When returning a generated report to the user, include a clickable absolute local file link so the document can be opened directly.

Persist release decision reports as downstream assets in the target component repository, not under `/tmp` or `/private/tmp`. For HAMi, default to `docs/downstream-release-decisions/hami-<target-version>-release-decision.md` so the file is clearly an Alauda/downstream follow-up decision rather than an upstream HAMi release artifact. Temporary files may be used while drafting, but final reports must not depend on temporary local paths.

## Workflow

1. Establish scope:
   - component: `HAMi`, `HAMi-core`, `HAMi-WebUI`, `ascend-device-plugin`, or related accelerator component
   - current downstream ref/version
   - target upstream ref/version
   - downstream branch, if already prepared
   - customer drivers: open customer requirements, Sev/P0 bugs, security asks, hardware roadmap

2. Collect evidence:
   - Fetch upstream release notes. Prefer a product/human-readable release note over raw GitHub PR lists, and keep the source link in the report.
   - Always verify with git: commits, diffstat, changed subsystems, submodule changes, chart/API changes.
   - Compare Kubernetes-related dependencies in `go.mod`, including effective versions after `replace`. Treat a target-side `k8s.io/*`, `k8s.io/kubelet`, `k8s.io/kube-scheduler`, or `controller-runtime` jump as a P0 compatibility risk until the supported Kubernetes version matrix is confirmed.
   - For HAMi, separate upstream release refs from Alauda downstream overlay refs. Do not treat `.build/build.yaml` or `module-plugin.yaml` as universal upstream facts.
   - Run `scripts/hami-release-decision.sh` to produce the evidence scaffold. The script is read-only and should be safe to run from macOS against local refs.

3. Apply veto gates before scoring:
   - Read `references/scoring-model.md`.
   - If any veto is true, default verdict is `NO-GO` or `DEFER`, even when the score is high.

4. Score the release:
   - Use the scoring table in `references/scoring-model.md`.
   - Score both positive value and negative risk.
   - Include evidence lines for every non-zero score. No evidence, no score.

5. Decide:
   - `GO`: release candidate should proceed into upgrade and e2e.
   - `GO with constraints`: release only for named scenario/customer/hardware, or behind default-off flags.
   - `DEFER`: no near-term release, but track or cherry-pick targeted fixes.
   - `NO-GO`: blocked by veto or unacceptable risk.

6. Route next action:
   - `GO` or `GO with constraints` -> use `$hami-version-upgrade` when available, then validate with `$accelerator-compatibility-test` or the `fy-skills/hami-dev` e2e path.
   - `DEFER with fixes` -> create a cherry-pick list and use `$hami-dev-test-iterate` or `$hami-debug-workflow`.
   - `NO-GO` -> write the blocker and the condition that would reopen the decision.

## Script

Run:

```bash
skill_dir="${CODEX_HOME:-$HOME/.codex}/skills/hami-release-decision"
[ -d "$skill_dir" ] || skill_dir="$(pwd)/hami-release-decision"
bash "$skill_dir/scripts/hami-release-decision.sh" \
  --repo /path/to/HAMi \
  --current-ref release-2.8 \
  --target-ref upstream/release-v2.9 \
  --downstream-ref release-2.9-alauda \
  --component HAMi \
  --output /tmp/hami-release-decision.md
```

The script is read-only. It writes a markdown evidence report with:

- ref/version summary
- commit count and diffstat
- commit buckets for fixes, features, security, deps, docs
- changed subsystem inventory
- critical path signals for version, chart, `.build`, ModulePlugin, `go.mod`, and `libvgpu`
- submodule, downstream overlay, release note, and customer-driver inputs
- suggested validation matrix
- a blank scoring table using the release decision model

## Output Contract

Final answers or reports must include:

- prominent decision summary at the top; do not bury the conclusion under commit lists
- decision: `GO`, `GO with constraints`, `DEFER`, or `NO-GO`
- current and target refs
- one-vote veto status
- score summary
- decision-basis table with human-readable value/risk evidence
- top release drivers
- top risks
- Kubernetes compatibility status when K8s dependencies change
- unresolved unknowns
- required validation matrix
- next action owner/path
- clickable report link, for example `[报告](/absolute/path/report.md)`

Do not claim "must release" from minor-version policy alone. Minor releases create a default expectation to evaluate and often to follow, but the final decision must survive veto gates and evidence scoring.

Keep raw commit hashes in an appendix or traceability section only. The main body should explain what changed, why it matters, and what decision it affects.

## References

Read `references/scoring-model.md` for the decision rubric, veto gates, scoring weights, and report template.
