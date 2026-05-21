---
name: cluster-image-import
description: 把外网镜像导入到内网/隔离集群的镜像仓库。当用户给出一个镜像地址(如 build-harbor.alauda.cn/mlops/vllm-server:tag 或 mlops/vllm-server:tag)并希望"导入集群""推送到集群 registry""同步镜像"时使用。流程是经跳板机 SSH 到一台网络开放的执行机(146)，由它从内网镜像源 pull 后 re-tag 并 push 到目标 registry，支持 amd64 / arm64 / 异构(arm64,amd64)。涉及关键词：跳板机、jumper、build-harbor.alauda.cn、registry.alauda.cn、目标 registry、docker push、pushimages.sh、离线/隔离集群导入镜像。
---

# Cluster Image Import（镜像导入集群）

把一个镜像从外网/构建仓库导入到内网或隔离集群的目标镜像仓库。

## 工作原理

执行机 `146`（默认 `192.168.152.146`）的网络被专门开放，能同时访问内网镜像源和集群目标仓库，但**只能经跳板机访问**。本 skill 的链路：

```
本地 / devpod
   │  ssh -i <跳板机私钥> -p 52022 fangyuan@192.168.144.101   (第一跳，密钥认证)
   ▼
跳板机 (jumper)
   │  ssh root@192.168.152.146                                 (第二跳，146 免密)
   ▼
执行机 146
   └─ /root/push-image.sh <目标registry> <镜像> <平台>
        └─ /root/pushimages.sh：从内网 mirror pull → tag → push 到目标 registry → 清理
```

这是嵌套 SSH（先登跳板机、再登 146），不是 ProxyJump —— 因为 146 对跳板机免密，第二跳无需带密钥。

## 用法

```
scripts/import_image.sh <目标registry> <镜像> [平台]
```

- `<目标registry>`：集群的镜像仓库地址，例 `192.168.136.182:11443`
- `<镜像>`：镜像路径，带不带 `build-harbor.alauda.cn/` 前缀都可，例 `mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130`
- `[平台]`：`amd64`(默认) / `arm64` / `arm64,amd64`(异构，自动 `docker manifest`)

示例（等价于执行机上原来的 `./x86-amd64.sh 192.168.136.182:11443 mlops/vllm-server:...`）：

```
# amd64
scripts/import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130

# arm64
scripts/import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130 arm64

# 异构（同时 amd64 + arm64，生成多架构 manifest）
scripts/import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130 arm64,amd64
```

## 配置（环境变量，均有默认值）

| 变量 | 默认 | 说明 |
|------|------|------|
| `JUMPER_HOST` | `192.168.144.101` | 跳板机地址 |
| `JUMPER_PORT` | `52022` | 跳板机端口 |
| `JUMPER_USER` | `fangyuan` | 跳板机用户 |
| `JUMPER_KEY` | `~/.ssh/fy-qq-jumper.pem` | 跳板机私钥（本地 Mac / devpod 都要有这把） |
| `HOST_146` | `192.168.152.146` | 执行机地址 |
| `HOST_146_USER` | `root` | 执行机用户 |
| `MIRROR` | `registry.alauda.cn:60070` | 内网镜像源（拉取来源） |

**两种环境都能用**：skill 不依赖本地 `~/.ssh/config` 里的 `Host jumper` 别名，连接参数全部显式传入。换环境只需保证那把私钥在 `JUMPER_KEY` 指向的路径；devpod 里没有就先放进去，或 `JUMPER_KEY=/path/to/key` 覆盖。

## 执行步骤（skill 调用流程）

1. 向用户确认/收集 3 个参数：目标 registry、镜像、平台（默认 amd64）。
2. 运行 `scripts/import_image.sh`，它会：
   - **[1/2]** 把 `scripts/push-image.sh` 部署到 `146:/root/push-image.sh`（统一包装脚本，替代旧的 `x86-amd64.sh`）。
   - **[2/2]** 经跳板机在 146 上执行该脚本，把镜像 pull/tag/push 到目标 registry。
3. push 成功后执行机会清理本地临时镜像（`pushimages.sh` 末尾的删除逻辑，非交互下默认执行）。

## 错误处理

- 找不到 `JUMPER_KEY` 私钥：退出码非 0，提示把私钥放到指定路径或用 `JUMPER_KEY=` 覆盖。
- 平台参数非法（非 amd64/arm64/arm64,amd64）：退出码非 0。
- SSH / docker push 失败：原样透传执行机的错误输出，便于定位是网络、认证还是仓库问题。
