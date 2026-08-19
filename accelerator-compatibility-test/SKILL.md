---
name: accelerator-compatibility-test
description: Run and analyze GPU/NPU compatibility e2e for Alauda accelerator products through the local accelerator-test repository. Use for HAMi, HAMi WebUI, PGPU, pNPU, NVIDIA GPU, Ascend NPU, vGPU/vNPU, release compatibility, e2e matrix, JUnit report collection, and accelerator-test troubleshooting. Triggers include GPU/NPU 兼容性, HAMi e2e, PGPU e2e, pNPU e2e, Ascend, NVIDIA, accelerator-test, release test evidence.
---

# Accelerator Compatibility Test

Use the `accelerator-test` repo as the execution backend. Do not reimplement platform detection or case selection unless the backend itself is being fixed.

## Inputs

Collect or infer:

| Input | Required | Notes |
|---|---:|---|
| `KUBE_CONF` | yes | Target cluster kubeconfig path. Use global/business kubeconfigs if deployment needs both. |
| Platform | yes | `hami`, `pgpu`, `pnpu`, or `auto`. Prefer explicit platform for release evidence. |
| Scope | no | `smoke`, `sanity`, `full`, or `focus`; default `full`. |
| Deploy allowed | yes | Default automation can deploy, but confirm for shared or production clusters. |
| Version | when deploying | `HAMI_VERSION`, `PGPU_VERSION`, `PNPU_NPU_OPERATOR_VERSION`, etc. |
| Accelerator family | when ambiguous | `nvidia` or `ascend`; HAMi can support both. |
| Image registry | often | `E2E_IMAGE_REGISTRY` for CUDA images in restricted networks. |

## Execution

Prefer the bundled wrapper:

```bash
/Users/yuan/.codex/skills/accelerator-compatibility-test/scripts/run-accelerator-e2e.sh \
  --root /Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/accelerator-test \
  --kube-conf /path/to/kubeconfig \
  --platform hami \
  --scope full \
  --hami-version <version-or-tag>
```

Common variants:

```bash
# Existing HAMi cluster; do not mutate deployment
run-accelerator-e2e.sh --kube-conf /path/to/config --platform hami --scope sanity --no-deploy

# HAMi Ascend vNPU
run-accelerator-e2e.sh --kube-conf /path/to/config --platform hami --hami-deploy-mode vnpu --accel ascend

# PGPU with explicit version
run-accelerator-e2e.sh --kube-conf /path/to/config --platform pgpu --pgpu-version <version>

# pNPU with explicit operator version
run-accelerator-e2e.sh --kube-conf /path/to/config --platform pnpu --pnpu-operator-version <version>
```

The wrapper writes timestamped artifacts under `test/e2e/.artifacts/skill-runs/<run-id>/`, including command, log, summary, and copied JUnit files when present.

Before deployment or test execution, the wrapper runs a tool preflight. It
verifies Go availability, then reads the required Ginkgo CLI version from the selected accelerator-test
checkout's `go.mod`, reuses an exact match, or installs the exact version into
the user tool cache. The resolved binary and version are recorded in
`command.env`, `summary.env`, and `preflight.log`. Do not work around a missing
Ginkgo CLI manually; fix or extend the preflight when a repeatable tool issue is
found.

## Result Analysis

Report:

- platform, scope, deploy mode, version inputs, cluster kubeconfig path
- artifact directory
- exit code and final verdict
- failed specs from JUnit/logs, grouped by layer when possible
- whether the failure should route to `$hami-debug-workflow`

Use `references/accelerator-test-map.md` when choosing variables, target cases, or interpreting platform-specific failures.
Use `references/common-test-failures.md` before manually repairing a repeated
test-environment failure.

## Safety

- Never print kubeconfig contents or platform credentials.
- Treat `*_AUTO_DEPLOY=true` as a cluster mutation.
- If the cluster is shared, prefer `--no-deploy` until the user explicitly allows upgrade/deploy.
- Keep test namespace explicit with `--namespace` when multiple runs may overlap.
