# agent-envs/

**Agent 面向的环境索引。** 事实的单一入口是 [`registry.yaml`](registry.yaml) —— Claude / Codex 解析任何环境前先读它。

## 为什么和 `envs/` 分开

| 目录 | 角色 | git | 改动纪律 |
|---|---|---|---|
| `envs/` | **密文 fill** —— skill 脚本硬编码路径的原始凭据文件 | **全部 gitignore** | 不重构、不改名(会断 bundle-iterate / hami-dev 等) |
| `agent-envs/`(本目录) | **索引 + 文档** —— 给 agent 看的访问配方 | **全部 git-tracked** | 在这里新增/整理 |

这条**目录边界 = 密/非密边界**:`envs/` 整体忽略(`.gitignore` 现状不动),`agent-envs/` 整体进 git 同步给
Mac Codex。不需要在单个目录里做 `!` 放行那种易错的 gitignore 规则。

> **铁律**:`agent-envs/` 里**绝不放密文**。registry 只写 `creds:` 引用路径(指向 `envs/...`),不复制 token /
> kubeconfig 正文。读到的任何 token/密码**不回显**到对话、日志、进程参数。

## 三个面

环境按访问方式分三段,与 `registry.yaml` 对应:

- `services:` 代码/制品面 —— token 鉴权的 API(git 平台、镜像仓、Edge 构建)
- `clusters:` 控制面 —— ACP 集群,kubeconfig + proxy/direct 双 context
- `hosts:` 数据面/跳板 —— SSH 裸机(NPU RoCE、P100 CUDA、跳板/网关)

## 如何新增一个环境

1. 凭据文件照旧放进 **`envs/`**(`env.<name>` / `kubeconfig/*.yaml` / host 套件)。
2. 在 **`registry.yaml`** 对应段加一条:`what` / 如何 reach / `creds:`(envs/ 路径)/ `used_by`。
   集群写两个 context;走跳板的写 `via_host` + `access`。
3. repo 有默认环境就在 `projects:` 加 `match:`(cwd/git_remote)→ 让 agent 自动选靶。

## 同步到 Mac / Codex

`git add agent-envs/` 即可 —— 同步过去的是结构与访问配方,不是密文。Codex 侧入口规则只需一句:
**"解析环境前先读 `agent-envs/registry.yaml`"**(加到 `~/.codex/AGENTS.md`);Claude 侧同理。
每台机器各自在自己的 `envs/` 里 fill 凭据(Mac 另有高权限 kubectl / `violet push` 口头凭据)。

## 与 `envs/` README 的分工

- 本文件 + `registry.yaml`:**有哪些环境、怎么访问**(agent 与跨机同步)。
- [`envs/README.md`](../envs/README.md):**字段约定、token 从哪拿、新 devpod bootstrap 顺序**(本机运维细节)。
