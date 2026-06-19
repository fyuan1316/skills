---
name: bundle-iterate
description: Drive a code-to-cluster iteration loop for an Alauda OLM Bundle product (e.g., InferNex-Bridge). One iteration = commit + push → Katanomi buildrun → harvest image tag → violet create/package on devpod → scp tgz to npuserver → violet push to target ACP cluster → recreate Subscription → verify CSV Succeeded + Pod Running + reconcile logs clean. Use when the user asks to "build and install the bundle on kubeos2", "iterate on the operator bundle", "fix and re-sync the bundle", "test bundle install end-to-end", or describes a code-change → verify-install loop on isolated ACP cluster (kubeos2 via npuserver). Each iteration is one tool-driven pass; the model loops by re-invoking the skill after each code change.
---

# Bundle Iterate (代码→流水线→目标集群安装验证 闭环)

Single iteration of the closed-loop development cycle for an Alauda OLM Bundle being delivered to an isolated ACP cluster (the kubeos2 air-gap scenario). Each pass produces a verdict: success (CSV Succeeded, Pod Running, reconcile errors empty) or failure (with diagnostic pointers).

## Topology (why this skill exists)

The kubeos2 cluster is isolated; neither cluster can reach `build-harbor.alauda.cn` and devpod cannot reach the kubeos2 ACP at `https://127.0.0.1`. **No single host can do the full sync.** The skill formalizes the split:

```
devpod (reaches build-harbor)                npuserver (reaches kubeos2 ACP)
  violet create --artifact=<bundle-ref>      violet push --clusters=kubeos2
    (pull operator + bundle image)             --platform-address=https://127.0.0.1
  violet package --output=*.tgz              ─────────────────────────────────────►
  ────────scp tgz (~80M)────────►            (uploads images to cluster registry,
                                              creates ArtifactVersion, refreshes
                                              packagemanifest channel head)
```

Then the local kubeconfig wrapper `kos2` (on npuserver) interacts with the kubeos2 API to manage Subscription / CSV / Pod state.

## When to use

- "Fix CSV / bundle / RBAC / controller and re-sync to kubeos2"
- "Bundle install failed with X on kubeos2 — diagnose and iterate"
- "Verify the next CI build installs cleanly"
- "End-to-end test after a Bridge code change"

Do **not** use for:
- First-time bundle authoring (no prior install state) — author the bundle skeleton first, then this skill kicks in
- Pure chart-path users (helm install on a connected cluster — no air-gap split needed)

## Prerequisites

| File | Purpose | Key fields |
|---|---|---|
| `envs/env.edge` | Katanomi BuildRun API auth | `TOKEN` (export as `EDGE_ENV_TOKEN`) |
| `envs/env.harbor` | build-harbor.alauda.cn pull creds | `USER`, `PSSSWORD` |
| `envs/env.gitlab` | gitlab-ce push (for already-pushed branches, mostly informational) | `GITLAB_TOKEN` |
| `envs/npuserver/kubeos2-kubeconfig.yaml` | kubeos2 API access via npuserver | bearer token |
| `envs/npuserver/kos2` | kubectl wrapper deployed at npuserver:/usr/local/bin/kos2 | — |
| `~/.ssh/config` `Host npuserver` | passwordless ssh to jumper/exec host | ProxyJump-compatible |
| `/tmp/violet` (devpod) | violet binary | downloaded from `http://package-minio.alauda.cn:9199/packages/violet/latest/violet_linux_amd64` |
| `violet` (npuserver, already installed at `/usr/local/bin/violet`) | platform-side push | — |
| **Platform credentials (out-of-band)** | npuserver ACP login | `--platform-address=https://127.0.0.1 --platform-username=admin@cpaas.io --platform-password=<from user>` |

Also depends on sibling skills:
- `katanomi-buildrun` (trivial-things repo) — `create_buildrun.sh` + `wait_buildrun.sh`
- `sync-bundle` (fy-skills repo) — original same-host violet wrapper (we bypass for air-gap)

## Inputs (per project)

Collect or carry from project memory before executing:

| Input | Example | Source |
|---|---|---|
| Source branch | `feat/build-pipeline` | git |
| Katanomi build name | `fuyao-infernex-bridge` | Edge console URL / project memory |
| Build namespace | `aml-dev` | `envs/env.edge` `namespace=` field |
| Bundle artifact image | `build-harbor.alauda.cn/mlops/infernex/infernex-bridge-bundle` | bundle CSV / Makefile |
| Target cluster name | `kubeos2` | npuserver kubeconfig context |
| Install namespace | `infernex-system` | CSV `suggested-namespace` |
| Subscription / package name | `infernex-bridge` | bundle metadata `package.v1` |

