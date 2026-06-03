# bundle-iterate

代码 → 流水线 → 打包 → 上架目标 ACP 集群 → 安装验证,失败后迭代修复。InferNex-Bridge 端到端开发闭环的工作流沉淀。

## 适用场景

某个 Alauda OLM Bundle 项目(InferNex-Bridge / KServe / 其他)在 devpod 上做代码迭代,目标是装到 air-gap 的 ACP 集群(kubeos2)验证。每次代码改完,这一套流程跑一遍知道改对没。

## 网络拓扑现实

devpod、build-harbor、npuserver、kubeos2 三网隔离:

| 链路 | 状态 |
|---|---|
| devpod ↔ build-harbor.alauda.cn | ✅ 有认证可达 |
| devpod ↔ gitlab-ce.alauda.cn | ✅ SSH key 已配 |
| devpod ↔ npuserver (`119.8.241.33:35710`) | ✅ key 免密 |
| devpod ↔ kubeos2 节点/ACP | ❌ |
| npuserver ↔ build-harbor.alauda.cn | ❌(`192.168.156.101:443` 超时) |
| npuserver ↔ kubeos2 ACP `https://127.0.0.1` | ✅(本机) |

→ 镜像打包必须在 devpod 上做,推到 catalog 必须在 npuserver 上做,中间用 scp 搬 tgz。

## 一次迭代的 6 个阶段

1. `git push` 当前分支到 gitlab-ce
2. 触发 Katanomi BuildRun(走 `katanomi-buildrun` skill 的 `create_buildrun.sh` / `wait_buildrun.sh`),拿到镜像 tag
3. devpod 上 `violet create --artifact=<bundle-image>:<tag>` + `violet package` → 79M 左右的 tgz(用 `envs/env.harbor` 鉴权拉 build-harbor 镜像)
4. `scp` tgz 到 npuserver
5. npuserver 上 `violet push --clusters=<target> --platform-address=https://127.0.0.1 ...`
6. 删 Subscription + CSV → 重建 Subscription → 等 `CURRENT=<new-csv>` + CSV `Succeeded` + Pod `1/1 Running`,看日志确认无 `Reconciler error`

详细命令模板见 [SKILL.md](SKILL.md)。

## 工作流来源

2026-05-28 InferNex-Bridge OLM Bundle 落地任务,期间从 v1 迭代到 v6,修了 3 个真实 bug(values.yaml 位置、`required` 依赖解析、cert path)+ 加了 1 个功能(模板自举),每次都是这套闭环验证。详见 [[project-infernex-bridge-olm]] 记忆条目和分支 `aml/openfuyao/infernex@feat/build-pipeline`。

## 关键依赖

- 兄弟 skills:
  - [trivial-things / katanomi-buildrun](../../skills/trivial-things/skills/katanomi-buildrun/) — 触发+等流水线
  - [fy-skills / sync-bundle](../sync-bundle/) — violet 同步(单机版,air-gap 场景不直接用,但思路相同)
  - [fy-skills / cluster-image-import](../cluster-image-import/) — 经跳板机推镜像(另一条 air-gap 路径,这个 skill 走的是 OLM catalog 而非裸镜像)
  - [alauda-ai-builders / ai-platform-passwordless-ssh](../../../skills/alauda-ai-builders/ai-platform/skills/ai-platform-passwordless-ssh/) — devpod 到 npuserver 的免密 SSH 标准做法
- 环境信息:[envs/README.md](../../../envs/README.md)
- violet 工具:`http://package-minio.alauda.cn:9199/packages/violet/latest/violet_linux_amd64`(devpod 用),npuserver 已预装 `/usr/local/bin/violet`

## 不解决什么

- 没有口令登陆 KubeOS 节点(用 `kos2` 直接打 API 已经够,不需要节点 SSH)
- 不绕过 build-harbor 认证
- 不修上游 Bridge 代码 bug(那是单独 PR)
- 不做 OLM 内部状态恢复魔法(失败靠"删 sub + CSV 重建"暴力路径)
