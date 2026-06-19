# AGENTS.md — 跨 agent / 跨机入口(Claude Code & Codex 共用)

本仓 = **可移植 agent 大脑**:skill playbook + 环境索引。配合每机各自的、gitignore 的 `envs/` 密文目录使用。
Claude Code 自带 Skill 工具发现 `*/SKILL.md`;Codex 没有该机制 —— 把每个 `SKILL.md` 当**可执行 playbook 正文**读并照做即可。

## 铁律(密/非密边界)

- **索引 git-tracked,密文不进 git。** 任何 token / kubeconfig 正文只存在于各机本地的 `envs/`(整目录 gitignore)。
- registry 只写 `creds:` 引用路径,**绝不**复制密文正文;读到的密码/token **不回显**到对话、日志、进程参数。

## 解析任何环境:先读 registry

resolve 任何主机/集群/服务前,先读环境索引:`./agent-envs/registry.yaml`(已并入本仓)。
可选:设环境变量 `FY_REGISTRY` 覆盖指向别处的 registry。

registry 三个面:`services:`(token API)/ `clusters:`(kubeconfig 双 context)/ `hosts:`(SSH 裸机+跳板)。
每条给出:是什么、怎么 reach、`creds:`(envs/ 路径)、`used_by`。

## Skill 目录(含"在哪跑")

| skill | 用途 | 执行位置 |
|---|---|---|
| `node-ssh-bootstrap` | 给免密登不进的 KubeOS 节点装免密 | **Mac 可跑**(经 npuserver 公网) |
| `edge-ci-build` | 手动触发 Alauda Edge CI 给任意 git 分支构建 | Mac 可跑(需公司 VPN 到 edge.alauda.cn) |
| `bundle-iterate` | OLM bundle code→cluster 闭环 | **devpod 主**(violet create/package 靠 devpod 大盘);Mac 仅能做 npuserver→kubeos2 的 install/verify 半程 |
| `hami-dev` | HAMi 技术栈 build/test | **devpod**(Go 工具链在大临时盘)+ P100(经 jumper,VPN) |
| `hami-fix` | HAMi 自动化修复编排 | devpod |
| `cluster-image-import` / `sync-bundle` | 镜像导入 / bundle 同步 | 看目标集群可达性(多为 VPN) |

> Codex 触发法:可在 `~/.codex/prompts/<name>.md` 放薄壳("读 `<clone>/<name>/SKILL.md` 并执行"),
> 即可用 `/<name>` 调起;或直接让 Codex 按 SKILL.md 正文走。

## Mac / Codex bootstrap

1. **clone 大脑**:`git clone git@github.com:fyuan1316/skills.git` —— 一次 clone 即含 registry(`agent-envs/`)+ 全部 skill + 本 AGENTS.md。
2. **Codex 入口**:在 `~/.codex/AGENTS.md` 加一句 ——
   `解析任何环境前先读 <skills-clone>/agent-envs/registry.yaml(或 $FY_REGISTRY);密文规则见 <skills-clone>/AGENTS.md。`
3. **本机填密文**:在 `<skills-clone>/../envs/`(或自定,与 devpod 同布局最省事)按下表创建文件。Mac 另有 devpod 没有的高权限 kubectl / `violet push` 口头凭据。
4. **可达性自检**:`192.168.x` 目标要先挂公司 VPN;公网链路(npuserver/kubeos2、github/gitcode)无需 VPN。

### envs/ 填写清单(各机各填,内容见主仓 envs/README.md)

| 文件 | 内容 | Mac 直连? |
|---|---|---|
| `env.github` | GITHUB_TOKEN | ✅ |
| `env.gitcode` | TOKEN | ✅ |
| `env.gitlab` | GITLAB_TOKEN(yuanfang Developer) | VPN |
| `env.jira` | USER+PASSWORD(basic) | VPN |
| `env.harbor` | USER+PSSSWORD(sic,3×S,勿改名) | VPN |
| `env.edge` | TOKEN(Bearer) | VPN |
| `env.jumper` | ssh_config:Host jumper→192.168.144.101:52022 | VPN |
| `npuserver/`(env.npuserver/env.acp/kos2/kubeos2-kubeconfig.yaml/setup.sh) | npuserver 公网网关 + kubeos2 | ✅(装 key 后 `ssh npuserver kos2 ...`) |
| `kubeconfig/*.yaml`、`192.168.142.163`、`192.168.128.78/` | 内网集群 kubeconfig + 平台凭据 | VPN |
| `env.kubeos` | kubeos 节点 root 口令 | VPN(经 jumper) |

### Mac 直连可达性一览

| 目标 | 入口 | Mac 直连 |
|---|---|---|
| github / gitcode | 公网 | ✅ |
| npuserver | 119.8.241.33:35710 | ✅(需 key) |
| kubeos2(e2e 主靶) | 经 npuserver `kos2` | ✅ |
| gitlab/jira/harbor/edge | *.alauda.cn 公司网 | 仅 VPN |
| jumper 及其后(p100、kubeos 节点) | 192.168.144.101 内网 | 仅 VPN |
| g1-c1-x86 / g1-c2-arm / business-1 / kubeos 平台 | 192.168.x ALB/:6443 | 仅 VPN |
