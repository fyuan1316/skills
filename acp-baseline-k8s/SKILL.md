---
name: acp-baseline-k8s
description: Query the ACP platform baseline Confluence tree for supported Kubernetes versions by ACP major.minor or major.minor.patch version. Use when the user asks which K8s/Kubernetes version ACP 4.2, 4.3, 4.4, or a specific ACP patch baseline supports, or needs release baseline evidence from the internal ACP baseline document.
---

# ACP Baseline Kubernetes Query

Use this skill to answer questions such as:

- `ACP 4.4 支持哪个 Kubernetes 版本?`
- `查一下 4.3 最新 patch 的 k8s 版本`
- `ACP 4.2.5 的 global 和业务集群 Kubernetes 基线是多少?`

The source of truth is the Confluence page tree rooted at:

`https://confluence.alauda.cn/pages/releaseview.action?pageId=75075758`

The tree is organized as:

1. Root page: `ACP 产品各版本基线`
2. Major/minor child page: titles like `v4.4.x 版本基线`
3. Patch child page: titles like `v4.4.0 版本基线`

Only read the concrete patch baseline pages, for example `v4.4.0 版本基线`.
Do not inspect sibling pages such as 功能完整性需求, 操作系统按需交付能力对照表,
性能需求, 非功能基线, 安全基线, or 通信矩阵 for this query.

## Quick Start

Run the bundled script. It reads Confluence credentials from environment variables or from `/Volumes/macOS-2/Users/yuan/Dev/tools/envs/env.confluence`.

```bash
python3 /Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/fy-skills/acp-baseline-k8s/scripts/query_acp_k8s.py 4.4
```

For a specific patch baseline:

```bash
python3 /Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/fy-skills/acp-baseline-k8s/scripts/query_acp_k8s.py 4.2 --patch 4.2.5
```

For machine-readable output:

```bash
python3 /Volumes/macOS-2/Users/yuan/Dev/alauda/ai-infra/fy-skills/acp-baseline-k8s/scripts/query_acp_k8s.py 4.3 --json
```

## Interpretation Rules

- With only `major.minor`, use the newest concrete patch baseline page under that series by semantic patch number, for example `4.3` -> `v4.3.2 版本基线` if `4.3.2` is the newest child baseline page.
- Prefer parsed Confluence tables over free text.
- Treat a table headed `Kubernetes 版本 | 运行时组件 | 备注` as the platform/global Kubernetes baseline.
- Treat a table headed `Kubernetes 版本 | istio版本 | 运行时组件版本 | 备注` as the business/attached cluster Kubernetes baseline.
- Treat cloud/OCP support tables as additional support matrices, not the core platform baseline.
- If the script reports several candidates, answer with the categorized values and cite the source page title and URL.
- The Confluence baseline pages are manually maintained and may be copied before the release is complete. If the script reports `release_audit.status = suspect_unreleased`, still give the Kubernetes versions it found, but also say `未发版 / 疑似复制残留，需人工确认` and include the exact Confluence URL so the user can inspect the page.
- Treat ACP product-version mismatches such as a `v4.4.0 版本基线` page whose content still mentions `ACP 4.3`, `v4.3.x`, or `v4.3.0` as an unreleased/suspicious signal. Do not silently trust the K8s table in this case.
- Also treat copied baseline headings or artifact links as suspicious, for example a `v4.4.0 版本基线` page whose body still says `v4.3.x 版本基线` or whose Kubernetes table links to `/blob/v4.3.0/.../artifacts.yaml`.

## Credentials

Use the shared env file convention:

```bash
set -a
source /Volumes/macOS-2/Users/yuan/Dev/tools/envs/env.confluence
set +a
```

Never print secrets. If checking the env file, list variable names only.

## Script

`scripts/query_acp_k8s.py` performs these steps:

1. Resolve the `v<major>.<minor>.x 版本基线` child page under the root.
2. Resolve the requested patch page, or the newest patch page under that series.
3. Fetch Confluence storage HTML with `body.storage`.
4. Parse tables using only the Python standard library.
5. Extract Kubernetes version rows and classify them as `platform`, `attached`, or `matrix`.
6. Audit whether the page title ACP version matches ACP version clues in the content and emit a `未发版` warning when they diverge.
