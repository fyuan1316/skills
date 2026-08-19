# HAMi Release Decision Scoring Model

## Decision Principle

Minor upstream releases create a default expectation to follow. They do not automatically force a downstream release. The downstream decision must combine:

- upstream delta value
- customer and product demand
- fix/security urgency
- downstream overlay risk
- validation feasibility
- operational timing

Use evidence for every score. If a factor cannot be evidenced, score it as `0` and list it as an unknown.

Run the veto gates first. Scoring explains urgency and priority; it does not override a hard blocker.

## One-Vote Veto Gates

If any gate is true, the default verdict is `NO-GO` or `DEFER` until the gate is cleared.

| Gate | Veto Condition | Typical Clearance |
|---|---|---|
| Build blocker | candidate cannot build image/chart locally or in CI | fix build or exclude broken feature |
| Chart/install blocker | default chart cannot render/install on supported clusters | fix chart or gate feature default-off |
| Critical regression | known regression affects existing supported production path | fix or cherry-pick around it |
| Missing hardware validation | release value depends on GPU/NPU hardware path that cannot be tested | restrict scope or defer |
| Incompatible downstream overlay | Alauda `.build`, ModulePlugin, registry, image, or ACP install path cannot be reconciled | patch overlay |
| Kubernetes / ACP compatibility blocker | Kubernetes-related dependencies jump and the downstream supported Kubernetes version matrix or target ACP Kubernetes version is unknown, lower than the target dependency line, or includes older unsupported clusters | infer the dependency line from effective `k8s.io/*` versions, confirm the downstream minimum supported K8s version and ACP target Kubernetes version, then validate or restrict release scope |
| Security/legal blocker | license, CVE, or supply-chain issue is worse than current release | resolve or exception approval |
| Supportability blocker | no rollback, no observability, or no owner for a changed critical path | add rollback/test/owner |

Classify each gate as `clear`, `blocked`, `unknown`, or `not applicable`. Treat `unknown` as a `DEFER` input when the gate touches the release's main value proposition or an existing production path.

## Positive Score

Maximum positive score: 100.

| Area | Weight | Score Guidance |
|---|---:|---|
| Release policy baseline | 10 | minor release = 8-10, patch release = 4-6, major release = 5 plus extra risk review |
| Customer/product demand | 20 | committed customer or roadmap hardware = 15-20; internal nice-to-have = 3-8 |
| Critical fixes | 20 | production bug/security/data race/panic/scheduler allocation fix = 4-8 each, cap 20 |
| New capabilities | 20 | new supported hardware/resource mode/runtime path = 6-10 each, cap 20 |
| Operational improvements | 10 | observability, webhook selectivity, readiness, HA, rollback, docs that reduce support load |
| Ecosystem alignment | 10 | DRA/K8s/NVIDIA/Ascend ecosystem direction, dependency freshness, upstream support window |
| Cherry-pick cost avoided | 10 | many coupled fixes/features that are hard to backport justify following the release |

## Negative Risk Score

Maximum risk score: 100.

| Area | Weight | Score Guidance |
|---|---:|---|
| Scheduler/device-plugin contract risk | 20 | allocation, annotation, webhook, scheduler cache, resource naming changes |
| Runtime/hook risk | 15 | `libvgpu`, CDI/envvar/runtimeClass, driver/toolkit, CUDA/NVML/Ascend runtime changes |
| Chart/install risk | 15 | CRDs/subcharts/ModulePlugin/image values/defaults/RBAC/ServiceMonitor changes |
| Dependency/toolchain risk | 15 | Go/K8s/NVIDIA/Ascend dependency jumps, generator drift, base image changes |
| Downstream overlay risk | 15 | `.build`, ACP packaging, registry, relatedImages, local patches, docs/site split |
| Validation gap | 15 | required GPU/NPU/platform matrix is unavailable or expensive |
| Operational timing | 5 | release window, customer freeze, support staffing |

## Verdict Thresholds

Let `net = positive - risk`.

| Verdict | Rule |
|---|---|
| GO | no veto, positive >= 65, net >= 25, validation matrix available |
| GO with constraints | no veto, positive >= 55, net >= 10, risks can be scoped by default-off flag, target hardware, or customer opt-in |
| DEFER | no veto, positive < 55 or net < 10, but track or cherry-pick selected fixes |
| NO-GO | any unresolved veto, or risk >= 70 with no mitigation |

## Required Evidence Buckets

Collect these before final verdict:

1. Upstream release note summary, if available.
2. Git range: current downstream base vs target upstream release.
3. Commit buckets: features, fixes, security, dependencies, docs.
4. File buckets: scheduler, device-plugin, runtime/hook, chart, build, docs, tests.
5. Downstream overlay comparison: candidate downstream branch vs current downstream branch.
6. Customer demand: named requests, bugs, hardware, deadlines.
7. Validation matrix: local tests, chart render, GPU e2e, NPU e2e, install/upgrade/rollback.
8. Kubernetes / ACP compatibility matrix: effective `go.mod` K8s library versions, basic dependency-line inference (`k8s.io/* v0.N` roughly maps to Kubernetes `1.N`), downstream minimum supported Kubernetes version, target ACP version and its Kubernetes version, API server install/upgrade validation, and kubelet/device-plugin interaction validation.

## Decision Heuristics

- Prefer `GO with constraints` over broad `GO` when the value is tied to one hardware family, one customer, or one default-off feature.
- Prefer `DEFER with cherry-picks` when the score is driven by a small number of isolated fixes and the target release carries broad scheduler/device-plugin/chart risk.
- Prefer `GO` when the high-value fixes/features are coupled across scheduler, device-plugin, chart, and dependency changes so cherry-picking would recreate the upgrade risk anyway.
- Do not score customer/product demand without a named source: customer, issue, roadmap item, security requirement, or support escalation.
- Do not score validation as available because manifests render. Real GPU/NPU value needs hardware-path evidence or an explicit release constraint.
- Treat Kubernetes dependency jumps as P0 risk, not routine dependency churn. A `client-go` / `k8s.io/*` / `kubelet` / `kube-scheduler` / `controller-runtime` jump can break older cluster compatibility or change API/runtime expectations. The report must show the basic version inference first, then state clearly that the exact minimum supported cluster version cannot be proven from `go.mod` alone. For Alauda downstream releases, ACP is the primary Kubernetes platform dependency; the target ACP version and its Kubernetes version must be included in the P0 audit.
- Put raw commit hashes in an appendix. The decision body should use human-readable themes, release-note value statements, risks, and validation status.

## 中文报告模板

```markdown
# HAMi 发版决策: <component> <current> -> <target>

## 结论

- 决策:
- 净分:
- 一票否决状态:
- P0 风险:
- 建议下一步:

## 证据

- 当前下游 ref:
- 目标上游 ref:
- 下游候选 ref:
- Release note:
- Commit 数 / diffstat:

## 价值驱动

| 驱动因素 | 得分 | 证据 |
|---|---:|---|

## P0 风险

| 风险项 | 状态 | 证据 | 解除条件 |
|---|---|---|---|

## 风险驱动

| 风险 | 得分 | 缓解措施 |
|---|---:|---|

## 一票否决项

| 否决项 | 状态 | 证据 / 解除条件 |
|---|---|---|

## 验证矩阵

| 范围 | 要求 | 当前状态 |
|---|---|---|

## 未知项 / 跟进项

| 未知项 | 为什么重要 | 负责人 / 下一步检查 |
|---|---|---|

## 决策说明

- 为什么现在发版或暂缓:
- 如果暂缓，需要 cherry-pick 什么:
- 什么条件会改变当前决策:
```