If the user request is "iterate on the same project as last session", these come from the project memory entry (see `[[project-infernex-bridge-olm]]` for InferNex-Bridge).

## One iteration: 6 stages

### Stage 1 — Push to GitLab

User has already edited code (or the model just did). Push the current branch:

```bash
git -C <project-repo-root> push origin <branch>
# or force-push if history was rewritten:
git -C <project-repo-root> push --force-with-lease origin <branch>
```

### Stage 2 — Trigger Katanomi BuildRun and wait

```bash
source envs/env.edge && export EDGE_ENV_TOKEN="$TOKEN"
BR=$(bash skills/trivial-things/skills/katanomi-buildrun/scripts/create_buildrun.sh \
        --namespace aml-dev --build <build-name> --git-revision <branch> \
      | yq e '.metadata.name' - | tail -1)
bash skills/trivial-things/skills/katanomi-buildrun/scripts/wait_buildrun.sh \
  --namespace aml-dev --buildrun "$BR" --timeout-seconds 900 --poll-seconds 30
```

Wait for completion in the background — re-entry happens on completion notification. Do **not** poll manually.

Extract the new image tag from artifact output (or via `query_artifacts.sh`):

```bash
grep -oE 'v0\.0\.0-[a-z0-9.]+' "$BR_OUTPUT" | sort -u
```

### Stage 3 — violet create + package on devpod

Run the helper that wraps the harbor-authenticated create+package:

```bash
bash scripts/devpod-package.sh \
  --artifact build-harbor.alauda.cn/mlops/infernex/infernex-bridge-bundle:<TAG> \
  --output /tmp/inbridge.tgz \
  --platforms linux/arm64
```

The script reads `envs/env.harbor` for `USER`/`PSSSWORD` and runs:
```
violet create <out-dir> --default-catalog-source=platform \
  --artifact=<ART> --username=<U> --password=<P> \
  --platforms=<PLATFORMS>
violet package <out-dir> --username=<U> --password=<P> \
  --output=<tgz>
```

**Packaging rule — infernex-bridge is arm64-only** (the script default is generic
`linux/amd64,linux/arm64`; this rule is per-project, NOT a global default). kubeos2 /
Ascend is arm64, so for infernex-bridge **pass `--platforms linux/arm64` explicitly** —
amd64 is pure dead weight in the air-gap tgz: a full infernex-bridge bundle measures
**~3.5G amd64+arm64 vs ~2.4G arm64-only** (−1.1G). The 2.4G is then dominated by two
heavy ML images — `hermes-router-tokenizer` (~1.2G, arm64-only) + `hermes-router-prediction`
(~0.57G) = ~76% of the package; the rest of the `relatedImages` are small. Can't trim
further without changing the bundle's `relatedImages` set. (Measured 2026-06-12 on `…alauda.3`.)

Note: do **not** pass `--no-auth` to `violet package` when source images require auth (build-harbor does).

### Stage 4 — scp tgz to npuserver

```bash
scp /tmp/inbridge.tgz npuserver:/tmp/inbridge.tgz
```

Background this (~80MB, takes ~30-60s on Tencent network).

### Stage 5 — violet push from npuserver

```bash
bash scripts/npuserver-push.sh \
  --tgz /tmp/inbridge.tgz \
  --cluster kubeos2 \
  --platform-username admin@cpaas.io \
  --platform-password '<from user>'
```

Or directly:
```bash
ssh npuserver "PLATFORM_USERNAME='<u>' PLATFORM_PASSWORD='<p>' bash -s" <<'EOF'
violet push --force \
  --clusters=kubeos2 \
  --platform-address=https://127.0.0.1 \
  --platform-username="$PLATFORM_USERNAME" \
  --platform-password="$PLATFORM_PASSWORD" \
  /tmp/inbridge.tgz
EOF
```

### Stage 6 — Force resubscribe + verify

After history rewrites or version-number resets, OLM may not auto-upgrade (SemVer non-monotonic, stuck on `AtLatestKnown` of older version, or Failed CSV blocks). Reliable fix: delete subscription + CSV, recreate.

```bash
ssh npuserver "kos2 -n <install-ns> delete subscription <pkg> --ignore-not-found
kos2 -n <install-ns> delete csv --all --ignore-not-found
kos2 apply -f - <<'YAML'
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata: { name: <pkg>, namespace: <install-ns> }
spec:
  channel: alpha
  name: <pkg>
  source: platform
  sourceNamespace: cpaas-system
  installPlanApproval: Automatic
YAML"
```

