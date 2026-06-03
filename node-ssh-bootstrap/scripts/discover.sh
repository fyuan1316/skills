#!/usr/bin/env bash
# discover.sh — inventory what you'd bootstrap: the libvirt VMs running on the
# physical host AND the Kubernetes nodes of the target cluster (so you can see which
# VMs are cluster nodes and which are standalone).
#
# Usage:
#   discover.sh                       # uses env defaults
#   discover.sh --ssh-host npuserver --kubectl kos2 --libvirt-net default
#
# Env defaults (see env.example): SSH_HOST, KUBECTL, LIBVIRT_NET
set -euo pipefail

SSH_HOST="${SSH_HOST:-npuserver}"
KUBECTL="${KUBECTL:-kos2}"
LIBVIRT_NET="${LIBVIRT_NET:-default}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh-host)    SSH_HOST="${2:-}"; shift 2 ;;
    --kubectl)     KUBECTL="${2:-}"; shift 2 ;;
    --libvirt-net) LIBVIRT_NET="${2:-}"; shift 2 ;;
    -h|--help)     sed -n '2,12p' "$0" >&2; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

ssh "$SSH_HOST" "KUBECTL='$KUBECTL' LIBVIRT_NET='$LIBVIRT_NET' bash -s" <<'REMOTE'
echo "==================== libvirt VMs on $(hostname) ===================="
if command -v virsh >/dev/null 2>&1; then
  virsh list --all
  echo "--- DHCP leases (net: $LIBVIRT_NET) → VM IPs ---"
  virsh net-dhcp-leases "$LIBVIRT_NET" 2>/dev/null || echo "(no leases / net '$LIBVIRT_NET' not found)"
else
  echo "(virsh not present — host is not the libvirt hypervisor)"
fi
echo
echo "==================== Kubernetes nodes (via $KUBECTL) ===================="
$KUBECTL get nodes -o wide 2>&1 || echo "(kubectl wrapper '$KUBECTL' not usable here)"
REMOTE
