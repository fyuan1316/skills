---
name: sync-bundle
description: Use when Codex needs to run or explain the sync-bundle workflow for syncing an artifact or operator bundle image into an Alauda platform catalog through the violet tool, including sync-bundle commands with an artifact and optional profile, bundle image synchronization, catalog push validation, violet packaging, and profile-specific config files.
---

# Sync Bundle

## Overview

Use the bundled `scripts/sync-bundle` wrapper, or an installed `sync-bundle` wrapper when it is already on `PATH`, to package an artifact with `violet` and push it to the configured Alauda platform catalog. Treat this as a live platform mutation: inspect inputs, avoid printing secrets, run the wrapper directly when the user asks for a sync, and report the artifact, profile, platform, clusters, and final result.

When the user describes a target in environment language such as "dev kubeos", "dev microos", "v100", or "上传到 dev kubeos 集群", prefer the envs-aware wrapper `scripts/sync-bundle-envs`. It resolves `/Volumes/macOS-2/Users/yuan/Dev/tools/envs/dev-*` and creates a temporary violet-sync profile, so `envs/` does not need persistent per-cluster `~/.config/violet-sync/*.env` files.

## Command Shape

Primary form:

```bash
sync-bundle <artifact> [profile]
```

Environment target form:

```bash
<skill-dir>/scripts/sync-bundle-envs <artifact> <env-or-alias> [cluster]
```

If `sync-bundle` is not on `PATH`, run the bundled script from this skill:

```bash
<skill-dir>/scripts/sync-bundle <artifact> [profile]
```

`<skill-dir>` is the directory containing this `SKILL.md`.

Examples:

```bash
sync-bundle charts/model-catalog
sync-bundle build-harbor.alauda.cn/mlops/model-registry-operator-bundle:v0.3.0-hotfix.6.1.g263306a3-dev-catalog-v0.1.0-release-0.3 cata
<skill-dir>/scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 dev kubeos
<skill-dir>/scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 dev-global-v100
<skill-dir>/scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 dev-global-compute microos
<skill-dir>/scripts/sync-bundle-envs build-harbor.alauda.cn/foo/bar:v1 p100
```

Interpretation:

- `<artifact>` is passed to `violet create --artifact=<artifact>`.
- `[profile]` is optional. When present, it loads `~/.config/violet-sync/<profile>.env` after the default config. In the command `... cata`, `cata` means `~/.config/violet-sync/cata.env`.
- Default config is `~/.config/violet-sync/config.env`; profile config overrides it.
- This skill includes `assets/config.env.example` as a safe starting template. Copy it to `~/.config/violet-sync/config.env` or `~/.config/violet-sync/<profile>.env` and fill in real credentials outside the skill directory.

For `sync-bundle-envs`:

- `<env-or-alias>` may be `dev`, `default`, `dev-global-default`, `v100`, `dev-v100`, `dev-global-v100`, or a unique cluster name found under `envs/dev-*/clusters/<cluster>.env`.
- Compute-platform card aliases are supported: `p100` resolves to `dev-global-compute/compute-x86`; `t4`, `4090`, and `rtx4090` resolve to `dev-global-compute/microos`.
- If the target dev environment contains multiple clusters, the cluster must be specified explicitly. For example, use `dev kubeos`, not just `dev`.
- It sources `<dev-env>/env` for non-secret platform metadata and `<dev-env>/platform.env` for credentials, then sets `CLUSTERS=<cluster>` when a cluster is specified.
- It creates a temporary `XDG_CONFIG_HOME/violet-sync/<profile>.env` and delegates to `scripts/sync-bundle`; it does not create persistent profile files.

## Env Target Resolution

For natural language requests, map them before running:

| User target | Command target | Result |
|---|---|---|
| `dev kubeos` / `开发 kubeos` | `sync-bundle-envs <artifact> dev kubeos` | platform `dev-global-default`, `CLUSTERS=kubeos` |
| `dev microos` | `sync-bundle-envs <artifact> dev microos` | platform `dev-global-default`, `CLUSTERS=microos` |
| `dev g1-c1-x86` | `sync-bundle-envs <artifact> dev g1-c1-x86` | platform `dev-global-default`, `CLUSTERS=g1-c1-x86` |
| `v100` / `dev-global-v100` | `sync-bundle-envs <artifact> dev-global-v100` | platform `dev-global-v100`, `CLUSTERS=global` |
| `dev-global-compute microos` | `sync-bundle-envs <artifact> dev-global-compute microos` | compute platform, `CLUSTERS=microos` |
| `dev-global-compute compute-x86` / `p100` | `sync-bundle-envs <artifact> p100` | compute platform, `CLUSTERS=compute-x86` |
| `t4` / `4090` / `rtx4090` | `sync-bundle-envs <artifact> t4` | compute platform, `CLUSTERS=microos` |

If the user only says "dev" and does not name a cluster, do not push to all default clusters automatically. Ask for the cluster unless the dev environment has exactly one cluster.

## Config Contract

Before running, verify the profile exists when a profile was provided:

```bash
ls -l ~/.config/violet-sync/config.env ~/.config/violet-sync/<profile>.env
```

Inspect config only with redaction:

