---
name: edge-ci-build
description: Trigger an Alauda Edge (Katanomi) CI build for a specific git branch/tag/commit and watch it to completion. Use when the user asks to "触发 CI 构建", "trigger the CI build for this branch", "build my feat branch on edge", "kick a buildrun", "rebuild the image after my fix", or otherwise wants to run the platform build pipeline for a revision that the git webhook does NOT auto-build (feat/* branches — the Katanomi gitTrigger usually only auto-fires on master or on a PR). Produces a BuildRun on edge.alauda.cn and harvests the resulting image tag. This is the standalone "trigger build" step that bundle-iterate performs inline; use this when you only need the build, not the full install loop.
---

# Edge CI Build (手动触发 Katanomi BuildRun)

Alauda 的插件镜像/bundle 构建跑在 **Katanomi**(edge.alauda.cn,cluster `business-build`,API group `builds.katanomi.dev/v1alpha1`)。每个仓库对应一个 **`Build`** 资源;真正的一次构建是一个 **`BuildRun`**。

**为什么需要手动触发**:`Build` 的 `spec.triggers.gitTrigger` 通常只对 **master 分支**(`filter.branch.regex: ^master$`)或 **PR/MR**(`pullRequest.enable`)自动起 BuildRun。**push 一个 `feat/*` 分支不会自动构建** —— 必须手动 POST 一个 `BuildRun` 指定 `git.revision`。这就是本 skill 做的事(实证:`fuyao-infernex-bridge` 的 trigger regex = `^master$`,feat 分支历史上都是手动建 BuildRun)。

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

## ⚠️ 版本号/tag 模式(关键,实证 2026-06-12)

**API 裸 POST `spec.git.revision: <字符串>` → katanomi 一律解析为 `revision.type=Commit` → `versionPhase=default` → tag = `v0.0.0-default.<N>.g<sha>`(dev tag),与字符串是不是分支名无关。** BuildRun 的 git 只接受 `revision`(无 `branch` 字段;Build 的 git 只有 url/secretRef/options),所以本脚本的 `trigger` **只能产 dev tag**。

要 **release/语义化 rc tag**(如 `v26.6.0-rc.2-alauda.<N>`,由 release 分支名派生 + 自增构建号):**必须在 branch 上下文跑** —— ref 被解析为 `type=Branch` 版本策略才映射分支→semver。两条路:
1. **edge console 流水线「运行」时选择分支**(`release-26.6.0-rc.2-alauda`)—— 推荐,console 会带上分支上下文/`triggeredBy`。
2. gitTrigger 分支事件(但本仓 gitTrigger regex=`^master$`,push release 不自动触发)。

**对应做法**:dev 验证(如改完快速重构重扫 CVE)用本脚本 `trigger` 即可;**正式 rc 发版镜像必须去 console 按分支跑**(脚本的 `status/wait/image` 仍可用于跟踪那条 console BuildRun)。实证:`{revision:"release-26.6.0-rc.2-alauda"}` 的裸 POST 产出 `v0.0.0-default.2.g36cbbb1f`(错),而 console 分支跑产出 `v26.6.0-rc.2-alauda.N`(对)。

## 纪律 / 坑

- **不要在 master/release 分支直接开发**触发构建;feature 走 `feat/<scope>`(见个人记忆 feedback-branch-workflow)。
- **触发是外发写操作**:仅当用户明确要"触发 CI/构建"时执行(本 skill 的存在即此授权场景);其余别擅自 POST BuildRun。
- **token 不回显**:`source envs/env.edge` 后用 `$TOKEN`,不要打印到日志/对话。
- gitTrigger 只认 master/PR → feat 分支必须手动 BuildRun;不要误以为 push 了就会自动构建(查不到 BuildRun 时先想到这点)。
- 与 [bundle-iterate] 的关系:bundle-iterate 内部就做了"commit→push→buildrun→取 tag→装集群→验证"整条;本 skill 是其中**只触发构建+拿 tag**那一段的独立版,适合"只想重构一个镜像"(如修完 CVE 重构后重扫)。
- 想走"自动触发"也可以**开 MR**(gitTrigger 的 pullRequest.enable=true);但手动 BuildRun 更直接、可指定任意 revision。

## 可选脚本

`scripts/edge-ci.sh <builds|trigger|status|wait|image> [args]` —— curl+jq 封装,读 `envs/env.edge`。最终结论仍以 edge pipeline UI / BuildRun status 为准。
