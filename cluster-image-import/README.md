# cluster-image-import

把外网/构建仓库的镜像导入到内网或隔离集群的目标镜像仓库。

## 链路

```
本地 / devpod ──ssh(密钥)──> 跳板机 192.168.144.101:52022 ──ssh(免密)──> 执行机 146 ──> push 到目标 registry
```

执行机 `146` 网络专门开放，能访问内网镜像源（`registry.alauda.cn:60070`）和集群目标仓库，但只能经跳板机进入。

## 快速开始

1. 确保跳板机私钥在本机：默认 `~/.ssh/fy-qq-jumper.pem`（devpod 里没有就先放进去，或用 `JUMPER_KEY=` 覆盖）。
2. 运行：

```bash
scripts/import_image.sh <目标registry> <镜像> [平台]

# 例
scripts/import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130
scripts/import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130 arm64
scripts/import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130 arm64,amd64
```

## 文件

| 文件 | 作用 |
|------|------|
| `scripts/import_image.sh` | 本地驱动：嵌套 SSH，部署包装脚本并在 146 上执行。本地 Mac / devpod 通用。 |
| `scripts/push-image.sh` | 部署到 `146:/root/push-image.sh` 的统一包装脚本，替代旧的 `x86-amd64.sh`，平台作为参数。内部调用 `146:/root/pushimages.sh`。 |

## 与旧脚本的关系

旧用法在 146 上是两个写死平台的脚本（`x86-amd64.sh` 等），其核心是：

```bash
registry=registry.alauda.cn:60070
/root/pushimages.sh --registry $1 --images $registry/$2 --platform amd64
```

本 skill 把平台抽成第 3 个参数，统一成一个 `push-image.sh`，并自动经跳板机部署+执行，无需手动 SSH。`pushimages.sh` 本身保持不变（它早已支持 `--platform amd64/arm64/arm64,amd64`）。

## 配置变量

见 [SKILL.md](SKILL.md) 的「配置」表（`JUMPER_*`、`HOST_146*`、`MIRROR`）。