Wait ~35s, then check:

```bash
ssh npuserver 'kos2 -n <install-ns> get subscription <pkg> -o jsonpath="CURRENT={.status.currentCSV}{\"\n\"}STATE={.status.state}{\"\n\"}"
kos2 -n <install-ns> get csv 2>/dev/null | tail -3
kos2 -n <install-ns> get pods 2>/dev/null | tail -3
kos2 -n <install-ns> logs deploy/<deployment> --tail=50 2>&1 | grep -iE "ERROR|Reconciler error"'
```

**Success signals**:
- `STATE=AtLatestKnown` AND `CURRENT=<expected-new-csv>`
- CSV phase `Succeeded`
- Pod `1/1 Running` with 0 restarts
- No `level=ERROR` or `Reconciler error` in last 50 log lines (allow PodSecurity warnings / other independent issues)

## Iteration loop (what the model does)

```
loop {
  edit code  →  Stage 1-6  →  verdict
    if success: report success, exit
    if failure:
      collect diagnostic (CSV reason, Pod logs, RBAC events)
      decide next code change
      continue
}
```

A loop cap of ~5 iterations is reasonable; beyond that, stop and ask the user.

## Failure triage cheatsheet (from real experience)

| Symptom | Most likely cause | Fix |
|---|---|---|
| Buildrun fails at `update_csv_related_images.sh: open ./values.yaml: no such file` | `values.yaml` not at repo root | Move `values.yaml` + `Makefile` to root, paths in CSV stay `packaging/bundle/manifests/...` |
| Subscription `ResolutionFailed: constraints not satisfiable: requires operator providing <GVK>` | CSV declares `customresourcedefinitions.required` GVK that no catalog operator owns | Drop the `required` block; document prereq CRDs in README |
| Pod CrashLoop `open /apiserver.local.config/certificates/tls.crt: no such file` | `--webhook-cert-path` points at wrong OLM-mounted dir | Use `/tmp/k8s-webhook-server/serving-certs` (OLM also mounts there with `tls.crt`/`tls.key`) |
| `no matches for kind X in version v1alpha1` while v1alpha2 served | Hardcoded GET on unserved API version | Add `meta.IsNoMatchError(err)` to NotFound-treat fallback, or change to storedVersion |
| `InferNexServiceConfig template not found in <ns>` | OLM cannot install CR instances; manual `kubectl apply` step missing | Add controller-side bootstrap (embed YAML + manager Runnable + RBAC `create`) |
| `Object X is already owned by another <Kind> controller Y` | Two CRs claim same dependent name | Either rename to per-owner (`<owner>-X`), or drop controllerRef and use a shared-resource controller |
| Subscription stuck on older CSV after force-push (counter reset to default.1) | SemVer pre-release comparison places new version below old | Delete old ArtifactVersions, delete sub+CSV, recreate sub → resolves to current head |
| `KubeAPIWarningLogger: would violate PodSecurity "restricted:latest"` | Reconciler-rendered Pod missing securityContext defaults | Set defaults in render code (allowPrivilegeEscalation=false, runAsNonRoot=true, capabilities.drop=ALL, seccompProfile=RuntimeDefault) |

## Red flags / common rationalizations

- Don't poll `wait_buildrun.sh` in a tight loop — use the harness background-task notification.
- Don't trust `subscription.status.state=AtLatestKnown` alone — verify `CURRENT` is actually the new CSV, not the old one. After artifact catalog updates, sub may remain on an outdated head until delete+recreate.
- Don't manually `kubectl apply` runtime templates as the success criterion — if the bundle requires manual templates, the install is incomplete; fix via controller bootstrap (#4 in our InferNex iteration history).
- "Just push the image, skip violet" — won't work in air-gap. Cluster cannot pull build-harbor; violet is what mirrors into cluster's internal registry.
- Don't print `PLATFORM_PASSWORD` or harbor `PSSSWORD` in command output. Pass via `bash -s` heredoc env, not argv.
- After history rewrite, the version-numbering counter restarts (git-derived). SemVer pre-release ordering can revert "current" → "earlier" tag. Always check packagemanifest channel head + force recreate Subscription.

## Output

After each iteration the skill returns a structured verdict (free-form text is fine, but include):

- Iteration #
- Image tag built
- Stage where failure (if any) occurred
- CSV phase / Subscription state / Pod state
- One-line diagnosis if failed
- Suggested next code change (when failed and cause is in code)