```bash
sed -n '1,220p' ~/.config/violet-sync/<profile>.env | sed -E 's/(PASSWORD|TOKEN|SECRET|KEY|USER|USERNAME|PASS)([^=]*)=.*/\1\2=<redacted>/I'
```

Important variables:

- `PLATFORM_TOKEN`: preferred when the target ACP provides a service-account token; passed to `violet push --platform-token`.
- `PLATFORM_USERNAME`, `PLATFORM_PASSWORD`: username/password alternative when `PLATFORM_TOKEN` is unset.
- `PLATFORM_ADDRESS`: optional; if unset, wrapper discovers it with `kubectl get productbases base -o jsonpath='{.spec.platformURL}'`, then optionally `kubectl get acpstdacps.env.idp.alauda.io -n "$ACP_NAMESPACE" "$ACP_NAME"`.
- `ACP_NAME`, `ACP_NAMESPACE`: optional discovery fallback; namespace defaults to `idp`.
- `CLUSTERS`: destination clusters, default `global`.
- `SKIP_PACKAGE_IMAGES`: default `true`; adds `--skip-package-images`.
- `PACKAGE_PLATFORMS`: default `dual`; expands to `linux/amd64` and `linux/arm64`. Otherwise it is a comma-separated platform list.
- `REGISTRY_REWRITE_FROM`, `REGISTRY_REWRITE_TO`: if both are set and the artifact starts with `REGISTRY_REWRITE_FROM`, the wrapper rewrites the artifact prefix before packaging.
- `VIOLET_VERSION`, `VIOLET_BASE_URL`, `VIOLET_BIN`: control violet download/cache. Default cache path is `~/.cache/violet-sync/violet`.
- `VIOLET_DEBUG=true` or `DEBUG=true`: pass `--debug` to violet.

## Execution Workflow

1. Confirm `sync-bundle --help` works and `command -v sync-bundle` resolves to the expected wrapper. If not, use `<skill-dir>/scripts/sync-bundle --help`.
2. If the request names an envs target rather than an explicit profile, use `<skill-dir>/scripts/sync-bundle-envs --help` and resolve the target through `envs/dev-*`.
3. Confirm the provided profile file exists when a profile name is used. This is not required for `sync-bundle-envs` because it creates a temporary profile.
4. Redact-check config if credentials or target platform may be unclear.
5. Run the exact requested sync command from a normal shell:

```bash
sync-bundle '<artifact>' '<profile>'
```

   If the installed command is unavailable, use `<skill-dir>/scripts/sync-bundle` and preserve the same arguments.

   For envs targets:

```bash
<skill-dir>/scripts/sync-bundle-envs '<artifact>' dev kubeos
```

6. Watch the wrapper logs. They should include:
   - `profile=...`
   - `artifact=...`
   - optional `rewritten-artifact=...`
   - `platform-address=...`
   - `clusters=...`
   - `package-platforms=...`
   - `skip-package-images=...`
   - final `result=success`
7. Report success or failure with the non-secret command inputs and the last meaningful error.

## What The Wrapper Runs

The wrapper performs:

```bash
violet create <tmp-output-dir> \
  --default-catalog-source=platform \
  --artifact=<possibly-rewritten-artifact> \
  [--skip-package-images] \
  [--platforms=...]

violet package <tmp-output-dir> --no-auth --output=<tmp-output.tgz>

violet push --force \
  --clusters=<clusters> \
  --platform-address=<platform-address> \
  [--platform-token=<token> | --platform-username=<username> --platform-password=<password>] \
  <tmp-output.tgz>
```

Do not manually reconstruct these commands unless debugging the wrapper itself. Prefer the wrapper because it handles config loading, platform discovery, violet download, registry rewrite, packaging, and push flags consistently.

## Failure Triage

- `PLATFORM_TOKEN or PLATFORM_USERNAME and PLATFORM_PASSWORD are required`: config or profile did not load either supported credential form.
- `target 'dev' resolves to multiple clusters`: the user gave an env target without a cluster; ask for `kubeos`, `microos`, `g1-c1-x86`, etc.
- `cluster '<name>' is not recorded`: envs has no `<dev-env>/clusters/<name>.env`; inspect `/Volumes/macOS-2/Users/yuan/Dev/tools/envs/dev-*`.
- `failed to discover PLATFORM_ADDRESS`: set `PLATFORM_ADDRESS` in config or ensure `kubectl` context can read `productbases` / ACP resources.
- `required command not found: kubectl`: needed only when `PLATFORM_ADDRESS` is absent.
- `required command not found: curl`: needed when `violet` must be downloaded.
- `unsupported OS` or `unsupported arch`: wrapper only supports Darwin/Linux and amd64/arm64.
- `violet create/package/push` errors: preserve the exact violet error, artifact, profile, platform address, and clusters in the report.

## Safety

- Never print `PLATFORM_PASSWORD` or credential-bearing config lines.
- Treat `violet push --force` as a real catalog update.
- If the user supplies an explicit sync command, execute that command rather than changing the artifact tag or profile.
- If the command uses a bundle image from `build-harbor.alauda.cn` and the profile has registry rewrite configured, expect `rewritten-artifact=...` in logs; this is normal.
