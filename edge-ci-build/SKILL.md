---
name: edge-ci-build
description: Legacy lightweight helper for Alauda Edge (Katanomi) CI BuildRun status, dev/default-tag rebuilds, and image result lookup. For branch-aware release or RC builds, prefer hyperflux-pipeline-ops because it uses the console Run API shape with refs/heads/<branch> and spec.params. Use edge-ci-build only when the user wants a simple dev rebuild/status/image check or when hyperflux-pipeline-ops is unavailable.
---

# Edge CI Build (轻量 BuildRun 辅助)

Alauda 的插件镜像/bundle 构建跑在 **Katanomi**(edge.alauda.cn,cluster `business-build`,API group `builds.katanomi.dev/v1alpha1`)。每个仓库对应一个 **`Build`** 资源;真正的一次构建是一个 **`BuildRun`**。

**当前推荐**:

- release / RC 分支构建:用 `hyperflux-pipeline-ops` 的 `trigger_buildrun.py`,它按 console Run 弹窗形态提交 `spec.git.revision=refs/heads/<branch>` 和 `spec.params`,已验证可以构建出预期 RC 版本。
- 简单 dev/default tag rebuild、status、wait、image 查询:仍可用本 skill 的 `scripts/edge-ci.sh`。
- Edge 已经产出 plugin 包后要上架/升级目标 ACP:用 `edge-plugin-package-rollout`。

**为什么仍保留这个 skill**:`Build` 的 `spec.triggers.gitTrigger` 通常只对 **master 分支**(`filter.branch.regex: ^master$`)或 **PR/MR**(`pullRequest.enable`)自动起 BuildRun。push 一个 `feat/*` 分支经常不会自动构建,本 skill 可作为低依赖 curl+jq fallback。

## 前置

- 凭据:`envs/env.edge`(`TOKEN`,Bearer);见 `agent-envs/registry.yaml` → `services.edge`(platform `https://edge.alauda.cn`,namespace `aml-dev`,cluster `business-build`)。
- **分支必须已 push 到 origin**(`git.revision` 在远端可解析才行)。本 skill 不负责 push;先 `git push -u origin <branch>`。
- 工具:`curl` + `jq`。

## 关键 API

```
BASE=https://edge.alauda.cn/kubernetes/business-build/apis/builds.katanomi.dev/v1alpha1/namespaces/aml-dev
GET  $BASE/builds                 # 列 Build(找仓库对应的 Build 名)
GET  $BASE/buildruns?limit=500    # 列历史 BuildRun(看命名/找模板)
POST $BASE/buildruns              # 建新 BuildRun(触发构建)
GET  $BASE/buildruns/<name>       # 查状态(.status.phase / conditions[Succeeded])
```

BuildRun 的最小 body(`generateName` 让平台分配名字):

```json
{
  "apiVersion": "builds.katanomi.dev/v1alpha1",
  "kind": "BuildRun",
  "metadata": {
    "generateName": "<BUILD>-",
    "namespace": "aml-dev",
    "labels": { "builds.katanomi.dev/build": "<BUILD>" }
  },
  "spec": {
    "buildRef": { "name": "<BUILD>", "namespace": "aml-dev" },
    "git": { "revision": "<BRANCH_OR_TAG_OR_COMMIT>" },
    "serviceAccount": { "name": "" },
    "status": ""
  }
}
```

## 流程

1. **确认分支已 push**:`git -C <repo> push -u origin <branch>`。
2. **找 Build 名**:用户给(如 `fuyao-infernex-bridge`),或 `scripts/edge-ci.sh builds | grep <repo>`。
   - 找不到时退而搜历史 BuildRun:`buildruns?limit=500` grep 仓库关键字,其 `metadata.labels["builds.katanomi.dev/build"]` 即 Build 名。
3. **触发**:`scripts/edge-ci.sh trigger <BUILD> <revision>` → 打印新 BuildRun 名(如 `fuyao-infernex-bridge-zgrrd`)。
4. **观察**:`scripts/edge-ci.sh wait <buildrun>` 轮询到终态;或 `status <buildrun>` 看一次。用户也能在 edge pipeline UI 看到。
5. **取产物**:成功后 `scripts/edge-ci.sh image <buildrun>` 提取构建出的镜像 tag(feat 分支 tag 形如 `v0.0.0-feat.N.g<commit>...`;后续可喂给 bundle-iterate 装到集群,或重扫 CVE 坐实)。

## ⚠️ 版本号/tag 模式

`scripts/edge-ci.sh trigger` 是最小裸 POST,只设置 `spec.git.revision:<字符串>`,没有 console Run 所带的完整分支/参数语义。它适合 dev/default tag 验证,不适合作为 release/RC 构建入口。

要 **release/语义化 rc tag**(如 `v26.6.0-rc.2-alauda.<N>`,由 release 分支名派生 + 自增构建号),使用 `hyperflux-pipeline-ops/scripts/trigger_buildrun.py`:

```bash
python3 /Volumes/macOS-2/Users/yuan/Dev/tools/alauda-ai-builders/hyperflux/skills/hyperflux-pipeline-ops/scripts/trigger_buildrun.py \
  --build-name <build> \
  --cluster business-build \
  --namespace aml-dev \
  --branch release-26.6.0-alauda \
  --param <name>=<value>
```

Then use this skill's `status`, `wait`, or `image` commands only as lightweight follow-up if needed.

## 纪律 / 坑

- **不要在 master/release 分支直接开发**触发构建;feature 走 `feat/<scope>`(见个人记忆 feedback-branch-workflow)。
- **触发是外发写操作**:仅当用户明确要"触发 CI/构建"时执行(本 skill 的存在即此授权场景);其余别擅自 POST BuildRun。
- **token 不回显**:`source envs/env.edge` 后用 `$TOKEN`,不要打印到日志/对话。
- gitTrigger 只认 master/PR → feat 分支必须手动 BuildRun;不要误以为 push 了就会自动构建(查不到 BuildRun 时先想到这点)。
- 与 `edge-plugin-package-rollout` 的关系:本 skill 到 BuildRun/image/tag 为止;Edge 产出 plugin 包并要进入 ACP/OLM 验证时,交给 `edge-plugin-package-rollout`。
- 与 `bundle-iterate` 的关系:bundle-iterate 是旧的 code→pipeline→package→air-gap install 闭环,强绑定 kubeos2/npuserver;不要用它处理普通 dev kubeos 的 Edge plugin 包升级。

## 可选脚本

`scripts/edge-ci.sh <builds|trigger|status|wait|image> [args]` —— curl+jq 封装,读 `envs/env.edge`。最终结论仍以 edge pipeline UI / BuildRun status 为准。
