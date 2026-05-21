#!/bin/bash
# push-image.sh —— 统一镜像导入包装脚本（替代执行机上的 x86-amd64.sh / arm 变体）
#
# 部署位置: 146:/root/push-image.sh （由 import_image.sh 自动部署）
# 用法:     push-image.sh <target-registry> <image> [platform]
#   <target-registry>  目标镜像仓库, 例 192.168.136.182:11443
#   <image>            镜像路径, 带不带源仓库前缀都可, 例 mlops/vllm-server:v0.20.2
#   [platform]         amd64(默认) | arm64 | arm64,amd64(异构)
# 环境变量:
#   MIRROR             内网镜像源 (默认 registry.alauda.cn:60070)
#
# 等价于旧脚本: registry=registry.alauda.cn:60070
#               /root/pushimages.sh --registry $1 --images $registry/$2 --platform amd64
# 区别: 平台不再写死, 由第 3 个参数指定。
set -uo pipefail

target_registry="${1:?需要目标镜像仓库地址, 例 192.168.136.182:11443}"
image="${2:?需要镜像路径, 例 mlops/vllm-server:v0.20.2}"
platform="${3:-amd64}"
mirror="${MIRROR:-registry.alauda.cn:60070}"

case "${platform}" in
  amd64|arm64|arm64,amd64) ;;
  *) echo "platform 只能是 amd64 / arm64 / arm64,amd64, 实际: ${platform}" >&2; exit 1 ;;
esac

# 去掉用户可能带上的源仓库前缀, 统一从内网 mirror 拉取
image="${image#build-harbor.alauda.cn/}"
image="${image#${mirror}/}"

echo "目标仓库 : ${target_registry}"
echo "拉取来源 : ${mirror}/${image}"
echo "平台     : ${platform}"
echo "---------------------------------------------"

exec /root/pushimages.sh \
  --registry "${target_registry}" \
  --images "${mirror}/${image}" \
  --platform "${platform}"
