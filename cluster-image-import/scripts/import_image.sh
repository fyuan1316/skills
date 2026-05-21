#!/usr/bin/env bash
# import_image.sh —— 本地驱动脚本：经跳板机把镜像导入到集群目标仓库。
# 在本地 Mac 或 devpod 均可运行；连接参数全部显式传入，不依赖 ~/.ssh/config。
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: import_image.sh <target-registry> <image> [platform]

  <target-registry>  目标镜像仓库地址, 例: 192.168.136.182:11443
  <image>            镜像路径(带不带 build-harbor.alauda.cn/ 前缀都可)
                     例: mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130
  [platform]         amd64(默认) | arm64 | arm64,amd64(异构)

环境变量(均有默认值, 可覆盖):
  JUMPER_HOST    跳板机地址      (默认 192.168.144.101)
  JUMPER_PORT    跳板机端口      (默认 52022)
  JUMPER_USER    跳板机用户      (默认 fangyuan)
  JUMPER_KEY     跳板机私钥路径  (默认 ~/.ssh/fy-qq-jumper.pem)
  HOST_146       执行机地址      (默认 192.168.152.146)
  HOST_146_USER  执行机用户      (默认 root)
  MIRROR         内网镜像源      (默认 registry.alauda.cn:60070)

示例:
  import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130
  import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130 arm64
  import_image.sh 192.168.136.182:11443 mlops/vllm-server:v0.20.2-rc.7.g077e559-cu130 arm64,amd64
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
  usage
  [[ $# -lt 2 ]] && exit 1 || exit 0
fi

TARGET_REGISTRY="$1"
IMAGE="$2"
PLATFORM="${3:-amd64}"

JUMPER_HOST="${JUMPER_HOST:-192.168.144.101}"
JUMPER_PORT="${JUMPER_PORT:-52022}"
JUMPER_USER="${JUMPER_USER:-fangyuan}"
JUMPER_KEY="${JUMPER_KEY:-$HOME/.ssh/fy-qq-jumper.pem}"
HOST_146="${HOST_146:-192.168.152.146}"
HOST_146_USER="${HOST_146_USER:-root}"
MIRROR="${MIRROR:-registry.alauda.cn:60070}"

case "$PLATFORM" in
  amd64|arm64|arm64,amd64) ;;
  *) echo "platform 只能是 amd64 / arm64 / arm64,amd64, 实际: $PLATFORM" >&2; exit 1 ;;
esac

if [[ ! -f "$JUMPER_KEY" ]]; then
  echo "找不到跳板机私钥: $JUMPER_KEY" >&2
  echo "请把私钥放到该路径, 或运行时用 JUMPER_KEY=/path/to/key 指定。" >&2
  exit 1
fi
chmod 600 "$JUMPER_KEY" 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER_LOCAL="$SCRIPT_DIR/push-image.sh"
WRAPPER_REMOTE="/root/push-image.sh"

if [[ ! -f "$WRAPPER_LOCAL" ]]; then
  echo "找不到包装脚本: $WRAPPER_LOCAL" >&2
  exit 1
fi

# 跳板机连接选项（StrictHostKeyChecking=accept-new 首连自动接受，避免交互卡住）
JUMP_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=10)
# 第二跳（跳板机 -> 146）的 ssh 选项，作为字符串嵌进远端命令
HOP2_OPTS="-o StrictHostKeyChecking=accept-new"

echo "==> [1/2] 部署包装脚本到 ${HOST_146}:${WRAPPER_REMOTE}"
DEPLOY_146="cat > ${WRAPPER_REMOTE} && chmod +x ${WRAPPER_REMOTE} && echo deployed"
JUMPER_DEPLOY="ssh ${HOP2_OPTS} ${HOST_146_USER}@${HOST_146} '${DEPLOY_146}'"
ssh "${JUMP_OPTS[@]}" -i "$JUMPER_KEY" -p "$JUMPER_PORT" "${JUMPER_USER}@${JUMPER_HOST}" \
  "$JUMPER_DEPLOY" < "$WRAPPER_LOCAL"

echo "==> [2/2] 在 ${HOST_146} 上导入镜像"
echo "    目标=${TARGET_REGISTRY}  镜像=${IMAGE}  平台=${PLATFORM}  mirror=${MIRROR}"
# 远端在 146 上执行的命令（单引号包裹各参数，假定参数内无单引号）
REMOTE_146="MIRROR='${MIRROR}' bash ${WRAPPER_REMOTE} '${TARGET_REGISTRY}' '${IMAGE}' '${PLATFORM}'"
# 跳板机上执行的命令：再 ssh 到 146 并把上面的命令作为一个双引号参数传过去
JUMPER_RUN="ssh ${HOP2_OPTS} ${HOST_146_USER}@${HOST_146} \"${REMOTE_146}\""
# </dev/null：让 pushimages.sh 末尾的 read 立即收到 EOF（默认执行清理），避免挂起
ssh "${JUMP_OPTS[@]}" -i "$JUMPER_KEY" -p "$JUMPER_PORT" "${JUMPER_USER}@${JUMPER_HOST}" \
  "$JUMPER_RUN" < /dev/null

echo "==> 完成: ${IMAGE} -> ${TARGET_REGISTRY} (${PLATFORM})"
